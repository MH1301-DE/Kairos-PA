from __future__ import annotations

import json
from typing import Any

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
