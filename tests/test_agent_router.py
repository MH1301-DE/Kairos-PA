# tests/test_agent_router.py
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent import orchestrator as orchestrator_module
from kairos.agent.events import AgentEvent
from kairos.agent.llm_client import NoLlmCredentialConfigured
from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session
from kairos.repositories.conversation import ConversationRepository
from kairos.routers import agent as agent_router_module


async def _insert_user(session: AsyncSession, user_id: uuid.UUID, email: str, sub: str) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": email, "sub": sub},
    )


@pytest_asyncio.fixture
async def db_session(session: AsyncSession) -> AsyncSession:
    return session


@pytest_asyncio.fixture
async def test_user_id(db_session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    await db_session.commit()
    return user_id


@pytest_asyncio.fixture
async def authed_client(db_session: AsyncSession, test_user_id: uuid.UUID):
    app.dependency_overrides[current_user] = lambda: {"user_id": str(test_user_id)}

    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_conversations_require_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/agent/conversations")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_and_list_conversations(authed_client: AsyncClient) -> None:
    create_resp = await authed_client.post("/api/agent/conversations", json={"title": "Frage"})
    assert create_resp.status_code == 201
    conversation_id = create_resp.json()["id"]

    list_resp = await authed_client.get("/api/agent/conversations")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["conversations"]) == 1
    assert list_resp.json()["conversations"][0]["id"] == conversation_id


@pytest.mark.asyncio
async def test_messages_404_for_unknown_conversation(authed_client: AsyncClient) -> None:
    resp = await authed_client.get(f"/api/agent/conversations/{uuid.uuid4()}/messages")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_messages_expose_tool_name_for_tool_rows(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    repo = ConversationRepository(session=db_session)
    conversation = await repo.create(user_id=test_user_id, title="t")
    await repo.append_message(
        conversation_id=conversation.id, user_id=test_user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_r", "name": "render", "arguments": "{}"}],
    )
    await repo.append_message(conversation_id=conversation.id, user_id=test_user_id,
                              role="tool", content="{}", tool_call_id="call_r")
    await repo.append_message(conversation_id=conversation.id, user_id=test_user_id,
                              role="tool", content="{}", tool_call_id="call_unknown")
    await db_session.commit()
    resp = await authed_client.get(f"/api/agent/conversations/{conversation.id}/messages")
    msgs = resp.json()["messages"]
    assert [(m["role"], m["tool_call_id"], m["tool_name"]) for m in msgs] == [
        ("assistant", None, None), ("tool", "call_r", "render"), ("tool", "call_unknown", None),
    ]


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def _events(*events: AgentEvent) -> AsyncIterator[AgentEvent]:
    for ev in events:
        yield ev


@pytest.mark.asyncio
async def test_stream_returns_sse_body_and_sets_title(authed_client: AsyncClient) -> None:
    create_resp = await authed_client.post("/api/agent/conversations", json={})
    conversation_id = create_resp.json()["id"]
    events = [AgentEvent("token", {"text": "Hallo"}), AgentEvent("done", {})]

    with patch.object(
        agent_router_module, "stream_turn", new=MagicMock(return_value=_events(*events))
    ) as mock_stream_turn:
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/stream",
            json={"content": "Wie erholt bin ich?"},
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert resp.text == "".join(ev.to_sse() for ev in events)
    assert mock_stream_turn.call_args.kwargs["user_message"] == "Wie erholt bin ich?"

    list_resp = await authed_client.get("/api/agent/conversations")
    assert list_resp.json()["conversations"][0]["title"] == "Wie erholt bin ich?"


@pytest.mark.asyncio
async def test_stream_404_for_unknown_conversation(authed_client: AsyncClient) -> None:
    with patch.object(agent_router_module, "stream_turn", new=MagicMock()) as mock_stream_turn:
        resp = await authed_client.post(
            f"/api/agent/conversations/{uuid.uuid4()}/stream", json={"content": "Hi"}
        )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "conversation_not_found"
    mock_stream_turn.assert_not_called()


@pytest.mark.asyncio
async def test_non_streaming_send_endpoint_is_gone(authed_client: AsyncClient) -> None:
    create_resp = await authed_client.post("/api/agent/conversations", json={})
    conversation_id = create_resp.json()["id"]
    resp = await authed_client.post(
        f"/api/agent/conversations/{conversation_id}/messages", json={"content": "Hi"}
    )
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_stream_reports_missing_llm_credential_as_error_event(
    authed_client: AsyncClient,
) -> None:
    """Regression test: found via a live smoke test against a user with no
    connection row -- NoLlmCredentialConfigured must surface as a clean
    error event, not an unhandled 500."""
    create_resp = await authed_client.post("/api/agent/conversations", json={})
    conversation_id = create_resp.json()["id"]

    with patch.object(
        orchestrator_module, "stream_completion",
        new=MagicMock(side_effect=NoLlmCredentialConfigured("no key")),
    ):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/stream", json={"content": "Hi"}
        )
    assert resp.status_code == 200
    assert _parse_sse(resp.text) == [
        ("error", {"detail": "no_llm_provider_configured"}), ("done", {}),
    ]


@pytest.mark.asyncio
async def test_stream_reports_llm_provider_error_as_error_event(
    authed_client: AsyncClient,
) -> None:
    """Regression test: found via a live smoke test with a dummy API key --
    litellm.exceptions.AuthenticationError (and every other litellm error, all
    on the openai.OpenAIError hierarchy) must surface as a clean error event."""
    import openai

    create_resp = await authed_client.post("/api/agent/conversations", json={})
    conversation_id = create_resp.json()["id"]

    fake_response = MagicMock(status_code=401, headers={})
    with patch.object(
        orchestrator_module, "stream_completion",
        new=MagicMock(side_effect=openai.AuthenticationError(
            message="invalid key", response=fake_response, body=None
        )),
    ):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/stream", json={"content": "Hi"}
        )
    assert resp.status_code == 200
    assert _parse_sse(resp.text) == [("error", {"detail": "llm_provider_error"}), ("done", {})]


async def _conversation_with_pending_proposal(
    db_session: AsyncSession, user_id: uuid.UUID
) -> uuid.UUID:
    repo = ConversationRepository(session=db_session)
    conversation = await repo.create(user_id=user_id, title="t")
    await repo.append_message(conversation_id=conversation.id, user_id=user_id, role="user",
                              content="Termin bitte")
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event",
                     "arguments": '{"summary": "Lauf", "start_at": "2026-10-06T07:00:00+00:00",'
                                  ' "end_at": "2026-10-06T08:00:00+00:00"}'}],
    )
    await db_session.commit()
    return conversation.id


@pytest.mark.asyncio
async def test_confirm_executes_stored_arguments_and_answers_the_original_call(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    executed = AsyncMock(return_value={"summary": "Termin angelegt", "data": {}, "meta": {}})
    continuation = MagicMock(return_value=_events(AgentEvent("done", {})))
    with (
        patch.object(agent_router_module, "dispatch", new=executed),
        patch.object(agent_router_module, "stream_continuation", new=continuation),
    ):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm"
        )
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/event-stream")
    assert _parse_sse(resp.text) == [
        ("tool_end", {"id": "call_p", "name": "propose_calendar_event",
                      "summary": "Termin angelegt", "ok": True}),
        ("done", {}),
    ]
    continuation.assert_called_once()
    call = executed.call_args.kwargs["tool_call"]
    assert call.name == "propose_calendar_event"
    assert call.arguments["summary"] == "Lauf"
    assert executed.call_args.kwargs["pending_confirmation"] is True
    repo = ConversationRepository(session=db_session)
    assert await repo.has_tool_result(conversation_id=conversation_id, user_id=test_user_id,
                                      tool_call_id="call_p")


@pytest.mark.asyncio
async def test_second_confirm_is_rejected_without_executing_twice(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    executed = AsyncMock(return_value={"summary": "ok", "data": {}, "meta": {}})
    with (
        patch.object(agent_router_module, "dispatch", new=executed),
        patch.object(agent_router_module, "stream_continuation",
                     new=MagicMock(side_effect=lambda *_a, **_k: _events(AgentEvent("done", {})))),
    ):
        first = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
        second = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "proposal_already_resolved"
    assert executed.await_count == 1


@pytest.mark.asyncio
async def test_confirm_handler_db_error_becomes_error_result(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)

    async def _failing_dispatch(session: AsyncSession, **_kwargs: object) -> dict:
        await session.execute(text("SELECT 1 / 0"))
        return {"summary": "unreachable", "data": None, "meta": {}}

    with (
        patch.object(agent_router_module, "dispatch", new=_failing_dispatch),
        patch.object(agent_router_module, "stream_continuation",
                     new=MagicMock(return_value=_events(AgentEvent("done", {})))),
    ):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
    assert resp.status_code == 200
    tool_end = _parse_sse(resp.text)[0]
    assert tool_end[0] == "tool_end"
    assert tool_end[1]["ok"] is False
    assert tool_end[1]["summary"].startswith("Fehler")
    assert await ConversationRepository(session=db_session).has_tool_result(
        conversation_id=conversation_id, user_id=test_user_id, tool_call_id="call_p"
    )


@pytest.mark.asyncio
async def test_reject_records_rejection_and_unknown_proposal_is_404(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    conversation_id = await _conversation_with_pending_proposal(db_session, test_user_id)
    continuation = MagicMock(return_value=_events(AgentEvent("done", {})))
    with patch.object(agent_router_module, "stream_continuation", new=continuation):
        resp = await authed_client.post(
            f"/api/agent/conversations/{conversation_id}/proposals/call_p/reject")
    assert resp.status_code == 200
    first_type, first_data = _parse_sse(resp.text)[0]
    assert first_type == "tool_end"
    assert first_data["id"] == "call_p"
    assert "abgelehnt" in first_data["summary"]
    tool_rows = [
        m for m in await ConversationRepository(session=db_session).list_messages(
            conversation_id=conversation_id, user_id=test_user_id
        ) if m.role == "tool"
    ]
    assert [m.tool_call_id for m in tool_rows] == ["call_p"]
    assert "abgelehnt" in (tool_rows[0].content or "")
    again = await authed_client.post(
        f"/api/agent/conversations/{conversation_id}/proposals/call_p/confirm")
    assert again.status_code == 409
    assert again.json()["detail"] == "proposal_already_resolved"
    missing = await authed_client.post(
        f"/api/agent/conversations/{conversation_id}/proposals/nope/confirm")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "proposal_not_found"


@pytest.mark.asyncio
async def test_read_tool_call_cannot_be_confirmed(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    repo = ConversationRepository(session=db_session)
    conversation = await repo.create(user_id=test_user_id, title="t")
    await repo.append_message(
        conversation_id=conversation.id, user_id=test_user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_r", "name": "query_health", "arguments": "{}"}],
    )
    await db_session.commit()
    resp = await authed_client.post(
        f"/api/agent/conversations/{conversation.id}/proposals/call_r/confirm")
    assert resp.status_code == 409
    assert resp.json()["detail"] == "not_a_proposal"


@pytest.mark.asyncio
async def test_confirm_404_for_unknown_conversation(authed_client: AsyncClient) -> None:
    resp = await authed_client.post(
        f"/api/agent/conversations/{uuid.uuid4()}/proposals/call_p/confirm"
    )
    assert resp.status_code == 404
