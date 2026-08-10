from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_wellness_daily_stats,
)


async def _insert_user(session: AsyncSession, user_id) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_recompute_hr_bucket_seconds_daily_groups_by_5bpm_bucket(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :start_at) "
                "RETURNING id"
            ),
            {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
        )
    ).scalar_one()
    for i in range(3):
        await session.execute(
            text(
                "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
                "VALUES (:uid, :aid, :ts, 'hr', 142.0)"
            ),
            {
                "uid": str(user_id), "aid": activity_id,
                "ts": datetime(2026, 8, 1, 9, 0, i, tzinfo=UTC),
            },
        )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT bpm_bucket, seconds FROM hr_bucket_seconds_daily WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).all()

    assert rows == [(140, 3)]


@pytest.mark.asyncio
async def test_recompute_is_idempotent_for_the_same_range(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :start_at) "
                "RETURNING id"
            ),
            {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
            "VALUES (:uid, :aid, :ts, 'hr', 142.0)"
        ),
        {
            "uid": str(user_id), "aid": activity_id,
            "ts": datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC),
        },
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    count = (
        await session.execute(
            text("SELECT count(*) FROM hr_bucket_seconds_daily WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar_one()

    assert count == 1


@pytest.mark.asyncio
async def test_recompute_wellness_daily_stats_aggregates_per_metric_per_day(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    metric_id = (
        await session.execute(text("SELECT id FROM metric_def WHERE code = 'hr'"))
    ).scalar_one()
    for i, value in enumerate((50.0, 60.0, 70.0)):
        await session.execute(
            text(
                "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
                "VALUES (:uid, :mid, :ts, :val)"
            ),
            {
                "uid": str(user_id), "mid": metric_id,
                "ts": datetime(2026, 8, 1, 9, 0, i, tzinfo=UTC), "val": value,
            },
        )
    await session.commit()

    await recompute_wellness_daily_stats(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    row = (
        await session.execute(
            text(
                "SELECT avg_value, min_value, max_value, sample_count "
                "FROM wellness_daily_stats WHERE user_id = :uid AND metric_id = :mid"
            ),
            {"uid": str(user_id), "mid": metric_id},
        )
    ).one()

    assert row == (60.0, 50.0, 70.0, 3)
