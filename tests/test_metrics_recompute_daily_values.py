from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.variants.edwards_trimp_variant import EdwardsTrimpVariant
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_metric_daily_values,
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
async def test_recompute_metric_daily_values_matches_direct_compute(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    # hr_max_override so EdwardsTrimpVariant.compute() doesn't hit insufficient_data
    await session.execute(
        text("INSERT INTO user_setting (user_id, hr_max_override) VALUES (:uid, 190)"),
        {"uid": str(user_id)},
    )
    day = date(2026, 8, 1)
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :start_at) RETURNING id"
            ),
            {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
        )
    ).scalar_one()
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(2026, 8, 1, 9, 0, tzinfo=UTC), values=[142.0] * 3,
    )
    await session.commit()

    # hr_bucket_seconds_daily is EdwardsTrimpVariant's own data source -- must run first
    await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=day, end=day)
    await session.commit()

    direct = await EdwardsTrimpVariant().compute(session, user_id=user_id, as_of=day)
    assert direct.confidence != "insufficient_data"  # sanity: this test needs a real value

    await recompute_metric_daily_values(session, user_id=user_id, start=day, end=day)
    await session.commit()

    row = (
        await session.execute(
            text(
                "SELECT value, confidence FROM metric_daily_value "
                "WHERE user_id = :uid AND metric_id = 'trimp' AND variant_id = 'edwards' "
                "AND day = :day"
            ),
            {"uid": str(user_id), "day": day},
        )
    ).one()

    assert row.value == pytest.approx(direct.value)
    assert row.confidence == direct.confidence


@pytest.mark.asyncio
async def test_recompute_metric_daily_values_is_idempotent(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    day = date(2026, 8, 1)

    await recompute_metric_daily_values(session, user_id=user_id, start=day, end=day)
    await recompute_metric_daily_values(session, user_id=user_id, start=day, end=day)
    await session.commit()

    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM metric_daily_value "
                "WHERE user_id = :uid AND metric_id = 'trimp' AND variant_id = 'edwards'"
            ),
            {"uid": str(user_id)},
        )
    ).scalar_one()

    assert count == 1


@pytest.mark.asyncio
async def test_recompute_metric_daily_values_skips_dict_valued_metrics(
    session: AsyncSession,
) -> None:
    """training_load's CTL/ATL/TSB dict has no single column to store -- must be
    persisted as NULL, not silently coerced or crash."""
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    day = date(2026, 8, 1)

    await recompute_metric_daily_values(session, user_id=user_id, start=day, end=day)
    await session.commit()

    row = (
        await session.execute(
            text(
                "SELECT value FROM metric_daily_value "
                "WHERE user_id = :uid AND metric_id = 'training_load' AND day = :day"
            ),
            {"uid": str(user_id), "day": day},
        )
    ).one()

    assert row.value is None
