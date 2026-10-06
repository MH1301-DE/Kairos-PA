from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent import orchestrator as orchestrator_module
from kairos.agent.dispatcher import Proposal
from kairos.agent.events import AgentEvent
from kairos.agent.llm_client import NoLlmCredentialConfigured
from kairos.agent.orchestrator import run_turn, stream_turn
from kairos.repositories.conversation import ConversationRepository
from tests.agent_stream_helpers import (
    chunks_of,
    finish_chunk,
    text_chunk,
    tool_call_chunk,
)


async def _new_conversation(session: AsyncSession) -> tuple[UUID, UUID]:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    conversation = await ConversationRepository(session=session).create(
        user_id=user_id, title="Test"
    )
    await session.commit()
    return user_id, conversation.id


def _rounds(*rounds: list) -> MagicMock:
    return MagicMock(side_effect=[chunks_of(r) for r in rounds])


def _text_round(*parts: str) -> list:
    return [*(text_chunk(p) for p in parts), finish_chunk("stop")]


def _tool_round(call_id: str, name: str, arguments: str) -> list:
    return [tool_call_chunk(0, call_id, name, arguments), finish_chunk("tool_calls")]


async def _collect(session: AsyncSession, user_id: UUID, conversation_id: UUID,
                   message: str = "Frage") -> list[AgentEvent]:
    return [
        ev async for ev in stream_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message=message
        )
    ]


def test_event_serializes_as_sse() -> None:
    ev = AgentEvent(type="token", data={"text": "Grüße"})
    assert ev.to_sse() == 'event: token\ndata: {"text": "Grüße"}\n\n'


@pytest.mark.asyncio
async def test_text_round_streams_tokens_then_done(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    with patch.object(orchestrator_module, "stream_completion",
                      new=_rounds(_text_round("Hal", "lo ", "Max"))):
        events = await _collect(session, user_id, conversation_id)
    assert [e.type for e in events] == ["token", "token", "token", "done"]
    assert "".join(e.data["text"] for e in events if e.type == "token") == "Hallo Max"
    assert events[-1].data == {}
    stored = await ConversationRepository(session=session).list_messages(
        conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in stored] == ["user", "assistant"]
    assert stored[1].content == "Hallo Max"


@pytest.mark.asyncio
async def test_tool_round_then_text_round_orders_events(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    rounds = _rounds(
        _tool_round("call_1", "query_health", '{"metric_id": "hrv_baseline"}'),
        _text_round("HRV ", "ok."),
    )
    result = {"summary": "HRV 62ms", "data": {"value": 62}, "meta": {}}
    with (
        patch.object(orchestrator_module, "stream_completion", new=rounds),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=result)),
    ):
        events = await _collect(session, user_id, conversation_id)
    assert [e.type for e in events] == ["tool_start", "tool_end", "token", "token", "done"]
    assert events[0].data == {"id": "call_1", "name": "query_health"}
    assert events[1].data == {
        "id": "call_1", "name": "query_health", "summary": "HRV 62ms", "ok": True,
    }


@pytest.mark.asyncio
async def test_failed_tool_call_reports_not_ok(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    rounds = _rounds(_tool_round("call_1", "query_health", '{"metric_id": '), _text_round("x"))
    with patch.object(orchestrator_module, "stream_completion", new=rounds):
        events = await _collect(session, user_id, conversation_id)
    tool_end = next(e for e in events if e.type == "tool_end")
    assert tool_end.data["ok"] is False
    assert tool_end.data["summary"].startswith("Ungültige JSON-Argumente")


@pytest.mark.asyncio
async def test_render_call_emits_render_event(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    config = {"title": "HRV", "value": 62, "unit": "ms"}
    rounds = _rounds(
        _tool_round("call_r", "render", json.dumps({"component": "StatCard", "config": config})),
        _text_round("Hier."),
    )
    with patch.object(orchestrator_module, "stream_completion", new=rounds):
        events = await _collect(session, user_id, conversation_id)
    render = next(e for e in events if e.type == "render")
    assert render.data == {"id": "call_r", "component": "StatCard", "config": config}


@pytest.mark.asyncio
async def test_proposal_ends_the_stream(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    proposal = Proposal(tool_name="propose_calendar_event", arguments={"summary": "Lauf"},
                        summary="Termin \"Lauf\" anlegen", tool_call_id="call_p")
    rounds = _rounds(_tool_round("call_p", "propose_calendar_event", '{"summary": "Lauf"}'))
    with (
        patch.object(orchestrator_module, "stream_completion", new=rounds),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=proposal)),
    ):
        events = await _collect(session, user_id, conversation_id)
    types = [e.type for e in events]
    assert types[-2:] == ["proposal", "done"]
    assert "token" not in types
    assert events[-2].data["tool_call_id"] == "call_p"
    assert events[-2].data["tool_name"] == "propose_calendar_event"
    assert events[-2].data["summary"] == "Termin \"Lauf\" anlegen"


@pytest.mark.asyncio
async def test_disconnect_after_tool_end_keeps_committed_messages(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    rounds = _rounds(
        _tool_round("call_1", "query_health", '{"metric_id": "hrv_baseline"}'),
        _text_round("nie gesendet"),
    )
    result = {"summary": "HRV 62ms", "data": {"value": 62}, "meta": {}}
    with (
        patch.object(orchestrator_module, "stream_completion", new=rounds),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=result)),
    ):
        agen = stream_turn(session, user_id=user_id, conversation_id=conversation_id,
                           user_message="Frage")
        async for ev in agen:
            if ev.type == "tool_end":
                break
        await agen.aclose()
    await session.rollback()
    stored = await ConversationRepository(session=session).list_messages(
        conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in stored] == ["user", "assistant", "tool"]
    assert stored[1].tool_calls is not None
    assert stored[2].tool_call_id == "call_1"


@pytest.mark.asyncio
async def test_missing_llm_credential_becomes_error_event(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    failing = MagicMock(side_effect=NoLlmCredentialConfigured("no key"))
    with patch.object(orchestrator_module, "stream_completion", new=failing):
        events = await _collect(session, user_id, conversation_id)
    assert [(e.type, e.data) for e in events] == [
        ("error", {"detail": "no_llm_provider_configured"}), ("done", {}),
    ]


@pytest.mark.asyncio
async def test_provider_error_mid_stream_becomes_error_event(session: AsyncSession) -> None:
    import openai

    user_id, conversation_id = await _new_conversation(session)

    async def _broken(*_args: object, **_kwargs: object):
        yield text_chunk("Hal")
        raise openai.APIConnectionError(request=MagicMock())

    with patch.object(orchestrator_module, "stream_completion", new=MagicMock(side_effect=_broken)):
        events = await _collect(session, user_id, conversation_id)
    assert [(e.type, e.data) for e in events][-2:] == [
        ("error", {"detail": "llm_provider_error"}), ("done", {}),
    ]


@pytest.mark.asyncio
async def test_run_turn_assembles_reply_from_stream(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    with patch.object(orchestrator_module, "stream_completion",
                      new=_rounds(_text_round("Hal", "lo"))):
        result = await run_turn(session, user_id=user_id, conversation_id=conversation_id,
                                user_message="Hi")
    assert result.reply_text == "Hallo"
    assert result.proposal is None


def _two_call_round(first: tuple[str, str], second: tuple[str, str]) -> list:
    return [
        tool_call_chunk(0, "call_1", *first), tool_call_chunk(1, "call_2", *second),
        finish_chunk("tool_calls"),
    ]


async def _close_at(agen, event_type: str, nth: int) -> None:
    seen = 0
    async for ev in agen:
        if ev.type == event_type:
            seen += 1
            if seen == nth:
                break
    await agen.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize(("event_type", "nth", "expected_roles"), [
    ("tool_start", 1, ["user"]),
    ("tool_start", 2, ["user"]),
    ("tool_end", 1, ["user", "assistant", "tool", "tool"]),
])
async def test_tool_round_is_persisted_all_or_nothing(
    session: AsyncSession, event_type: str, nth: int, expected_roles: list[str]
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    args = '{"metric_id": "hrv_baseline"}'
    rounds = _rounds(
        _two_call_round(("query_health", args), ("query_health", args)), _text_round("x")
    )
    result = {"summary": "HRV 62ms", "data": {"value": 62}, "meta": {}}
    with (
        patch.object(orchestrator_module, "stream_completion", new=rounds),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=result)),
    ):
        await _close_at(
            stream_turn(session, user_id=user_id, conversation_id=conversation_id,
                        user_message="Frage"),
            event_type, nth,
        )
    await session.rollback()
    stored = await ConversationRepository(session=session).list_messages(
        conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in stored] == expected_roles


@pytest.mark.asyncio
async def test_disconnect_mid_round_does_not_commit_a_remembered_entry(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    rounds = _rounds(
        _two_call_round(("remember", '{"content": "mag keine Sprints"}'),
                        ("query_health", '{"metric_id": "hrv_baseline"}')),
        _text_round("x"),
    )
    with patch.object(orchestrator_module, "stream_completion", new=rounds):
        await _close_at(
            stream_turn(session, user_id=user_id, conversation_id=conversation_id,
                        user_message="Ich mag keine Sprints."),
            "tool_start", 2,
        )
    await session.rollback()
    count = await session.scalar(
        text("SELECT count(*) FROM agent_memory WHERE user_id = :u"), {"u": str(user_id)}
    )
    assert count == 0


@pytest.mark.asyncio
async def test_handler_db_error_becomes_error_result_without_losing_the_round(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)

    async def _broken_handler(sess: AsyncSession, **_kwargs: object) -> dict:
        await sess.execute(text("SELECT * FROM table_that_does_not_exist"))
        return {}

    rounds = _rounds(
        _tool_round("call_1", "query_health", '{"metric_id": "hrv_baseline"}'),
        _text_round("Ging nicht."),
    )
    with (
        patch.object(orchestrator_module, "stream_completion", new=rounds),
        patch.object(orchestrator_module, "dispatch", new=_broken_handler),
    ):
        events = await _collect(session, user_id, conversation_id)
    assert next(e for e in events if e.type == "tool_end").data["ok"] is False
    assert events[-1].type == "done"
    stored = await ConversationRepository(session=session).list_messages(
        conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in stored] == ["user", "assistant", "tool", "assistant"]
