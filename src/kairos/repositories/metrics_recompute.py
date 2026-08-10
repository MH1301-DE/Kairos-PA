from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def recompute_hr_bucket_seconds_daily(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    await session.execute(
        text(
            "DELETE FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    await session.execute(
        text(
            """
            INSERT INTO hr_bucket_seconds_daily (user_id, day, bpm_bucket, seconds)
            SELECT
                user_id,
                (recorded_at AT TIME ZONE 'UTC')::date AS day,
                (floor(value / 5) * 5)::smallint AS bpm_bucket,
                count(*) AS seconds
            FROM activity_record
            WHERE metric = 'hr' AND user_id = :uid
              AND (recorded_at AT TIME ZONE 'UTC')::date >= :start
              AND (recorded_at AT TIME ZONE 'UTC')::date <= :end
            GROUP BY user_id, (recorded_at AT TIME ZONE 'UTC')::date,
                     (floor(value / 5) * 5)::smallint
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )


async def recompute_wellness_daily_stats(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    await session.execute(
        text(
            "DELETE FROM wellness_daily_stats "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    await session.execute(
        text(
            """
            INSERT INTO wellness_daily_stats
                (user_id, metric_id, day, avg_value, min_value, max_value, sample_count)
            SELECT
                user_id,
                metric_id,
                (observed_at AT TIME ZONE 'UTC')::date AS day,
                avg(value), min(value), max(value), count(*)
            FROM wellness_sample
            WHERE user_id = :uid
              AND (observed_at AT TIME ZONE 'UTC')::date >= :start
              AND (observed_at AT TIME ZONE 'UTC')::date <= :end
            GROUP BY user_id, metric_id, (observed_at AT TIME ZONE 'UTC')::date
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
