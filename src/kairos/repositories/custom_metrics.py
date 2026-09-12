from __future__ import annotations

import uuid
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import CustomMetricDefinition


class CustomMetricRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, *, user_id: UUID) -> list[CustomMetricDefinition]:
        result = await self._session.execute(
            select(CustomMetricDefinition)
            .where(CustomMetricDefinition.user_id == user_id)
            .order_by(CustomMetricDefinition.created_at.desc())
        )
        return list(result.scalars().all())

    async def create(
        self, *, user_id: UUID, code: str, display_name: str, expression: str, created_by: str
    ) -> CustomMetricDefinition:
        definition = CustomMetricDefinition(
            id=uuid.uuid4(),
            user_id=user_id,
            code=code,
            display_name=display_name,
            expression=expression,
            created_by=created_by,
        )
        self._session.add(definition)
        await self._session.flush()
        return definition

    async def delete(self, *, user_id: UUID, definition_id: UUID) -> bool:
        result = await self._session.execute(
            delete(CustomMetricDefinition).where(
                CustomMetricDefinition.id == definition_id,
                CustomMetricDefinition.user_id == user_id,
            )
        )
        rowcount: int = cast(CursorResult[Any], result).rowcount
        return rowcount > 0
