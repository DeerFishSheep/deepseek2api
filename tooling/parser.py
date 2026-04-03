from __future__ import annotations

import json
import re
from typing import Any, Iterable, List, Tuple

from .adapter import ToolCall, ToolSpec, normalize_tool_name
from .fixer import fix_tool_call_arguments, replace_smart_quotes


OPEN_BLOCK_RE = re.compile(r"```json(?:\s+action)?", re.IGNORECASE)


def _tolerant_json_loads(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ValueError("empty json content")

    candidates = [text, replace_smart_quotes(text)]
    for candidate in candidates:
        try:
            return json.loads(candidate)
        except Exception:
            continue
    raise ValueError("invalid json content")


def _scan_fenced_json_blocks(text: str) -> List[Tuple[int, int, str]]:
    blocks: List[Tuple[int, int, str]] = []
    for match in OPEN_BLOCK_RE.finditer(text):
        block_start = match.start()
        content_start = match.end()

        pos = content_start
        in_string = False
        closing_pos = -1

        while pos < len(text) - 2:
            char = text[pos]
            if char == '"':
                backslash_count = 0
                probe = pos - 1
                while probe >= content_start and text[probe] == "\\":
                    backslash_count += 1
                    probe -= 1
                if backslash_count % 2 == 0:
                    in_string = not in_string
                pos += 1
                continue

            if not in_string and text[pos : pos + 3] == "```":
                closing_pos = pos
                break
            pos += 1

        if closing_pos >= 0:
            content = text[content_start:closing_pos].strip()
            blocks.append((block_start, closing_pos + 3, content))
        else:
            content = text[content_start:].strip()
            if content:
                blocks.append((block_start, len(text), content))
    return blocks


def has_incomplete_json_action_block(response_text: str) -> bool:
    for match in OPEN_BLOCK_RE.finditer(response_text):
        content_start = match.end()
        pos = content_start
        in_string = False
        found_closing = False

        while pos < len(response_text) - 2:
            char = response_text[pos]
            if char == '"':
                backslash_count = 0
                probe = pos - 1
                while probe >= content_start and response_text[probe] == "\\":
                    backslash_count += 1
                    probe -= 1
                if backslash_count % 2 == 0:
                    in_string = not in_string
                pos += 1
                continue

            if not in_string and response_text[pos : pos + 3] == "```":
                found_closing = True
                break
            pos += 1

        if not found_closing:
            return True
    return False


def _parse_json_action_object(
    parsed: Any,
    tool_specs: Iterable[ToolSpec],
    fix_arguments: bool,
) -> ToolCall | None:
    if not isinstance(parsed, dict):
        return None

    tool_name = parsed.get("tool") or parsed.get("name")
    if not tool_name:
        return None

    arguments = (
        parsed.get("parameters")
        if "parameters" in parsed
        else parsed.get("arguments", parsed.get("input", {}))
    )
    if fix_arguments:
        arguments = fix_tool_call_arguments(str(tool_name), arguments)
    elif not isinstance(arguments, dict):
        arguments = {"input": arguments}

    normalized_name = normalize_tool_name(str(tool_name), tool_specs)
    return ToolCall(name=normalized_name, arguments=arguments)


def parse_json_action_blocks(
    response_text: str,
    tool_specs: Iterable[ToolSpec],
    *,
    fix_arguments: bool = True,
) -> Tuple[List[ToolCall], str]:
    blocks = _scan_fenced_json_blocks(response_text)
    tool_calls: List[ToolCall] = []
    removals: List[Tuple[int, int]] = []

    for start, end, content in blocks:
        try:
            parsed = _tolerant_json_loads(content)
        except Exception:
            continue

        tool_call = _parse_json_action_object(parsed, tool_specs, fix_arguments)
        if tool_call is None:
            continue

        tool_calls.append(tool_call)
        removals.append((start, end))

    clean_text = response_text
    for start, end in reversed(removals):
        clean_text = clean_text[:start] + clean_text[end:]

    return tool_calls, clean_text.strip()


def _parse_legacy_tool_calls_container(
    parsed: Any,
    tool_specs: Iterable[ToolSpec],
    *,
    fix_arguments: bool,
) -> List[ToolCall]:
    tool_calls: List[ToolCall] = []
    if not isinstance(parsed, dict):
        return tool_calls

    items = parsed.get("tool_calls")
    if not isinstance(items, list):
        return tool_calls

    for item in items:
        if not isinstance(item, dict):
            continue

        if isinstance(item.get("function"), dict):
            name = item["function"].get("name")
            arguments = item["function"].get("arguments", {})
        else:
            name = item.get("name")
            arguments = item.get("input", item.get("arguments", {}))

        if not name:
            continue

        if fix_arguments:
            arguments = fix_tool_call_arguments(str(name), arguments)
        elif not isinstance(arguments, dict):
            arguments = {"input": arguments}

        tool_calls.append(
            ToolCall(
                name=normalize_tool_name(str(name), tool_specs),
                arguments=arguments,
            )
        )
    return tool_calls


def parse_legacy_tool_calls(
    response_text: str,
    tool_specs: Iterable[ToolSpec],
    *,
    fix_arguments: bool = True,
) -> Tuple[List[ToolCall], str]:
    candidates: List[Tuple[str, str]] = []
    stripped = response_text.strip()
    if stripped:
        candidates.append((stripped, stripped))

    for _, _, content in _scan_fenced_json_blocks(response_text):
        candidates.append((content, content))

    pattern = r'\{[\s\S]*?"tool_calls"\s*:\s*\[[\s\S]*?\]\s*\}'
    for match in re.finditer(pattern, response_text):
        candidates.append((match.group(0), match.group(0)))

    seen = set()
    for candidate, removable in candidates:
        marker = candidate.strip()
        if not marker or marker in seen:
            continue
        seen.add(marker)
        try:
            parsed = _tolerant_json_loads(candidate)
        except Exception:
            continue

        tool_calls = _parse_legacy_tool_calls_container(
            parsed, tool_specs, fix_arguments=fix_arguments
        )
        if not tool_calls:
            continue

        clean_text = response_text.replace(removable, "", 1).strip()
        return tool_calls, clean_text

    return [], response_text.strip()


def parse_tool_response(
    response_text: str,
    strategy: str,
    tool_specs: Iterable[ToolSpec],
    *,
    fix_arguments: bool = True,
    allow_fallback: bool = True,
) -> Tuple[List[ToolCall], str]:
    if strategy == "json_action":
        tool_calls, clean_text = parse_json_action_blocks(
            response_text, tool_specs, fix_arguments=fix_arguments
        )
        if tool_calls or not allow_fallback:
            return tool_calls, clean_text

    return parse_legacy_tool_calls(
        response_text, tool_specs, fix_arguments=fix_arguments
    )
