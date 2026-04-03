from __future__ import annotations

from typing import Any, Dict


def get_tool_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    parser_config = config.get("tool_call_parser") or {}

    strategy = str(config.get("tool_call_strategy", "legacy")).strip().lower()
    if strategy not in {"legacy", "json_action"}:
        strategy = "legacy"

    return {
        "strategy": strategy,
        "fewshot": bool(config.get("tool_call_fewshot", True)),
        "retry_on_empty": bool(config.get("tool_call_retry_on_empty", True)),
        "retry_on_refusal": bool(config.get("tool_call_retry_on_refusal", True)),
        "auto_continue": bool(config.get("tool_call_auto_continue", True)),
        "retry_max_attempts": max(0, int(config.get("tool_call_retry_max_attempts", 1))),
        "fix_arguments": bool(parser_config.get("fix_arguments", True)),
    }
