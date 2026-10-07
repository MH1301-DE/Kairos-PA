from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.agent.events import AgentEvent
from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session
from kairos.repositories.conversation import ConversationRepository
from kairos.routers import agent as agent_router_module


async def _done_only(*_a: Any, **_k: Any) -> AsyncIterator[AgentEvent]:
    yield AgentEvent("done", {})


async def _wait_until(predicate: Any, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(0.02)
    return False


@pytest.mark.asyncio
async def test_concurrent_confirms_execute_the_proposal_exactly_once(
    session: AsyncSession, db_url: str
) -> None:
    user_id = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="t")
    await repo.append_message(conversation_id=conversation.id, user_id=user_id, role="user",
                              content="Termin bitte")
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event",
                     "arguments": '{"summary": "Lauf", "start_at": "2026-10-06T07:00:00+00:00",'
                                  ' "end_at": "2026-10-06T08:00:00+00:00"}'}],
    )
    await session.commit()

    first_call_entered = threading.Event()
    release_first_call = threading.Event()
    create_calls: list[int] = []

    def _fake_create_event(*_a: Any, **_k: Any) -> dict[str, Any]:
        create_calls.append(1)
        if len(create_calls) == 1:
            first_call_entered.set()
            release_first_call.wait(timeout=15)
        return {"id": f"google-evt-{len(create_calls)}"}

    google = MagicMock()
    google.create_event.side_effect = _fake_create_event

    original_append = ConversationRepository.append_message

    async def _append_after_racer(self: ConversationRepository, **kwargs: Any) -> Any:
        # give a racing confirm the window to execute again before the result row exists
        if kwargs.get("role") == "tool":
            await _wait_until(_second_create_seen, timeout=1.5)
        return await original_append(self, **kwargs)

    async def _second_create_seen() -> bool:
        return len(create_calls) >= 2

    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def _own_session() -> AsyncIterator[AsyncSession]:
        async with factory() as s:
            yield s

    async def _someone_waits_on_a_lock() -> bool:
        async with factory() as probe:
            waiting = (await probe.execute(text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE wait_event_type = 'Lock' AND datname = current_database()"
            ))).scalar_one()
        return int(waiting) >= 1

    app.dependency_overrides[current_user] = lambda: {"user_id": str(user_id)}
    app.dependency_overrides[get_session] = _own_session
    url = f"/api/agent/conversations/{conversation.id}/proposals/call_p/confirm"
    try:
        with (
            patch("kairos.routers.calendar._build_google_calendar_client",
                  new=AsyncMock(return_value=google)),
            patch.object(agent_router_module, "stream_continuation",
                         new=MagicMock(side_effect=_done_only)),
            patch.object(ConversationRepository, "append_message", new=_append_after_racer),
        ):
            async with AsyncClient(transport=ASGITransport(app=app),
                                   base_url="http://test") as client:
                first = asyncio.create_task(client.post(url))

                async def _first_entered() -> bool:
                    return first_call_entered.is_set()

                assert await _wait_until(_first_entered, timeout=10)
                second = asyncio.create_task(client.post(url))
                assert await _wait_until(_someone_waits_on_a_lock, timeout=10)
                release_first_call.set()
                responses = await asyncio.gather(first, second)
    finally:
        release_first_call.set()
        app.dependency_overrides.clear()
        await engine.dispose()

    statuses = sorted(r.status_code for r in responses)
    assert statuses == [200, 409]
    rejected = next(r for r in responses if r.status_code == 409)
    assert rejected.json()["detail"] == "proposal_already_resolved"
    assert google.create_event.call_count == 1
    tool_rows = (await session.execute(
        text("SELECT count(*) FROM conversation_message "
             "WHERE conversation_id = :cid AND role = 'tool' AND tool_call_id = 'call_p'"),
        {"cid": str(conversation.id)},
    )).scalar_one()
    assert tool_rows == 1
