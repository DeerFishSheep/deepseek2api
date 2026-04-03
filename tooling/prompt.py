from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from .adapter import ToolSpec


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


def _build_example_action(tool_specs: Iterable[ToolSpec]) -> str:
    tool_specs = list(tool_specs)
    if not tool_specs:
        return ""

    tool = tool_specs[0]
    params: Dict[str, Any] = {}
    if isinstance(tool.parameters, dict):
        properties = tool.parameters.get("properties")
        if isinstance(properties, dict):
            for key, value in list(properties.items())[:2]:
                value = value if isinstance(value, dict) else {}
                if value.get("type") == "boolean":
                    params[key] = True
                elif value.get("type") in {"integer", "number"}:
                    params[key] = 1
                else:
                    params[key] = "value"
    if not params:
        params = {"input": "value"}

    return (
        "Example:\n"
        "```json action\n"
        + json.dumps(
            {"tool": tool.name, "parameters": params},
            ensure_ascii=False,
            indent=2,
        )
        + "\n```"
    )


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
        "- Use one block per tool call.",
        "- If multiple independent tools are needed, output multiple blocks in the same response.",
        "- Do not wrap multiple tool calls in a larger JSON object.",
        "- Do not describe the tool call before or after the block unless additional plain text is really needed.",
        "- After tool results are returned, continue the task normally.",
        "- If no tool is needed, answer in normal text.",
    ]

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
