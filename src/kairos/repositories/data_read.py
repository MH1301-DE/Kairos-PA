from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import Activity, ActivityRecord, MetricDef, SleepSession, WellnessSample


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class ActivityDetail:
    activity: Activity
    records: list[ActivityRecord]


class SqlDataReadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_wellness_series(
        self, *, user_id: UUID, metric: str, from_date: datetime, to_date: datetime
    ) -> list[WellnessSample]:
        metric_id_row = await self._session.execute(
            select(MetricDef.id).where(MetricDef.code == metric)
        )
        metric_id = metric_id_row.scalar_one_or_none()
        if metric_id is None:
            return []
        result = await self._session.execute(
            select(WellnessSample)
            .where(
                WellnessSample.user_id == user_id,
                WellnessSample.metric_id == metric_id,
                WellnessSample.observed_at >= from_date,
                WellnessSample.observed_at <= to_date,
            )
            .order_by(WellnessSample.observed_at)
        )
        return list(result.scalars().all())

    async def list_activities(
        self, *, user_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> Page[Activity]:
        stmt = select(Activity).where(Activity.user_id == user_id)
        if cursor is not None:
            cursor_start_at = _decode_cursor(cursor)
            stmt = stmt.where(Activity.start_at < cursor_start_at)
        stmt = stmt.order_by(Activity.start_at.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = (
            _encode_cursor(items[-1].start_at) if has_more and items[-1].start_at else None
        )
        return Page(items=items, next_cursor=next_cursor)

    async def get_activity_detail(
        self, *, user_id: UUID, external_id: str
    ) -> ActivityDetail | None:
        activity_row = await self._session.execute(
            select(Activity).where(
                Activity.user_id == user_id, Activity.external_id == external_id
            )
        )
        activity = activity_row.scalar_one_or_none()
        if activity is None:
            return None
        records_row = await self._session.execute(
            select(ActivityRecord)
            .where(ActivityRecord.user_id == user_id, ActivityRecord.activity_id == activity.id)
            .order_by(ActivityRecord.recorded_at)
        )
        return ActivityDetail(activity=activity, records=list(records_row.scalars().all()))

    async def list_sleep_sessions(
        self, *, user_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[SleepSession]:
        result = await self._session.execute(
            select(SleepSession)
            .where(
                SleepSession.user_id == user_id,
                SleepSession.start_at >= from_date,
                SleepSession.start_at <= to_date,
            )
            .order_by(SleepSession.start_at)
        )
        return list(result.scalars().all())


def _encode_cursor(dt: datetime) -> str:
    return base64.urlsafe_b64encode(dt.isoformat().encode()).decode()


def _decode_cursor(cursor: str) -> datetime:
    return datetime.fromisoformat(base64.urlsafe_b64decode(cursor.encode()).decode())
