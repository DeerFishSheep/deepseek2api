from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class ToolSpec:
    name: str
    description: str = ""
    parameters: Optional[Dict[str, Any]] = None


@dataclass
class ToolCall:
    name: str
    arguments: Dict[str, Any]


def extract_openai_tools(tools: Iterable[Dict[str, Any]]) -> List[ToolSpec]:
    tool_specs: List[ToolSpec] = []
    for tool in tools or []:
        function = tool.get("function", {}) if isinstance(tool, dict) else {}
        tool_specs.append(
            ToolSpec(
                name=str(function.get("name", "unknown")),
                description=str(function.get("description", "")),
                parameters=function.get("parameters") or {},
            )
        )
    return tool_specs


def extract_anthropic_tools(tools: Iterable[Dict[str, Any]]) -> List[ToolSpec]:
    tool_specs: List[ToolSpec] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        tool_specs.append(
            ToolSpec(
                name=str(tool.get("name", "unknown")),
                description=str(tool.get("description", "")),
                parameters=tool.get("input_schema") or {},
            )
        )
    return tool_specs


def normalize_tool_name(name: str, tool_specs: Iterable[ToolSpec]) -> str:
    candidates = {tool.name.lower(): tool.name for tool in tool_specs}
    return candidates.get(name.lower(), name)


def to_openai_tool_calls(tool_calls: Iterable[ToolCall]) -> List[Dict[str, Any]]:
    openai_calls: List[Dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        openai_calls.append(
            {
                "id": f"call_{index + 1:03d}",
                "type": "function",
                "function": {
                    "name": tool_call.name,
                    "arguments": json.dumps(
                        tool_call.arguments, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            }
        )
    return openai_calls


def to_anthropic_tool_use_blocks(
    tool_calls: Iterable[ToolCall],
) -> List[Dict[str, Any]]:
    blocks: List[Dict[str, Any]] = []
    for index, tool_call in enumerate(tool_calls):
        blocks.append(
            {
                "type": "tool_use",
                "id": f"toolu_{int(time.time())}_{random.randint(1000, 9999)}_{index}",
                "name": tool_call.name,
                "input": tool_call.arguments,
            }
        )
    return blocks
