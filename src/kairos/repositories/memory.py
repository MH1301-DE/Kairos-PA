from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import AgentMemory


class SqlMemoryRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, *, user_id: UUID) -> list[AgentMemory]:
        result = await self._session.execute(
            select(AgentMemory)
            .where(AgentMemory.user_id == user_id)
            .order_by(AgentMemory.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(self, *, user_id: UUID, content: str, source: str) -> AgentMemory:
        entry = AgentMemory(id=uuid.uuid4(), user_id=user_id, content=content, source=source)
        self._session.add(entry)
        await self._session.flush()
        return entry

    async def update(
        self, *, user_id: UUID, memory_id: UUID, content: str
    ) -> AgentMemory | None:
        await self._session.execute(
            update(AgentMemory)
            .where(AgentMemory.id == memory_id, AgentMemory.user_id == user_id)
            .values(content=content, updated_at=datetime.now().astimezone())
        )
        result = await self._session.execute(
            select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, *, user_id: UUID, memory_id: UUID) -> bool:
        result = await self._session.execute(
            delete(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.user_id == user_id)
        )
        rowcount: int = cast(CursorResult[Any], result).rowcount
        return rowcount > 0
