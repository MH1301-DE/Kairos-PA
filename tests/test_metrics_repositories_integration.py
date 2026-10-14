# tests/test_metrics_repositories_integration.py
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_data import hr_bucket_seconds
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily
from kairos.repositories.user_setting import get_or_default_user_setting
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
async def test_get_or_default_user_setting_returns_defaults_when_absent(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    setting = await get_or_default_user_setting(session, user_id=user_id)

    assert setting.sleep_target_hours == 8.0
    assert setting.birth_date is None
    assert setting.hr_max_override is None


@pytest.mark.asyncio
async def test_hr_bucket_seconds_aggregates_stream_by_day(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    activity_id = (
        await session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, start_at)
                VALUES (:uid, 'ext-1', :start_at)
                RETURNING id
                """
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

    buckets = await hr_bucket_seconds(session, user_id=user_id, day=date(2026, 8, 1))

    assert buckets == {140: 3.0}
