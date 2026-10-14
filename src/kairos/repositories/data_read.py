from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_repository import load_stream
from kairos.db.models import Activity, MetricDef, SleepSession, WellnessSample


class InvalidCursorError(ValueError):
    """Raised when a client-supplied pagination cursor cannot be decoded."""


@dataclass(frozen=True)
class Page[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class ActivityDetail:
    activity: Activity
    series: dict[str, list[float | None]]
    t_offset_s: list[int]


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
                # to_date is an EXCLUSIVE upper bound (callers pass midnight of the day after
                # the last wanted day), otherwise everything after 00:00 of it is dropped
                WellnessSample.observed_at < to_date,
            )
            .order_by(WellnessSample.observed_at)
        )
        return list(result.scalars().all())

    async def list_activities(
        self, *, user_id: UUID, limit: int = 50, cursor: str | None = None
    ) -> Page[Activity]:
        stmt = select(Activity).where(Activity.user_id == user_id, Activity.deleted_at.is_(None))
        if cursor is not None:
            cursor_start_at, cursor_id = _decode_cursor(cursor)
            if cursor_start_at is None:
                # cursor row had start_at IS NULL: Postgres sorts NULLs first for DESC, so
                # "after" it means remaining NULL rows (smaller id) plus the entire non-NULL
                # group (which sorts after the NULL group in full). Non-NULL rows naturally
                # satisfy this without an extra IS NOT NULL check further below, but here we
                # have no start_at to compare against at all, so it must be explicit.
                stmt = stmt.where(
                    (Activity.start_at.is_(None) & (Activity.id < cursor_id))
                    | Activity.start_at.is_not(None)
                )
            else:
                stmt = stmt.where(
                    (Activity.start_at < cursor_start_at)
                    | ((Activity.start_at == cursor_start_at) & (Activity.id < cursor_id))
                )
        stmt = stmt.order_by(Activity.start_at.desc(), Activity.id.desc()).limit(limit + 1)
        result = await self._session.execute(stmt)
        rows = list(result.scalars().all())
        has_more = len(rows) > limit
        items = rows[:limit]
        next_cursor = _encode_cursor(items[-1].start_at, items[-1].id) if has_more else None
        return Page(items=items, next_cursor=next_cursor)

    async def get_activity_detail(
        self, *, user_id: UUID, external_id: str, max_points: int = 2000
    ) -> ActivityDetail | None:
        activity_row = await self._session.execute(
            select(Activity).where(
                Activity.user_id == user_id,
                Activity.external_id == external_id,
                Activity.deleted_at.is_(None),
            )
        )
        activity = activity_row.scalar_one_or_none()
        if activity is None:
            return None
        loaded = await load_stream(self._session, activity_id=activity.id)
        if loaded is None:
            return ActivityDetail(activity=activity, series={}, t_offset_s=[])
        t_offset_s, series = _downsample_mean(loaded.t_offset_s, loaded.channels, max_points)
        return ActivityDetail(activity=activity, series=series, t_offset_s=t_offset_s)

    async def list_sleep_sessions(
        self, *, user_id: UUID, from_date: datetime, to_date: datetime
    ) -> list[SleepSession]:
        result = await self._session.execute(
            select(SleepSession)
            .where(
                SleepSession.user_id == user_id,
                SleepSession.start_at >= from_date,
                # exclusive upper bound, see list_wellness_series
                SleepSession.start_at < to_date,
            )
            .order_by(SleepSession.start_at)
        )
        return list(result.scalars().all())


def _downsample_mean(
    t_offset_s: list[int], channels: dict[str, list[float | None]], max_points: int
) -> tuple[list[int], dict[str, list[float | None]]]:
    n = len(t_offset_s)
    if n <= max_points:
        return t_offset_s, channels
    # max_points consecutive buckets of near-equal size
    bounds = [i * n // max_points for i in range(max_points + 1)]
    spans = list(zip(bounds[:-1], bounds[1:], strict=True))
    offsets = [t_offset_s[lo] for lo, _ in spans]
    out: dict[str, list[float | None]] = {}
    for code, values in channels.items():
        means: list[float | None] = []
        for lo, hi in spans:
            present = [v for v in values[lo:hi] if v is not None]
            means.append(sum(present) / len(present) if present else None)
        out[code] = means
    return offsets, out


def _encode_cursor(dt: datetime | None, activity_id: int) -> str:
    dt_part = dt.isoformat() if dt is not None else "null"
    return base64.urlsafe_b64encode(f"{dt_part}|{activity_id}".encode()).decode()


def _decode_cursor(cursor: str) -> tuple[datetime | None, int]:
    # cursors come straight from the query string — every decode step can fail on junk
    try:
        raw = base64.urlsafe_b64decode(cursor.encode()).decode()
        dt_part, id_part = raw.rsplit("|", 1)
        dt = None if dt_part == "null" else datetime.fromisoformat(dt_part)
        return dt, int(id_part)
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise InvalidCursorError("malformed pagination cursor") from exc
