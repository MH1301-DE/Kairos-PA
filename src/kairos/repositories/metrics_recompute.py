from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.bootstrap import build_default_registry


async def recompute_hr_bucket_seconds_daily(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    # needs install_rls_listener(session, user_id) first, else the RLS SELECT returns 0 rows
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
            SELECT user_id, day, (floor(v / 5) * 5)::smallint AS bpm_bucket, count(*) AS seconds
            FROM (
                SELECT s.user_id,
                       ((ax.start_at + ax.t_offset_s[h.ord] * interval '1 second')
                           AT TIME ZONE 'UTC')::date AS day,
                       h.v
                FROM activity_stream s
                JOIN activity_stream_axis ax ON ax.activity_id = s.activity_id
                JOIN activity a ON a.id = s.activity_id AND a.deleted_at IS NULL
                CROSS JOIN LATERAL unnest(s.v4) WITH ORDINALITY AS h(v, ord)
                WHERE s.channel = 'hr' AND s.user_id = :uid AND h.v IS NOT NULL
            ) samples
            WHERE day >= :start AND day <= :end
            GROUP BY user_id, day, (floor(v / 5) * 5)::smallint
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )


async def recompute_wellness_daily_stats(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    # needs install_rls_listener(session, user_id) first, else the RLS SELECT returns 0 rows
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


async def recompute_metric_daily_values(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    # needs install_rls_listener(session, user_id) first, else the underlying .compute()
    # queries return 0 rows and every day ends up insufficient_data
    await session.execute(
        text(
            "DELETE FROM metric_daily_value "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    registry = build_default_registry()
    day = start
    while day <= end:
        for metric_id in registry.metric_ids():
            for variant_id in registry.variants_for(metric_id):
                result = await registry.get(metric_id, variant_id).compute(
                    session, user_id=user_id, as_of=day
                )
                # multi-stat metrics (e.g. training_load's CTL/ATL/TSB dict) are
                # skipped here -- only scalar formula outputs get a daily series in
                # this table, a dict value has no single column to store it in
                value = result.value if isinstance(result.value, int | float) else None
                await session.execute(
                    text(
                        "INSERT INTO metric_daily_value "
                        "(user_id, metric_id, variant_id, day, value, confidence) "
                        "VALUES (:uid, :mid, :vid, :day, :value, :confidence)"
                    ),
                    {
                        "uid": str(user_id),
                        "mid": metric_id,
                        "vid": variant_id,
                        "day": day,
                        "value": value,
                        "confidence": result.confidence,
                    },
                )
        day += timedelta(days=1)
