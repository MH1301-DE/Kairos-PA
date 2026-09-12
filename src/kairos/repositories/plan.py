from __future__ import annotations

import uuid
from datetime import date
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import Plan, PlanBlock
from kairos.planning.algorithm import PlannedBlock


class PlanRepository:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def create_draft(
        self,
        *,
        user_id: UUID,
        title: str,
        start_date: date,
        end_date: date,
        goal_date: date | None,
        blocks: list[PlannedBlock],
    ) -> Plan:
        plan = Plan(
            id=uuid.uuid4(), user_id=user_id, title=title, start_date=start_date,
            end_date=end_date, goal_date=goal_date, status="draft",
        )
        self._session.add(plan)
        await self._session.flush()
        for b in blocks:
            self._session.add(
                PlanBlock(
                    id=uuid.uuid4(), plan_id=plan.id, user_id=user_id, day=b.day,
                    workout_type=b.workout_type, target_trimp=b.target_trimp,
                )
            )
        await self._session.flush()
        return plan

    async def get(self, *, user_id: UUID, plan_id: UUID) -> Plan | None:
        result = await self._session.execute(
            select(Plan).where(Plan.id == plan_id, Plan.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_active_for_user(self, *, user_id: UUID) -> Plan | None:
        result = await self._session.execute(
            select(Plan)
            .where(Plan.user_id == user_id, Plan.status == "committed")
            .order_by(Plan.updated_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_blocks(self, *, user_id: UUID, plan_id: UUID) -> list[PlanBlock]:
        result = await self._session.execute(
            select(PlanBlock)
            .where(PlanBlock.plan_id == plan_id, PlanBlock.user_id == user_id)
            .order_by(PlanBlock.day)
        )
        return list(result.scalars().all())

    async def commit(
        self, *, user_id: UUID, plan_id: UUID, event_ids_by_block_id: dict[UUID, str]
    ) -> None:
        plan = await self.get(user_id=user_id, plan_id=plan_id)
        if plan is not None:
            plan.status = "committed"
        blocks = await self.list_blocks(user_id=user_id, plan_id=plan_id)
        for block in blocks:
            event_id = event_ids_by_block_id.get(block.id)
            if event_id is not None:
                block.calendar_event_id = UUID(event_id)
        await self._session.flush()

    async def replace_remaining_blocks(
        self, *, user_id: UUID, plan_id: UUID, from_day: date, blocks: list[PlannedBlock]
    ) -> None:
        # only future, still-'planned' blocks are ever replaced -- done/skipped
        # history and anything before from_day is untouched
        await self._session.execute(
            delete(PlanBlock).where(
                PlanBlock.plan_id == plan_id,
                PlanBlock.user_id == user_id,
                PlanBlock.day >= from_day,
                PlanBlock.status == "planned",
            )
        )
        for b in blocks:
            self._session.add(
                PlanBlock(
                    id=uuid.uuid4(), plan_id=plan_id, user_id=user_id, day=b.day,
                    workout_type=b.workout_type, target_trimp=b.target_trimp,
                )
            )
        await self._session.flush()
