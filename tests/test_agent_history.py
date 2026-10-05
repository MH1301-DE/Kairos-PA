from __future__ import annotations

from kairos.agent.history import repair_history


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
