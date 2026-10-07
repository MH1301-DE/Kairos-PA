from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.rls import install_rls_listener
from kairos.repositories.memory import SqlMemoryRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_expired_memories_are_hidden_and_deleted(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = SqlMemoryRepository(session=session)
    now = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    await repo.create(user_id=user_id, content="dauerhaft", source="agent")
    await repo.create(
        user_id=user_id, content="bald weg", source="agent", expires_at=now + timedelta(days=1)
    )
    await repo.create(
        user_id=user_id,
        content="abgelaufen",
        source="agent",
        expires_at=now - timedelta(minutes=1),
    )
    active = await repo.list_active(user_id=user_id, now=now)
    assert {m.content for m in active} == {"dauerhaft", "bald weg"}
    assert await repo.delete_expired(user_id=user_id, now=now) == 1
    assert len(await repo.list_for_user(user_id=user_id)) == 2
