from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class WellnessDayStat:
    avg: float
    min: float
    max: float
    sample_count: int


async def hr_bucket_seconds(
    session: AsyncSession, *, user_id: UUID, day: date
) -> dict[int, float]:
    result = await session.execute(
        text(
            "SELECT bpm_bucket, seconds FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day = :day"
        ),
        {"uid": str(user_id), "day": day},
    )
    return {int(bucket): float(seconds) for bucket, seconds in result.all()}


async def hr_bucket_seconds_range(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> dict[date, dict[int, float]]:
    result = await session.execute(
        text(
            "SELECT day, bpm_bucket, seconds FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    out: dict[date, dict[int, float]] = {}
    for day, bucket, seconds in result.all():
        out.setdefault(day, {})[int(bucket)] = float(seconds)
    return out


async def wellness_daily_stat(
    session: AsyncSession, *, user_id: UUID, metric_code: str, day: date
) -> WellnessDayStat | None:
    result = await session.execute(
        text(
            """
            SELECT w.avg_value, w.min_value, w.max_value, w.sample_count
            FROM wellness_daily_stats w
            JOIN metric_def m ON m.id = w.metric_id
            WHERE w.user_id = :uid AND m.code = :code AND w.day = :day
            """
        ),
        {"uid": str(user_id), "code": metric_code, "day": day},
    )
    row = result.first()
    if row is None:
        return None
    return WellnessDayStat(avg=row[0], min=row[1], max=row[2], sample_count=row[3])


async def wellness_daily_stat_range(
    session: AsyncSession, *, user_id: UUID, metric_code: str, start: date, end: date
) -> dict[date, WellnessDayStat]:
    result = await session.execute(
        text(
            """
            SELECT w.day, w.avg_value, w.min_value, w.max_value, w.sample_count
            FROM wellness_daily_stats w
            JOIN metric_def m ON m.id = w.metric_id
            WHERE w.user_id = :uid AND m.code = :code AND w.day >= :start AND w.day <= :end
            """
        ),
        {"uid": str(user_id), "code": metric_code, "start": start, "end": end},
    )
    return {
        day: WellnessDayStat(avg=avg, min=mn, max=mx, sample_count=cnt)
        for day, avg, mn, mx, cnt in result.all()
    }


async def sleep_hours_range(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> dict[date, float]:
    result = await session.execute(
        text(
            "SELECT (s.start_at AT TIME ZONE u.home_timezone)::date AS day, s.duration_seconds "
            "FROM sleep_session s JOIN app_user u ON u.id = s.user_id WHERE s.user_id = :uid "
            "AND (s.start_at AT TIME ZONE u.home_timezone)::date >= :start "
            "AND (s.start_at AT TIME ZONE u.home_timezone)::date <= :end "
            "AND s.duration_seconds IS NOT NULL"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    return {day: seconds / 3600.0 for day, seconds in result.all()}
