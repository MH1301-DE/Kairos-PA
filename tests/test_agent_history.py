from __future__ import annotations

import json

from kairos.agent.history import NOT_CONFIRMED, repair_history, split_turns, window_turns
from kairos.db.models import ConversationMessage


def _assistant(*ids: str) -> dict:
    return {
        "role": "assistant", "content": None,
        "tool_calls": [
            {"id": i, "type": "function", "function": {"name": "query_health", "arguments": "{}"}}
            for i in ids
        ],
    }


def test_dangling_tool_call_gets_synthetic_result_right_after_its_assistant_message() -> None:
    messages = [
        {"role": "user", "content": "a"},
        _assistant("call_1"),
        {"role": "user", "content": "b"},
    ]
    repaired = repair_history(messages)
    assert [m["role"] for m in repaired] == ["user", "assistant", "tool", "user"]
    assert repaired[2]["tool_call_id"] == "call_1"
    assert "nicht" in repaired[2]["content"].lower()


def test_existing_results_are_kept_and_only_missing_ones_added() -> None:
    messages = [
        {"role": "user", "content": "a"},
        _assistant("call_1", "call_2"),
        {"role": "tool", "tool_call_id": "call_2", "content": "{}"},
    ]
    repaired = repair_history(messages)
    tool_ids = [m["tool_call_id"] for m in repaired if m["role"] == "tool"]
    assert sorted(tool_ids) == ["call_1", "call_2"]
    assert len(repaired) == 4


def test_orphan_tool_message_without_preceding_call_is_dropped() -> None:
    messages = [
        {"role": "tool", "tool_call_id": "gone", "content": "{}"},
        {"role": "user", "content": "a"},
    ]
    assert repair_history(messages) == [{"role": "user", "content": "a"}]


def test_late_result_of_a_mid_history_call_is_moved_right_after_the_call() -> None:
    late = {"role": "tool", "tool_call_id": "call_p", "content": "{}"}
    messages = [
        {"role": "user", "content": "a"},
        _assistant("call_p"),
        {"role": "user", "content": "b"},
        {"role": "assistant", "content": "c"},
        late,
    ]
    repaired = repair_history(messages)
    assert [m["role"] for m in repaired] == ["user", "assistant", "tool", "user", "assistant"]
    assert repaired[2] is late


def test_results_follow_the_order_of_the_calls() -> None:
    messages = [
        _assistant("call_1", "call_2"),
        {"role": "tool", "tool_call_id": "call_2", "content": "2"},
        {"role": "tool", "tool_call_id": "call_1", "content": "1"},
    ]
    assert [m["tool_call_id"] for m in repair_history(messages)[1:]] == ["call_1", "call_2"]


def test_duplicate_results_keep_the_real_one_over_not_confirmed() -> None:
    closing = {
        "role": "tool", "tool_call_id": "call_p",
        "content": json.dumps({"summary": NOT_CONFIRMED, "data": None, "meta": {}},
                              ensure_ascii=False),
    }
    real = {"role": "tool", "tool_call_id": "call_p", "content": '{"summary": "angelegt"}'}
    messages = [_assistant("call_p"), closing, real, {"role": "user", "content": "x"}]
    repaired = repair_history(messages)
    assert repaired == [messages[0], real, {"role": "user", "content": "x"}]


def test_duplicate_real_results_keep_the_first() -> None:
    first = {"role": "tool", "tool_call_id": "call_1", "content": "1"}
    second = {"role": "tool", "tool_call_id": "call_1", "content": "2"}
    repaired = repair_history([_assistant("call_1"), first, second])
    assert repaired[1:] == [first]


def test_synthetic_result_keeps_umlauts_unescaped() -> None:
    repaired = repair_history([_assistant("call_1")])
    assert json.loads(repaired[1]["content"])["summary"] == NOT_CONFIRMED
    assert "bestätigt" in repaired[1]["content"]


def _msg(seq: int, role: str, content: str = "x") -> ConversationMessage:
    return ConversationMessage(
        seq=seq, role=role, content=content, tool_calls=None, tool_call_id=None
    )


def test_split_turns_starts_a_turn_at_each_user_message() -> None:
    msgs = [_msg(1, "user"), _msg(2, "assistant"), _msg(3, "tool"), _msg(4, "user")]
    assert [[m.seq for m in t] for t in split_turns(msgs)] == [[1, 2, 3], [4]]


def test_window_keeps_newest_turns_within_budget_and_evicts_oldest() -> None:
    turns = [[_msg(i, "user", "y" * 400)] for i in range(1, 6)]
    kept, evicted = window_turns(turns, budget_tokens=250)
    assert [t[0].seq for t in kept] == [4, 5]
    assert [t[0].seq for t in evicted] == [1, 2, 3]


def test_window_always_keeps_the_newest_turn() -> None:
    turns = [[_msg(1, "user", "z" * 10_000)]]
    kept, evicted = window_turns(turns, budget_tokens=10)
    assert len(kept) == 1 and evicted == []
