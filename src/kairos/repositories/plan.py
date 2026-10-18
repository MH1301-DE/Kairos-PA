from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date, datetime, time
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.coach.model import BlockDraft, PhaseDraft
from kairos.db.models import Plan, PlanBlock, PlanPhase
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
        if plan is not None and plan.status != "committed":
            # one active plan per user (coach spec S6): the previous one ends here
            previous = await self.get_active_for_user(user_id=user_id)
            if previous is not None:
                previous.status = "completed" if previous.end_date < date.today() else "abandoned"
                await self._session.flush()
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

    async def delete_drafts(self, *, user_id: UUID) -> None:
        await self._session.execute(
            delete(Plan).where(Plan.user_id == user_id, Plan.status == "draft")
        )

    async def latest_draft(self, *, user_id: UUID) -> Plan | None:
        result = await self._session.execute(
            select(Plan)
            .where(Plan.user_id == user_id, Plan.status == "draft")
            .order_by(Plan.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_phases(self, *, user_id: UUID, plan_id: UUID) -> list[PlanPhase]:
        result = await self._session.execute(
            select(PlanPhase)
            .where(PlanPhase.plan_id == plan_id, PlanPhase.user_id == user_id)
            .order_by(PlanPhase.seq)
        )
        return list(result.scalars().all())

    async def create_coach_draft(
        self,
        *,
        user_id: UUID,
        title: str,
        start_date: date,
        end_date: date,
        goal_date: date | None,
        goal_id: UUID | None,
        plan_type: str,
        plan_type_version: int,
        parameters: dict[str, Any],
        detail_until: date | None,
        phases: Sequence[PhaseDraft],
        blocks: Sequence[BlockDraft],
        timezone: str,
    ) -> Plan:
        # a new proposal replaces older drafts of the same user (coach spec 8.2)
        await self.delete_drafts(user_id=user_id)
        plan = Plan(
            id=uuid.uuid4(), user_id=user_id, title=title, start_date=start_date,
            end_date=end_date, goal_date=goal_date, goal_id=goal_id, status="draft",
            plan_type=plan_type, plan_type_version=plan_type_version, parameters=parameters,
            detail_until=detail_until,
        )
        self._session.add(plan)
        await self._session.flush()
        phase_rows = []
        for seq, phase in enumerate(phases):
            row = PlanPhase(
                id=uuid.uuid4(), plan_id=plan.id, user_id=user_id, seq=seq, kind=phase.kind,
                start_date=phase.start, end_date=phase.end, focus=phase.focus,
                volume_min_km=phase.volume_min_km, volume_max_km=phase.volume_max_km,
                rule_refs=list(phase.rule_refs),
            )
            self._session.add(row)
            phase_rows.append(row)
        await self._session.flush()
        zone = ZoneInfo(timezone)
        for block in blocks:
            phase_id = next(
                (r.id for r in phase_rows if r.start_date <= block.day <= r.end_date), None
            )
            # days without a preferred time start at 07:00 local, like the phase-5 plans
            hours, minutes = (int(x) for x in (block.start_time or "07:00").split(":"))
            start_at = datetime.combine(block.day, time(hours, minutes), zone)
            self._session.add(
                PlanBlock(
                    id=uuid.uuid4(), plan_id=plan.id, user_id=user_id, day=block.day,
                    workout_type=block.workout_type, phase_id=phase_id, sport=block.sport,
                    unit_id=block.unit_id, start_at=start_at,
                    planned_duration_s=round(block.duration_s),
                    planned_distance_m=round(block.distance_m) if block.distance_m else None,
                    steps=[s.to_json() for s in block.steps], rule_refs=list(block.rule_refs),
                    override_reason=block.override_reason,
                )
            )
        await self._session.flush()
        return plan
