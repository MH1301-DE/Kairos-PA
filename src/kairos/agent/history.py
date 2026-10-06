from __future__ import annotations

import json
from typing import Any

from kairos.db.models import ConversationMessage

HISTORY_BUDGET_TOKENS = 12_000

NOT_CONFIRMED = (
    "Nicht ausgeführt: der Nutzer hat diesen Vorschlag weder bestätigt noch abgelehnt."
)


def _synthetic_result(tool_call_id: str) -> dict[str, Any]:
    return {
        "role": "tool", "tool_call_id": tool_call_id,
        "content": json.dumps({"summary": NOT_CONFIRMED, "data": None, "meta": {}}),
    }


def repair_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    # providers reject tool calls without results and results without calls
    answered = {m["tool_call_id"] for m in messages if m["role"] == "tool"}
    known_calls: set[str] = set()
    repaired: list[dict[str, Any]] = []
    for m in messages:
        if m["role"] == "tool":
            if m["tool_call_id"] in known_calls:
                repaired.append(m)
            continue
        repaired.append(m)
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                known_calls.add(tc["id"])
                if tc["id"] not in answered:
                    repaired.append(_synthetic_result(tc["id"]))
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
