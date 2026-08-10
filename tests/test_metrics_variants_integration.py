from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.bootstrap import build_default_registry
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily


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


async def _insert_workout(session: AsyncSession, user_id, day: date) -> None:
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at, max_hr) "
                "VALUES (:uid, 'ext-1', :start_at, 185) RETURNING id"
            ),
            {
                "uid": str(user_id),
                "start_at": datetime(day.year, day.month, day.day, 9, tzinfo=UTC),
            },
        )
    ).scalar_one()
    for i in range(600):  # 10 minutes at 150 bpm
        ts = datetime(day.year, day.month, day.day, 9, 0, i % 60, tzinfo=UTC) + timedelta(
            minutes=i // 60
        )
        await session.execute(
            text(
                "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
                "VALUES (:uid, :aid, :ts, 'hr', 150.0)"
            ),
            {"uid": str(user_id), "aid": activity_id, "ts": ts},
        )
    await session.commit()
    await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=day, end=day)
    await session.commit()


@pytest.mark.asyncio
async def test_edwards_trimp_variant_computes_from_real_data(session: AsyncSession) -> None:
    user_id = uuid4()
    today = date(2026, 8, 1)
    await _insert_user(session, user_id)
    await _insert_workout(session, user_id, today)

    registry = build_default_registry()
    result = await registry.get("trimp", "edwards").compute(session, user_id=user_id, as_of=today)

    assert result.confidence in ("high", "medium", "low")
    assert isinstance(result.value, float)
    assert result.value > 0
