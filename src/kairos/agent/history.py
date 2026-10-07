from __future__ import annotations

import json
from typing import Any

from kairos.db.models import ConversationMessage

HISTORY_BUDGET_TOKENS = 12_000

NOT_CONFIRMED = (
    "Nicht ausgeführt: der Nutzer hat diesen Vorschlag weder bestätigt noch abgelehnt."
)


def tool_result(summary: str) -> dict[str, Any]:
    return {"summary": summary, "data": None, "meta": {}}


def tool_result_json(summary: str) -> str:
    return json.dumps(tool_result(summary), ensure_ascii=False)


def _is_not_confirmed(message: dict[str, Any]) -> bool:
    try:
        parsed = json.loads(message.get("content") or "")
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("summary") == NOT_CONFIRMED


def repair_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # providers need every call answered directly after its assistant message, exactly once
    results: dict[str, dict[str, Any]] = {}
    for m in messages:
        if m["role"] != "tool":
            continue
        current = results.get(m["tool_call_id"])
        if current is None or (_is_not_confirmed(current) and not _is_not_confirmed(m)):
            results[m["tool_call_id"]] = m
    repaired: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "tool":
            continue
        repaired.append(m)
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                repaired.append(results.get(tc["id"]) or {
                    "role": "tool", "tool_call_id": tc["id"],
                    "content": tool_result_json(NOT_CONFIRMED),
                })
    return repaired


def estimate_tokens(obj: Any) -> int:
    return len(json.dumps(obj, ensure_ascii=False)) // 4


def split_turns(messages: list[ConversationMessage]) -> list[list[ConversationMessage]]:
    turns: list[list[ConversationMessage]] = []
    for m in messages:
        if m.role == "user" or not turns:
            turns.append([])
        turns[-1].append(m)
    return turns


def _turn_tokens(turn: list[ConversationMessage]) -> int:
    return estimate_tokens(
        [{"role": m.role, "content": m.content, "tool_calls": m.tool_calls} for m in turn]
    )


def window_turns(
    turns: list[list[ConversationMessage]], budget_tokens: int
) -> tuple[list[list[ConversationMessage]], list[list[ConversationMessage]]]:
    used = 0
    start = len(turns)
    for i in range(len(turns) - 1, -1, -1):
        used += _turn_tokens(turns[i])
        # the newest turn is kept even when it alone exceeds the budget
        if used > budget_tokens and i != len(turns) - 1:
            break
        start = i
    return turns[start:], turns[:start]
