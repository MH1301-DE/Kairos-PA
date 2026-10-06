from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import pytest
from litellm.types.utils import ChatCompletionMessageToolCall, Function
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent import orchestrator as orchestrator_module
from kairos.agent.dispatcher import Proposal
from kairos.agent.orchestrator import run_turn
from kairos.repositories.conversation import ConversationRepository
from tests.agent_stream_helpers import stream_forever, stream_rounds


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


def _fake_response(
    content: str | None, tool_calls: list[ChatCompletionMessageToolCall] | None = None
):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


def _fake_tool_call(call_id: str, name: str, arguments: str) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id=call_id, type="function", function=Function(name=name, arguments=arguments)
    )


async def _new_conversation(session: AsyncSession) -> tuple[UUID, UUID]:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="Test")
    await session.commit()
    return user_id, conversation.id


@pytest.mark.asyncio
async def test_plain_text_reply_ends_the_turn(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)

    with (
        patch.object(
            orchestrator_module, "stream_completion",
            new=stream_forever(_fake_response("Du bist gut erholt.")),
        ),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock()) as mock_dispatch,
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id,
            user_message="Wie erholt bin ich?",
        )

    assert result.reply_text == "Du bist gut erholt."
    assert result.proposal is None
    mock_dispatch.assert_not_called()

    repo = ConversationRepository(session=session)
    messages = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_tool_call_then_plain_text_completes_two_rounds(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    tool_call = _fake_tool_call("call_1", "query_health", '{"metric_id": "hrv_baseline"}')
    responses = [
        _fake_response(None, [tool_call]),
        _fake_response("HRV liegt im Normalbereich."),
    ]
    tool_result = {"summary": "HRV 62ms", "data": {"value": 62}, "meta": {}}

    with (
        patch.object(
            orchestrator_module, "stream_completion", new=stream_rounds(*responses)
        ) as mock_stream_completion,
        patch.object(
            orchestrator_module, "dispatch", new=AsyncMock(return_value=tool_result)
        ) as mock_dispatch,
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id,
            user_message="Wie erholt bin ich?",
        )

    assert mock_stream_completion.call_count == 2
    mock_dispatch.assert_called_once()
    call_kwargs = mock_dispatch.call_args.kwargs
    assert call_kwargs["tool_call"].name == "query_health"
    assert call_kwargs["tool_call"].arguments == {"metric_id": "hrv_baseline"}
    assert call_kwargs["pending_confirmation"] is False
    assert result.reply_text == "HRV liegt im Normalbereich."

    repo = ConversationRepository(session=session)
    messages = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool", "assistant"]
    assert messages[2].tool_call_id == "call_1"


@pytest.mark.asyncio
async def test_proposal_short_circuits_without_a_second_completion_call(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    tool_call = _fake_tool_call("call_1", "propose_calendar_event", '{"summary": "Long Run"}')
    proposal = Proposal(
        tool_name="propose_calendar_event", arguments={"summary": "Long Run"},
        summary="Termin \"Long Run\" anlegen",
    )

    with (
        patch.object(
            orchestrator_module, "stream_completion",
            new=stream_forever(_fake_response(None, [tool_call])),
        ) as mock_stream_completion,
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=proposal)),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id,
            user_message="Plan mir einen Lauf morgen früh.",
        )

    assert mock_stream_completion.call_count == 1
    assert result.proposal == replace(proposal, tool_call_id="call_1")
    assert result.reply_text is None


@pytest.mark.asyncio
async def test_hardcap_trips_on_a_runaway_tool_call_loop(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    tool_call = _fake_tool_call("call_x", "query_health", '{"metric_id": "hrv_baseline"}')

    with (
        patch.object(
            orchestrator_module, "stream_completion",
            new=stream_forever(_fake_response(None, [tool_call])),
        ) as mock_stream_completion,
        patch.object(
            orchestrator_module, "dispatch",
            new=AsyncMock(return_value={"summary": "ok", "data": {}, "meta": {}}),
        ),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="Frage",
        )

    assert mock_stream_completion.call_count == orchestrator_module._MAX_LOOP_ITERATIONS
    assert result.proposal is None
    assert "Zu viele Tool-Aufrufe" in (result.reply_text or "")


@pytest.mark.asyncio
async def test_remember_result_collected_in_remembered_list(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    tool_call = _fake_tool_call("call_1", "remember", '{"content": "mag keine Sprints"}')
    responses = [_fake_response(None, [tool_call]), _fake_response("Alles klar.")]
    remember_result = {
        "summary": "Gemerkt: mag keine Sprints",
        "data": {"id": "abc", "content": "mag keine Sprints", "source": "agent"},
        "meta": {},
    }

    with (
        patch.object(
            orchestrator_module, "stream_completion", new=stream_rounds(*responses)
        ),
        patch.object(
            orchestrator_module, "dispatch", new=AsyncMock(return_value=remember_result)
        ),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id,
            user_message="Ich mag keine Sprints.",
        )

    assert result.remembered == [
        {"id": "abc", "content": "mag keine Sprints", "expires_at": None}
    ]


@pytest.mark.asyncio
async def test_tool_handler_exception_becomes_an_error_tool_result(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    tool_call = _fake_tool_call("call_1", "query_health", '{"metric_id": "bogus"}')
    responses = [_fake_response(None, [tool_call]), _fake_response("Das kenne ich nicht.")]

    with (
        patch.object(
            orchestrator_module, "stream_completion", new=stream_rounds(*responses)
        ),
        patch.object(
            orchestrator_module, "dispatch",
            new=AsyncMock(side_effect=ValueError("Unknown metric_id: 'bogus'")),
        ),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="Frage",
        )

    assert result.reply_text == "Das kenne ich nicht."
    repo = ConversationRepository(session=session)
    messages = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    tool_message = next(m for m in messages if m.role == "tool")
    assert "Fehler" in (tool_message.content or "")


@pytest.mark.asyncio
async def test_invalid_tool_json_is_returned_to_the_model_not_raised(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    bad_call = _fake_tool_call("call_1", "query_health", '{"metric_id": ')
    completion = stream_rounds(_fake_response(None, [bad_call]), _fake_response("Korrigiert."))
    with (
        patch.object(orchestrator_module, "stream_completion", new=completion),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock()) as mock_dispatch,
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="x"
        )
    assert result.reply_text == "Korrigiert."
    mock_dispatch.assert_not_called()
    second_call_messages = completion.call_args_list[1].kwargs["messages"]
    tool_msg = next(m for m in second_call_messages if m["role"] == "tool")
    assert "Ungültige JSON-Argumente" in tool_msg["content"]


@pytest.mark.asyncio
async def test_proposal_carries_tool_call_id_and_siblings_get_skipped_results(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    calls = [
        _fake_tool_call("call_p", "propose_calendar_event",
                        '{"summary": "Lauf", "start_at": "2026-10-06T07:00:00+00:00",'
                        ' "end_at": "2026-10-06T08:00:00+00:00"}'),
        _fake_tool_call("call_q", "query_health", '{"metric_id": "hrv_baseline"}'),
    ]
    proposal = Proposal(tool_name="propose_calendar_event", arguments={}, summary="s",
                        tool_call_id="call_p")
    with (
        patch.object(orchestrator_module, "stream_completion",
                     new=stream_forever(_fake_response(None, calls))),
        patch.object(orchestrator_module, "dispatch", new=AsyncMock(return_value=proposal)),
    ):
        result = await run_turn(
            session, user_id=user_id, conversation_id=conversation_id, user_message="plan"
        )
    assert result.proposal is not None
    assert result.proposal.tool_call_id == "call_p"
    repo = ConversationRepository(session=session)
    tool_msgs = [m for m in await repo.list_messages(conversation_id=conversation_id,
                                                     user_id=user_id) if m.role == "tool"]
    assert [m.tool_call_id for m in tool_msgs] == ["call_q"]
    assert "wartet auf Bestätigung" in (tool_msgs[0].content or "")


@pytest.mark.asyncio
async def test_unanswered_proposal_is_closed_when_the_user_writes_again(
    session: AsyncSession,
) -> None:
    user_id, conversation_id = await _new_conversation(session)
    repo = ConversationRepository(session=session)
    await repo.append_message(conversation_id=conversation_id, user_id=user_id, role="user",
                              content="plan")
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event", "arguments": "{}"}],
    )
    await session.commit()
    completion = stream_forever(_fake_response("Ok."))
    with patch.object(orchestrator_module, "stream_completion", new=completion):
        await run_turn(session, user_id=user_id, conversation_id=conversation_id,
                       user_message="lieber nicht")
    stored = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    closing = [m for m in stored if m.role == "tool" and m.tool_call_id == "call_p"]
    assert len(closing) == 1
    sent = completion.call_args.kwargs["messages"]
    assert any(m["role"] == "tool" and m["tool_call_id"] == "call_p" for m in sent)


@pytest.mark.asyncio
async def test_failing_compaction_does_not_fail_the_turn(session: AsyncSession) -> None:
    user_id, conversation_id = await _new_conversation(session)
    with (
        patch.object(
            orchestrator_module, "stream_completion",
            new=stream_forever(_fake_response("Alles gut.")),
        ),
        patch.object(
            orchestrator_module, "compact_conversation",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
    ):
        result = await run_turn(session, user_id=user_id, conversation_id=conversation_id,
                                user_message="Hallo")
    assert result.reply_text == "Alles gut." and result.remembered == []
    repo = ConversationRepository(session=session)
    stored = await repo.list_messages(conversation_id=conversation_id, user_id=user_id)
    assert [m.role for m in stored] == ["user", "assistant"]
