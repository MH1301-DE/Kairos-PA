from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from kairos.db.rls import install_rls_listener
from kairos.repositories.conversation import ConversationRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_create_append_and_list_messages_in_order(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = ConversationRepository(session=session)

    conversation = await repo.create(user_id=user_id, title="Wie erholt bin ich heute?")
    await session.commit()

    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="user",
        content="Wie erholt bin ich heute?",
    )
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"name": "query_health", "arguments": {"metric_id": "hrv_baseline"}}],
    )
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="tool",
        content='{"summary": "HRV 62ms"}',
    )
    await session.commit()

    messages = await repo.list_messages(conversation_id=conversation.id, user_id=user_id)
    assert [m.role for m in messages] == ["user", "assistant", "tool"]
    assert messages[1].tool_calls == [
        {"name": "query_health", "arguments": {"metric_id": "hrv_baseline"}}
    ]


@pytest.mark.asyncio
async def test_append_message_bumps_conversation_updated_at(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = ConversationRepository(session=session)

    conversation = await repo.create(user_id=user_id, title="Test")
    await session.commit()
    first_updated_at = conversation.updated_at

    await session.execute(text("SELECT pg_sleep(0.01)"))
    await repo.append_message(
        conversation_id=conversation.id, user_id=user_id, role="user", content="hi"
    )
    await session.commit()

    refreshed = await repo.get(user_id=user_id, conversation_id=conversation.id)
    assert refreshed is not None
    assert refreshed.updated_at > first_updated_at


@pytest.mark.asyncio
async def test_list_for_user_orders_most_recently_updated_first(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = ConversationRepository(session=session)

    older = await repo.create(user_id=user_id, title="Older")
    await session.commit()
    await session.execute(text("SELECT pg_sleep(0.01)"))
    newer = await repo.create(user_id=user_id, title="Newer")
    await session.commit()

    conversations = await repo.list_for_user(user_id=user_id)
    assert [c.id for c in conversations] == [newer.id, older.id]


@pytest.mark.asyncio
async def test_conversation_enforce_rls_isolation(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    await _insert_user(session, user_a)
    await _insert_user(session, user_b)
    await session.commit()

    install_rls_listener(app_session, user_a)
    repo_a = ConversationRepository(session=app_session)
    await repo_a.create(user_id=user_a, title="A's conversation")
    await app_session.commit()

    install_rls_listener(app_session, user_b)
    repo_b = ConversationRepository(session=app_session)
    conversations_for_b = await repo_b.list_for_user(user_id=user_b)
    assert conversations_for_b == []


@pytest.mark.asyncio
async def test_find_tool_call_and_has_tool_result(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = ConversationRepository(session=session)
    conversation = await repo.create(user_id=user_id, title="t")
    conversation_id = conversation.id
    await repo.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event", "arguments": "{\"a\": 1}"}],
    )
    found = await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )
    assert found == {"id": "call_p", "name": "propose_calendar_event", "arguments": "{\"a\": 1}"}
    assert await repo.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="nope"
    ) is None
    assert not await repo.has_tool_result(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )
    await repo.append_message(conversation_id=conversation_id, user_id=user_id, role="tool",
                              content="{}", tool_call_id="call_p")
    assert await repo.has_tool_result(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
    )


@pytest.mark.asyncio
async def test_find_tool_call_for_update_serializes_concurrent_resolvers(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo_a = ConversationRepository(session=session)
    conversation = await repo_a.create(user_id=user_id, title="t")
    conversation_id = conversation.id
    await repo_a.append_message(
        conversation_id=conversation_id, user_id=user_id, role="assistant", content=None,
        tool_calls=[{"id": "call_p", "name": "propose_calendar_event", "arguments": "{}"}],
    )
    await session.commit()
    assert session.bind is not None
    factory = async_sessionmaker(session.bind, expire_on_commit=False)

    await repo_a.find_tool_call(
        conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p", for_update=True
    )

    async def second_resolver() -> bool:
        async with factory() as other:
            repo_b = ConversationRepository(session=other)
            await repo_b.find_tool_call(
                conversation_id=conversation_id, user_id=user_id,
                tool_call_id="call_p", for_update=True,
            )
            return await repo_b.has_tool_result(
                conversation_id=conversation_id, user_id=user_id, tool_call_id="call_p"
            )

    task = asyncio.create_task(second_resolver())
    await asyncio.sleep(0.5)
    assert not task.done()  # blocked on A's row lock
    await repo_a.append_message(conversation_id=conversation_id, user_id=user_id, role="tool",
                                content="{}", tool_call_id="call_p")
    await session.commit()
    assert await asyncio.wait_for(task, timeout=10) is True
