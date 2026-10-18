"""Training history as generator input (coach spec 6.1), loaded from stage-1 data."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.coach.model import RunRecord, TrainingHistory
from kairos.db.models import Activity, ActivityStats


async def load_history(
    session: AsyncSession, user_id: UUID, today: date, weeks: int = 12
) -> TrainingHistory:
    # expects install_rls_listener(session, user_id); days are local (stage 1 A.8)
    since = datetime.combine(today - timedelta(weeks=weeks), time())
    rows = await session.execute(
        select(
            Activity.start_local,
            ActivityStats.distance_m,
            ActivityStats.moving_s,
            ActivityStats.timer_s,
        )
        .join(ActivityStats, ActivityStats.activity_id == Activity.id)
        .where(
            Activity.user_id == user_id,
            Activity.sport_profile == "running",
            Activity.deleted_at.is_(None),
            Activity.start_local >= since,
        )
        .order_by(Activity.start_local)
    )
    return TrainingHistory(
        tuple(
            RunRecord(
                day=r.start_local.date(),
                distance_m=float(r.distance_m),
                duration_s=float(r.moving_s or r.timer_s or 0.0),
            )
            for r in rows
            if r.start_local is not None and r.distance_m
        )
    )
