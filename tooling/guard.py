from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from .adapter import ToolCall
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


def detect_tool_refusal(response_text: str) -> Optional[str]:
    text = str(response_text or "").strip()
    if not text:
        return None

    for pattern in REFUSAL_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


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
) -> str:
    choice = tool_choice or {"mode": "auto"}
    mode = str(choice.get("mode", "auto"))

    if reason == "continue":
        return (
            "Continue exactly where you stopped and finish the pending tool call. "
            "Use the same tool-calling format required by the system instructions. "
            "Output only the remaining content needed to complete it."
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
