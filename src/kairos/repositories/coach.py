from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import AthleteReferenceValue, CoachProfile, PlanReview

REFERENCE_KINDS = ("vdot", "lthr_laufen", "lthr_rad", "ftp", "css", "critical_speed")


class CoachProfileRepository:
    """Expects a session with install_rls_listener for the user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, user_id: UUID) -> CoachProfile | None:
        return (
            await self._session.execute(select(CoachProfile).where(CoachProfile.user_id == user_id))
        ).scalar_one_or_none()

    async def upsert(self, user_id: UUID, **fields: Any) -> CoachProfile:
        profile = await self.get(user_id)
        now = datetime.now(UTC)
        if profile is None:
            profile = CoachProfile(user_id=user_id, onboarded_at=now, **fields)
            self._session.add(profile)
        else:
            for key, value in fields.items():
                setattr(profile, key, value)
        profile.updated_at = now
        await self._session.flush()
        return profile


class ReferenceValueRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        user_id: UUID,
        *,
        kind: str,
        value: float,
        measured_on: date,
        source: str,
        activity_id: int | None = None,
        note: str | None = None,
    ) -> AthleteReferenceValue:
        row = AthleteReferenceValue(
            user_id=user_id,
            kind=kind,
            value=value,
            measured_on=measured_on,
            source=source,
            activity_id=activity_id,
            note=note,
        )
        self._session.add(row)
        await self._session.flush()
        return row

    async def current(self, user_id: UUID) -> dict[str, AthleteReferenceValue]:
        # newest per kind; ties on the same day go to the later entry
        rows = await self._session.execute(
            select(AthleteReferenceValue)
            .where(AthleteReferenceValue.user_id == user_id)
            .order_by(
                AthleteReferenceValue.kind,
                AthleteReferenceValue.measured_on.desc(),
                AthleteReferenceValue.id.desc(),
            )
            .distinct(AthleteReferenceValue.kind)
        )
        return {row.kind: row for row in rows.scalars()}

    async def history(self, user_id: UUID, kind: str | None = None) -> list[AthleteReferenceValue]:
        stmt = select(AthleteReferenceValue).where(AthleteReferenceValue.user_id == user_id)
        if kind is not None:
            stmt = stmt.where(AthleteReferenceValue.kind == kind)
        rows = await self._session.execute(
            stmt.order_by(AthleteReferenceValue.measured_on.desc(), AthleteReferenceValue.id.desc())
        )
        return list(rows.scalars())


class PlanReviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, plan_id: UUID, week_start: date) -> PlanReview | None:
        return (
            await self._session.execute(
                select(PlanReview).where(
                    PlanReview.plan_id == plan_id, PlanReview.week_start == week_start
                )
            )
        ).scalar_one_or_none()

    async def latest_before(self, plan_id: UUID, week_start: date) -> PlanReview | None:
        return (
            await self._session.execute(
                select(PlanReview)
                .where(PlanReview.plan_id == plan_id, PlanReview.week_start < week_start)
                .order_by(PlanReview.week_start.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    async def create(
        self,
        *,
        plan_id: UUID,
        user_id: UUID,
        week_start: date,
        facts: dict[str, Any],
        conversation_id: UUID | None = None,
    ) -> PlanReview:
        review = PlanReview(
            id=uuid.uuid4(),
            plan_id=plan_id,
            user_id=user_id,
            week_start=week_start,
            facts=facts,
            conversation_id=conversation_id,
        )
        self._session.add(review)
        await self._session.flush()
        return review
