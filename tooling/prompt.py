from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

from .adapter import ToolSpec


COMMAND_TOOL_RE = re.compile(
    r"(?:^|[_-])(bash|shell|command|cmd|terminal|exec|execute|run)(?:[_-]|$)",
    re.IGNORECASE,
)
READ_TOOL_RE = re.compile(
    r"(?:^|[_-])(read|cat|open|load|get|fetch)(?:[_-]|$)",
    re.IGNORECASE,
)
WRITE_TOOL_RE = re.compile(
    r"(?:^|[_-])(write|edit|update|replace|append|create|save)(?:[_-]|$)",
    re.IGNORECASE,
)
SEARCH_TOOL_RE = re.compile(
    r"(?:^|[_-])(search|grep|find|query|locate|scan)(?:[_-]|$)",
    re.IGNORECASE,
)
LIST_TOOL_RE = re.compile(
    r"(?:^|[_-])(list|ls|dir|tree|browse)(?:[_-]|$)",
    re.IGNORECASE,
)

COMMAND_PARAM_CANDIDATES = (
    "command",
    "cmd",
    "script",
    "shell_command",
    "bash_command",
)
PATH_PARAM_CANDIDATES = (
    "path",
    "file_path",
    "filename",
    "target_path",
    "directory",
)
CONTENT_PARAM_CANDIDATES = (
    "content",
    "file_text",
    "text",
    "body",
)
QUERY_PARAM_CANDIDATES = (
    "query",
    "pattern",
    "keyword",
    "search",
)


def normalize_openai_tool_choice(tool_choice: Any) -> Dict[str, Any]:
    if tool_choice in (None, "", "auto"):
        return {"mode": "auto"}
    if tool_choice in ("required", "any"):
        return {"mode": "any"}
    if isinstance(tool_choice, dict):
        if tool_choice.get("type") == "function":
            function = tool_choice.get("function") or {}
            name = function.get("name")
            if name:
                return {"mode": "tool", "name": str(name)}
        if tool_choice.get("type") == "any":
            return {"mode": "any"}
    return {"mode": "auto"}


def normalize_anthropic_tool_choice(tool_choice: Any) -> Dict[str, Any]:
    if not isinstance(tool_choice, dict):
        return {"mode": "auto"}
    choice_type = str(tool_choice.get("type", "auto"))
    if choice_type == "any":
        return {"mode": "any"}
    if choice_type == "tool" and tool_choice.get("name"):
        return {"mode": "tool", "name": str(tool_choice["name"])}
    return {"mode": "auto"}


def _compact_schema(schema: Optional[Dict[str, Any]]) -> str:
    if not isinstance(schema, dict):
        return "{}"

    properties = schema.get("properties")
    if not isinstance(properties, dict) or not properties:
        return "{}"

    required = set(schema.get("required") or [])
    parts = []
    for name, prop in properties.items():
        prop = prop if isinstance(prop, dict) else {}
        prop_type = str(prop.get("type", "any"))
        if prop.get("enum"):
            prop_type = "|".join(str(item) for item in prop["enum"])
        elif prop_type == "array" and isinstance(prop.get("items"), dict):
            item_type = str(prop["items"].get("type", "any"))
            prop_type = f"{item_type}[]"
        suffix = "!" if name in required else "?"
        parts.append(f"{name}{suffix}: {prop_type}")
    return "{" + ", ".join(parts) + "}"


def _build_tool_catalog(tool_specs: Iterable[ToolSpec]) -> str:
    lines = []
    for tool in tool_specs:
        line = f"- {tool.name}"
        if tool.description:
            line += f": {tool.description}"
        schema = _compact_schema(tool.parameters)
        if schema != "{}":
            line += f"\n  Params: {schema}"
        lines.append(line)
    return "\n".join(lines)


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


def _tool_descriptor(tool: ToolSpec) -> str:
    properties = ", ".join(str(name) for name in _tool_properties(tool))
    return " ".join(
        part for part in [tool.name, tool.description or "", properties] if part
    ).lower()


def _is_command_tool(tool: ToolSpec) -> bool:
    descriptor = _tool_descriptor(tool)
    return bool(
        COMMAND_TOOL_RE.search(tool.name)
        or any(keyword in descriptor for keyword in ("shell", "terminal", "command"))
        or _find_param_name(tool, COMMAND_PARAM_CANDIDATES)
    )


def _is_read_tool(tool: ToolSpec) -> bool:
    descriptor = _tool_descriptor(tool)
    return bool(
        READ_TOOL_RE.search(tool.name)
        or "read file" in descriptor
        or (
            _find_param_name(tool, PATH_PARAM_CANDIDATES)
            and not _find_param_name(tool, CONTENT_PARAM_CANDIDATES)
            and not _find_param_name(tool, COMMAND_PARAM_CANDIDATES)
        )
    )


def _is_write_tool(tool: ToolSpec) -> bool:
    descriptor = _tool_descriptor(tool)
    return bool(
        WRITE_TOOL_RE.search(tool.name)
        or "write file" in descriptor
        or (
            _find_param_name(tool, PATH_PARAM_CANDIDATES)
            and _find_param_name(tool, CONTENT_PARAM_CANDIDATES)
        )
    )


def _is_search_tool(tool: ToolSpec) -> bool:
    descriptor = _tool_descriptor(tool)
    return bool(
        SEARCH_TOOL_RE.search(tool.name)
        or "search" in descriptor
        or _find_param_name(tool, QUERY_PARAM_CANDIDATES)
    )


def _is_list_tool(tool: ToolSpec) -> bool:
    descriptor = _tool_descriptor(tool)
    return bool(
        LIST_TOOL_RE.search(tool.name)
        or "directory" in descriptor
        or "list files" in descriptor
    )


def _build_example_params(tool: ToolSpec) -> Dict[str, Any]:
    command_param = _find_param_name(tool, COMMAND_PARAM_CANDIDATES)
    path_param = _find_param_name(tool, PATH_PARAM_CANDIDATES)
    content_param = _find_param_name(tool, CONTENT_PARAM_CANDIDATES)
    query_param = _find_param_name(tool, QUERY_PARAM_CANDIDATES)

    if _is_command_tool(tool):
        return {
            command_param or "command": (
                "cd /workspace/project && source venv/bin/activate && python test.py"
            )
        }
    if _is_read_tool(tool):
        return {path_param or "path": "src/main.py"}
    if _is_write_tool(tool):
        return {
            path_param or "path": "logs/test-output.txt",
            content_param or "content": "Test completed successfully.",
        }
    if _is_search_tool(tool):
        return {query_param or "query": "TODO"}
    if _is_list_tool(tool):
        return {path_param or "path": "."}

    params: Dict[str, Any] = {}
    for key, value in list(_tool_properties(tool).items())[:2]:
        value = value if isinstance(value, dict) else {}
        if value.get("type") == "boolean":
            params[key] = True
        elif value.get("type") in {"integer", "number"}:
            params[key] = 1
        else:
            params[key] = "value"
    return params or {"input": "value"}


def _select_fewshot_tools(tool_specs: Iterable[ToolSpec], limit: int = 4) -> List[ToolSpec]:
    tool_specs = list(tool_specs)
    if not tool_specs:
        return []

    selected: List[ToolSpec] = []
    used_names = set()

    def pick(predicate) -> None:
        for tool in tool_specs:
            if tool.name in used_names:
                continue
            if predicate(tool):
                selected.append(tool)
                used_names.add(tool.name)
                return

    pick(_is_read_tool)
    pick(_is_command_tool)
    pick(_is_write_tool)
    pick(lambda tool: _is_search_tool(tool) or _is_list_tool(tool))

    for tool in tool_specs:
        if len(selected) >= limit:
            break
        if tool.name in used_names:
            continue
        selected.append(tool)
        used_names.add(tool.name)

    return selected[:limit]


def _build_example_action(tool_specs: Iterable[ToolSpec]) -> str:
    examples = _select_fewshot_tools(tool_specs)
    if not examples:
        return ""

    blocks = ["Examples:"]
    for tool in examples:
        blocks.append("```json action")
        blocks.append(
            json.dumps(
                {"tool": tool.name, "parameters": _build_example_params(tool)},
                ensure_ascii=False,
                indent=2,
            )
        )
        blocks.append("```")
    return "\n".join(blocks)


def _build_tool_choice_instruction(tool_choice: Dict[str, Any]) -> str:
    mode = tool_choice.get("mode", "auto")
    if mode == "any":
        return (
            "MANDATORY: You must call at least one tool in your next response. "
            "Return one or more `json action` blocks and do not answer with plain text only."
        )
    if mode == "tool" and tool_choice.get("name"):
        return (
            f"MANDATORY: You must call the tool `{tool_choice['name']}` in your next response. "
            "Do not answer with plain text only."
        )
    return ""


def _build_command_tool_instruction(tool_specs: Iterable[ToolSpec]) -> str:
    command_tools = [tool for tool in tool_specs if _is_command_tool(tool)]
    if not command_tools:
        return ""

    primary_tool = command_tools[0]
    command_param = _find_param_name(primary_tool, COMMAND_PARAM_CANDIDATES) or "command"
    tool_names = ", ".join(tool.name for tool in command_tools[:4])

    return "\n".join(
        [
            "Command execution rule:",
            f"- If you need to run a shell command, script, test, or chained terminal operation, call one of these tools: {tool_names}.",
            "- NEVER output a bare shell command as plain text.",
            f"- Put the full command string inside `parameters.{command_param}` of the selected command tool.",
            "- This includes commands using `cd`, `source`, `export`, `python`, `bash`, `sh`, `node`, `npm`, `uv`, `pytest`, `make`, or chained operators like `&&` and `;`.",
        ]
    )


def build_json_action_prompt(
    tool_specs: Iterable[ToolSpec],
    *,
    fewshot: bool = True,
    tool_choice: Optional[Dict[str, Any]] = None,
) -> str:
    tool_specs = list(tool_specs)
    tool_catalog = _build_tool_catalog(tool_specs)
    example = _build_example_action(tool_specs) if fewshot else ""
    choice_instruction = _build_tool_choice_instruction(tool_choice or {"mode": "auto"})
    command_instruction = _build_command_tool_instruction(tool_specs)

    prompt_parts = [
        "You have access to the following tools:",
        tool_catalog,
        "",
        "When you need to call a tool, output one or more fenced blocks in exactly this format:",
        "```json action",
        '{',
        '  "tool": "TOOL_NAME",',
        '  "parameters": {',
        '    "param": "value"',
        "  }",
        '}',
        "```",
        "",
        "Rules:",
        "- `json action` is the only supported tool-calling format in this environment.",
        "- Use one block per tool call.",
        "- If multiple independent tools are needed, output multiple blocks in the same response.",
        "- Do not wrap multiple tool calls in a larger JSON object.",
        "- Do not use provider-native tool calling, XML, or any other format.",
        "- Do not describe the tool call before or after the block unless additional plain text is really needed.",
        "- When the next step is clear, go straight to the action block without preamble.",
        "- After tool results are returned, continue the task normally.",
        "- If no tool is needed, answer in normal text.",
    ]

    if command_instruction:
        prompt_parts.extend(["", command_instruction])
    if choice_instruction:
        prompt_parts.extend(["", choice_instruction])
    if example:
        prompt_parts.extend(["", example])
    return "\n".join(prompt_parts).strip()


def build_legacy_prompt(
    tool_specs: Iterable[ToolSpec],
    *,
    protocol: str = "openai",
    tool_choice: Optional[Dict[str, Any]] = None,
) -> str:
    tool_specs = list(tool_specs)
    tool_catalog = _build_tool_catalog(tool_specs)
    choice_instruction = _build_tool_choice_instruction(tool_choice or {"mode": "auto"})

    if protocol == "anthropic":
        format_block = """When you need to use tools, return JSON in this format:
{"tool_calls":[{"name":"tool_name","input":{"param":"value"}}]}"""
    else:
        format_block = """When you need to use tools, return JSON in this format:
{"tool_calls":[{"id":"call_001","type":"function","function":{"name":"tool_name","arguments":"{\\"param\\":\\"value\\"}"}}]}"""

    prompt_parts = [
        "You have access to the following tools:",
        tool_catalog,
        "",
        format_block,
        "You may include multiple tool calls in one response when they are independent.",
    ]
    if choice_instruction:
        prompt_parts.extend(["", choice_instruction])
    return "\n".join(prompt_parts).strip()


def build_tool_prompt(
    tool_specs: Iterable[ToolSpec],
    settings: Dict[str, Any],
    *,
    protocol: str,
    tool_choice: Optional[Dict[str, Any]] = None,
) -> str:
    if settings.get("strategy") == "json_action":
        return build_json_action_prompt(
            tool_specs,
            fewshot=bool(settings.get("fewshot", True)),
            tool_choice=tool_choice,
        )
    return build_legacy_prompt(tool_specs, protocol=protocol, tool_choice=tool_choice)
