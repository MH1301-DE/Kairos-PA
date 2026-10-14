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
from tests.stream_seed import seed_hr_stream


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
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC), values=[142.0] * 3,
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
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC), values=[142.0],
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


@pytest.mark.asyncio
async def test_stream_buckets_match_legacy_activity_record_result(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    start_at = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :s) RETURNING id"
            ),
            {"uid": str(user_id), "s": start_at},
        )
    ).scalar_one()
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id, start_at=start_at,
        values=[142.0, 143.0, 144.9, 145.0, 150.0, 139.9],
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT bpm_bucket, seconds FROM hr_bucket_seconds_daily "
                "WHERE user_id = :uid ORDER BY bpm_bucket"
            ),
            {"uid": str(user_id)},
        )
    ).all()
    # fixed output of the former activity_record query for the same values
    assert rows == [(135, 1), (140, 3), (145, 1), (150, 1)]


@pytest.mark.asyncio
async def test_hr_samples_across_utc_midnight_land_on_two_days(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    start_at = datetime(2026, 8, 1, 23, 59, 58, tzinfo=UTC)
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :s) RETURNING id"
            ),
            {"uid": str(user_id), "s": start_at},
        )
    ).scalar_one()
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id, start_at=start_at,
        values=[142.0, 143.0, None, 150.0], t_offset_s=[0, 1, 2, 3],
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 2)
    )
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT day, bpm_bucket, seconds FROM hr_bucket_seconds_daily "
                "WHERE user_id = :uid ORDER BY day, bpm_bucket"
            ),
            {"uid": str(user_id)},
        )
    ).all()
    assert rows == [(date(2026, 8, 1), 140, 2), (date(2026, 8, 2), 150, 1)]
