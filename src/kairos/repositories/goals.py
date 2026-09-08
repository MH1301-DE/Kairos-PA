from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import Goal


class SqlGoalRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, *, user_id: UUID) -> list[Goal]:
        result = await self._session.execute(
            select(Goal)
            .where(Goal.user_id == user_id)
            .order_by(Goal.target_date.asc().nulls_last())
        )
        return list(result.scalars().all())

    async def create(
        self,
        *,
        user_id: UUID,
        title: str,
        target_value: float | None,
        target_unit: str | None,
        target_date: date | None,
        notes: str | None,
    ) -> Goal:
        goal = Goal(
            id=uuid.uuid4(),
            user_id=user_id,
            title=title,
            target_value=target_value,
            target_unit=target_unit,
            target_date=target_date,
            notes=notes,
        )
        self._session.add(goal)
        await self._session.flush()
        return goal

    async def update(
        self,
        *,
        user_id: UUID,
        goal_id: UUID,
        title: str | None = None,
        target_value: float | None = None,
        target_unit: str | None = None,
        target_date: date | None = None,
        notes: str | None = None,
        status: str | None = None,
    ) -> Goal | None:
        values: dict[str, object] = {"updated_at": datetime.now().astimezone()}
        if title is not None:
            values["title"] = title
        if target_value is not None:
            values["target_value"] = target_value
        if target_unit is not None:
            values["target_unit"] = target_unit
        if target_date is not None:
            values["target_date"] = target_date
        if notes is not None:
            values["notes"] = notes
        if status is not None:
            values["status"] = status

        await self._session.execute(
            update(Goal).where(Goal.id == goal_id, Goal.user_id == user_id).values(**values)
        )
        result = await self._session.execute(
            select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def delete(self, *, user_id: UUID, goal_id: UUID) -> bool:
        result = await self._session.execute(
            delete(Goal).where(Goal.id == goal_id, Goal.user_id == user_id)
        )
        rowcount: int = cast(CursorResult[Any], result).rowcount
        return rowcount > 0
