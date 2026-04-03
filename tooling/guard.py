from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from .adapter import ToolCall, ToolSpec
from .parser import has_incomplete_json_action_block


REFUSAL_PATTERNS = [
    re.compile(
        r"\b(?:cannot|can't|can not|unable to|won't|will not|do not|don't)\b"
        r"[\s\S]{0,80}\b(?:use|call|invoke|run|access|execute)\b"
        r"[\s\S]{0,80}\b(?:tool|tools|function|functions)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:no access|not available|unavailable)\b[\s\S]{0,80}\b(?:tool|tools|function|functions)\b",
        re.IGNORECASE,
    ),
]

COMMAND_TOOL_RE = re.compile(
    r"(?:^|[_-])(bash|shell|command|cmd|terminal|exec|execute|run)(?:[_-]|$)",
    re.IGNORECASE,
)
SHELL_COMMAND_RE = re.compile(
    r"(?:^|(?:&&|;)\s*)(?:cd\s+\S+|source\s+\S+|export\s+[A-Z_][A-Z0-9_]*=|python(?:3)?\s+\S+|bash\s+\S+|sh\s+\S+|node\s+\S+|npm\s+(?:run|test|install|exec|start)\b|uv\s+run\b|pytest\b|make\s+\S+|\.\/\S+)",
    re.IGNORECASE,
)
COMMAND_PARAM_CANDIDATES = (
    "command",
    "cmd",
    "script",
    "shell_command",
    "bash_command",
)


def detect_tool_refusal(response_text: str) -> Optional[str]:
    text = str(response_text or "").strip()
    if not text:
        return None

    for pattern in REFUSAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


def _tool_properties(tool: ToolSpec) -> Dict[str, Any]:
    parameters = tool.parameters if isinstance(tool.parameters, dict) else {}
    properties = parameters.get("properties")
    return properties if isinstance(properties, dict) else {}


def _find_param_name(tool: ToolSpec, candidates: Iterable[str]) -> Optional[str]:
    properties = _tool_properties(tool)
    lowered = {str(name).lower(): name for name in properties}
    for candidate in candidates:
        if candidate.lower() in lowered:
            return str(lowered[candidate.lower()])
    return None


def _is_command_tool(tool: ToolSpec) -> bool:
    description = f"{tool.name} {tool.description or ''}".lower()
    return bool(
        COMMAND_TOOL_RE.search(tool.name)
        or any(keyword in description for keyword in ("shell", "terminal", "command"))
        or _find_param_name(tool, COMMAND_PARAM_CANDIDATES)
    )


def _primary_command_tool(tool_specs: Iterable[ToolSpec]) -> Optional[ToolSpec]:
    for tool in tool_specs:
        if _is_command_tool(tool):
            return tool
    return None


def detect_plain_command_text(response_text: str) -> Optional[str]:
    text = str(response_text or "").strip()
    if not text:
        return None

    if "```" in text or '"tool_calls"' in text or '"tool"' in text:
        return None

    candidate = text.strip().strip("`")
    candidate = (
        candidate.replace("\u201c", "")
        .replace("\u201d", "")
        .replace("\u2018", "")
        .replace("\u2019", "")
    )
    candidate = candidate.strip("\"'").strip()
    if not candidate:
        return None

    match = SHELL_COMMAND_RE.search(candidate)
    if not match:
        return None

    lowered = candidate.lower()
    if not (
        SHELL_COMMAND_RE.match(candidate)
        or "&&" in lowered
        or "\n" in lowered
        or "; " in lowered
    ):
        return None

    return match.group(0)


def should_retry_empty_tool_call(
    tool_choice: Dict[str, Any],
    tool_calls: Iterable[ToolCall],
    settings: Dict[str, Any],
) -> bool:
    if not settings.get("retry_on_empty", True):
        return False

    mode = str((tool_choice or {}).get("mode", "auto"))
    if mode not in {"any", "tool"}:
        return False

    return not any(True for _ in tool_calls)


def should_retry_tool_refusal(
    response_text: str,
    tool_calls: Iterable[ToolCall],
    settings: Dict[str, Any],
) -> bool:
    if not settings.get("retry_on_refusal", True):
        return False

    if any(True for _ in tool_calls):
        return False

    return detect_tool_refusal(response_text) is not None


def should_retry_command_text(
    response_text: str,
    tool_specs: Iterable[ToolSpec],
    tool_calls: Iterable[ToolCall],
    settings: Dict[str, Any],
) -> bool:
    if not settings.get("retry_on_command_text", True):
        return False

    if any(True for _ in tool_calls):
        return False

    if _primary_command_tool(tool_specs) is None:
        return False

    return detect_plain_command_text(response_text) is not None


def should_auto_continue_tool_response(
    response_text: str,
    strategy: str,
    tool_calls: Iterable[ToolCall],
    settings: Dict[str, Any],
) -> bool:
    if not settings.get("auto_continue", False):
        return False

    if strategy != "json_action":
        return False

    if any(True for _ in tool_calls):
        return False

    return has_incomplete_json_action_block(response_text)


def build_tool_retry_instruction(
    reason: str,
    tool_choice: Optional[Dict[str, Any]] = None,
    tool_specs: Optional[Iterable[ToolSpec]] = None,
) -> str:
    choice = tool_choice or {"mode": "auto"}
    mode = str(choice.get("mode", "auto"))
    command_tool = _primary_command_tool(tool_specs or [])
    command_param = (
        _find_param_name(command_tool, COMMAND_PARAM_CANDIDATES)
        if command_tool is not None
        else None
    )

    if reason == "continue":
        return (
            "Continue exactly where you stopped and finish the pending tool call. "
            "Use the same tool-calling format required by the system instructions. "
            "Output only the remaining content needed to complete it."
        )

    if reason == "command_text":
        if command_tool is not None:
            return (
                "Your previous reply output a shell command as plain text instead of using the available tool. "
                f"Retry now using a `json action` block that calls `{command_tool.name}` and place the full command string in "
                f"`parameters.{command_param or 'command'}`. "
                "Do not output the command as plain text."
            )
        return (
            "Your previous reply output a command as plain text instead of using a tool. "
            "Retry now and follow the required `json action` tool-calling format."
        )

    if reason == "refusal":
        base = (
            "Your previous reply incorrectly said that you could not use tools. "
            "Tools are available in this conversation. "
            "Retry now and follow the tool-calling format required by the system instructions."
        )
    else:
        base = (
            "Your previous reply did not produce a valid tool call. "
            "Retry now and follow the tool-calling format required by the system instructions."
        )

    if mode == "tool" and choice.get("name"):
        return (
            f"{base} You must call the tool `{choice['name']}` now. "
            "Do not answer with plain text only."
        )

    if mode == "any":
        return (
            f"{base} You must call at least one tool now. "
            "Do not answer with plain text only."
        )

    return base
