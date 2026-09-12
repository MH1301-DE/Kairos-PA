from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from kairos.agent import dispatcher as dispatcher_module
from kairos.agent.dispatcher import Proposal, ToolCall, dispatch
from kairos.agent.tools import ToolSpec


def _fake_spec(
    name: str, risk_class: str, requires_confirmation: bool, handler: AsyncMock
) -> ToolSpec:
    return ToolSpec(
        name=name, risk_class=risk_class,  # type: ignore[arg-type]
        requires_confirmation=requires_confirmation, json_schema={}, handler=handler,
    )


@pytest.mark.asyncio
async def test_read_tool_executes_immediately(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AsyncMock(return_value={"summary": "ok", "data": {}, "meta": {}})
    monkeypatch.setattr(
        dispatcher_module, "TOOLS_BY_NAME",
        {"fake_read": _fake_spec("fake_read", "read", False, handler)},
    )

    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(name="fake_read", arguments={"x": 1}), pending_confirmation=False,
    )

    handler.assert_called_once()
    assert result == {"summary": "ok", "data": {}, "meta": {}}


@pytest.mark.asyncio
async def test_remember_executes_immediately_despite_write_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AsyncMock(return_value={"summary": "gemerkt"})
    monkeypatch.setattr(
        dispatcher_module, "TOOLS_BY_NAME",
        {"remember": _fake_spec("remember", "write", False, handler)},
    )

    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(name="remember", arguments={"content": "hi"}),
        pending_confirmation=False,
    )

    handler.assert_called_once()
    assert result == {"summary": "gemerkt"}


@pytest.mark.asyncio
async def test_write_tool_without_confirmation_returns_proposal_and_never_calls_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AsyncMock()
    monkeypatch.setattr(
        dispatcher_module, "TOOLS_BY_NAME",
        {"propose_calendar_event": _fake_spec("propose_calendar_event", "write", True, handler)},
    )

    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(
            name="propose_calendar_event",
            arguments={
                "summary": "Long Run",
                "start_at": "2026-09-01T07:00:00",
                "end_at": "2026-09-01T08:00:00",
            },
        ),
        pending_confirmation=False,
    )

    handler.assert_not_called()
    assert isinstance(result, Proposal)
    assert result.tool_name == "propose_calendar_event"
    assert "Long Run" in result.summary


@pytest.mark.asyncio
async def test_write_tool_with_pending_confirmation_calls_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = AsyncMock(return_value={"summary": "created"})
    monkeypatch.setattr(
        dispatcher_module, "TOOLS_BY_NAME",
        {"propose_calendar_event": _fake_spec("propose_calendar_event", "write", True, handler)},
    )

    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(name="propose_calendar_event", arguments={"summary": "Long Run"}),
        pending_confirmation=True,
    )

    handler.assert_called_once()
    assert result == {"summary": "created"}


@pytest.mark.asyncio
async def test_destructive_tool_also_needs_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = AsyncMock()
    monkeypatch.setattr(
        dispatcher_module, "TOOLS_BY_NAME",
        {
            "delete_calendar_event": _fake_spec(
                "delete_calendar_event", "destructive", True, handler
            )
        },
    )

    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(name="delete_calendar_event", arguments={"event_id": "abc"}),
        pending_confirmation=False,
    )

    handler.assert_not_called()
    assert isinstance(result, Proposal)
    assert result.tool_name == "delete_calendar_event"


@pytest.mark.asyncio
async def test_dispatch_raises_on_unknown_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dispatcher_module, "TOOLS_BY_NAME", {})

    with pytest.raises(ValueError, match="Unknown tool"):
        await dispatch(
            object(), user_id=uuid4(),  # type: ignore[arg-type]
            tool_call=ToolCall(name="not_a_tool", arguments={}), pending_confirmation=False,
        )


# The tests below use the REAL CORE_TOOLS registration (not a monkeypatched
# fake spec) -- unlike the tests above, these catch an actual mistake in how
# plan_commit/plan_adjust are registered in tools.py (e.g. someone flipping
# requires_confirmation=False by accident), not just the dispatcher's own logic.


@pytest.mark.asyncio
async def test_real_plan_commit_requires_confirmation() -> None:
    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(name="plan_commit", arguments={"plan_id": str(uuid4())}),
        pending_confirmation=False,
    )
    assert isinstance(result, Proposal)
    assert result.tool_name == "plan_commit"


@pytest.mark.asyncio
async def test_real_plan_adjust_requires_confirmation() -> None:
    result = await dispatch(
        object(), user_id=uuid4(),  # type: ignore[arg-type]
        tool_call=ToolCall(
            name="plan_adjust", arguments={"plan_id": str(uuid4()), "reason": "Stress"}
        ),
        pending_confirmation=False,
    )
    assert isinstance(result, Proposal)
    assert result.tool_name == "plan_adjust"


@pytest.mark.asyncio
async def test_real_plan_propose_and_progress_are_read_class() -> None:
    from kairos.agent.tools import TOOLS_BY_NAME

    assert TOOLS_BY_NAME["plan_propose"].risk_class == "read"
    assert TOOLS_BY_NAME["plan_progress"].risk_class == "read"
