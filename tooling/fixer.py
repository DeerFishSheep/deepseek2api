from __future__ import annotations

import json
from typing import Any, Dict


SMART_QUOTE_MAP = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u0060": "`",
    }
)


ALIAS_GROUPS = [
    ("path", "file_path"),
    ("content", "file_text"),
    ("old_text", "old_string"),
    ("new_text", "new_string"),
    ("command", "cmd"),
]


def replace_smart_quotes(text: str) -> str:
    return text.translate(SMART_QUOTE_MAP)


def _normalize_strings(value: Any) -> Any:
    if isinstance(value, str):
        return replace_smart_quotes(value)
    if isinstance(value, list):
        return [_normalize_strings(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _normalize_strings(item) for key, item in value.items()}
    return value


def _mirror_aliases(arguments: Dict[str, Any]) -> Dict[str, Any]:
    for left, right in ALIAS_GROUPS:
        if left in arguments and right not in arguments:
            arguments[right] = arguments[left]
        elif right in arguments and left not in arguments:
            arguments[left] = arguments[right]
    return arguments


def fix_tool_call_arguments(tool_name: str, arguments: Any) -> Dict[str, Any]:
    if arguments is None:
        normalized: Any = {}
    elif isinstance(arguments, str):
        text = replace_smart_quotes(arguments).strip()
        if not text:
            normalized = {}
        else:
            try:
                normalized = json.loads(text)
            except Exception:
                normalized = {"input": text}
    elif isinstance(arguments, dict):
        normalized = arguments
    else:
        normalized = {"input": arguments}

    normalized = _normalize_strings(normalized)
    if not isinstance(normalized, dict):
        return {"input": normalized}
    return _mirror_aliases(normalized)
