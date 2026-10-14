from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.bootstrap import build_default_registry
from kairos.repositories.metrics_data import sleep_hours_range
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily
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
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(day.year, day.month, day.day, 9, tzinfo=UTC), values=[150.0] * 600,
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


async def _insert_stream_workout(
    session: AsyncSession, user_id, day: date, *, minutes: int = 10, bpm: float = 150.0
) -> None:
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at, max_hr) "
                "VALUES (:uid, :ext, :start_at, 185) RETURNING id"
            ),
            {
                "uid": str(user_id),
                "ext": f"ext-{day.isoformat()}",
                "start_at": datetime(day.year, day.month, day.day, 9, tzinfo=UTC),
            },
        )
    ).scalar_one()
    await seed_hr_stream(
        session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(day.year, day.month, day.day, 9, tzinfo=UTC),
        values=[bpm] * (minutes * 60),
    )


async def _insert_sparse_training(session: AsyncSession, user_id, days: list[date]) -> None:
    """Bulk-insert several training days, then recompute the daily-bucket table once."""
    for day in days:
        await _insert_stream_workout(session, user_id, day)
    await session.commit()
    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=min(days), end=max(days)
    )
    await session.commit()


def _mon_wed_sat(start: date, end: date) -> list[date]:
    days = []
    day = start
    while day <= end:
        if day.weekday() in (0, 2, 5):  # Monday, Wednesday, Saturday
            days.append(day)
        day += timedelta(days=1)
    return days


def _sparse_schedule(*, rest_days_after: int) -> tuple[list[date], date]:
    """Mon/Wed/Sat training over ~10 weeks, then `rest_days_after` rest days up to as_of.

    schedule_end is a Monday so it lands exactly on a training day, making the gap to
    as_of deterministic instead of depending on which weekday as_of happens to be.
    """
    schedule_end = date(2026, 8, 3)
    training_days = _mon_wed_sat(schedule_end - timedelta(days=70), schedule_end)
    as_of = max(training_days) + timedelta(days=rest_days_after)
    return training_days, as_of


@pytest.mark.asyncio
async def test_training_load_variant_reflects_rest_day_decay(session: AsyncSession) -> None:
    """Sparse Mon/Wed/Sat schedule with training stopping 6 days before as_of.

    This is exactly the pattern the pre-fix sparse edwards_daily_load_series hid: with the
    old code, training_load() would iterate only up to the last training day and never see
    the rest days, so TSB would stay in the still-fatigued (often negative) state from the
    last workout instead of advancing to a rested one.
    """
    user_id = uuid4()
    await _insert_user(session, user_id)
    training_days, as_of = _sparse_schedule(rest_days_after=6)
    await _insert_sparse_training(session, user_id, training_days)

    registry = build_default_registry()
    result = await registry.get("training_load", "default").compute(
        session, user_id=user_id, as_of=as_of
    )

    assert result.confidence != "insufficient_data"
    assert isinstance(result.value, dict)
    assert result.value["tsb"] > 0, "TSB should reflect a rested state after 6 rest days"
    assert result.value["atl"] < result.value["ctl"], "ATL should have decayed below CTL"
    assert result.coverage_days >= 7


@pytest.mark.asyncio
async def test_training_load_variant_insufficient_data_for_zero_training_user(
    session: AsyncSession,
) -> None:
    """hr_max resolves (via activity.max_hr) but there is no hr stream data, ever.

    Guards the composition bug the dense-series fix could introduce: edwards_daily_load_series()
    always returns a dense, zero-filled series once hr_max resolves, so the old
    `if not result.series` check is dead code for this case — the variant must gate on
    days_with_data itself before calling training_load().
    """
    user_id = uuid4()
    await _insert_user(session, user_id)
    as_of = date(2026, 8, 10)
    await session.execute(
        text(
            "INSERT INTO activity (user_id, external_id, start_at, max_hr) "
            "VALUES (:uid, 'ext-no-records', :start_at, 185)"
        ),
        {"uid": str(user_id), "start_at": datetime(2026, 1, 1, 9, tzinfo=UTC)},
    )
    await session.commit()

    registry = build_default_registry()
    result = await registry.get("training_load", "default").compute(
        session, user_id=user_id, as_of=as_of
    )

    assert result.confidence == "insufficient_data"
    assert result.value is None


@pytest.mark.asyncio
async def test_acwr_variant_returns_ratio_for_sparse_schedule_with_enough_history(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    training_days, as_of = _sparse_schedule(rest_days_after=6)
    await _insert_sparse_training(session, user_id, training_days)

    registry = build_default_registry()
    result = await registry.get("acwr", "default").compute(session, user_id=user_id, as_of=as_of)

    assert result.confidence != "insufficient_data"
    assert isinstance(result.value, dict)
    assert result.value["ratio"] > 0


@pytest.mark.asyncio
async def test_acwr_variant_insufficient_data_for_sparse_new_user(session: AsyncSession) -> None:
    """Only 2 days of real history, ever: ACWR must still report insufficient_data.

    Guards the composition bug the dense-series fix could introduce: acwr()'s own
    coverage gate always sees every day "present" once the series is dense, so the
    variant must gate on the real-data-day count itself before calling acwr().
    """
    user_id = uuid4()
    await _insert_user(session, user_id)
    as_of = date(2026, 8, 10)
    sparse_days = [as_of - timedelta(days=12), as_of - timedelta(days=10)]
    await _insert_sparse_training(session, user_id, sparse_days)

    registry = build_default_registry()
    result = await registry.get("acwr", "default").compute(session, user_id=user_id, as_of=as_of)

    assert result.confidence == "insufficient_data"
    assert result.value is None


@pytest.mark.asyncio
async def test_monotony_strain_variant_computes_real_value_for_sparse_schedule(
    session: AsyncSession,
) -> None:
    """Pre-fix, the 7-day window's "all days present" check always failed for any
    schedule that included a rest day, so this returned None for realistic data."""
    user_id = uuid4()
    await _insert_user(session, user_id)
    training_days, as_of = _sparse_schedule(rest_days_after=6)
    await _insert_sparse_training(session, user_id, training_days)

    registry = build_default_registry()
    result = await registry.get("monotony_strain", "default").compute(
        session, user_id=user_id, as_of=as_of
    )

    assert result.confidence != "insufficient_data"
    assert isinstance(result.value, dict)
    assert result.value["monotony"] > 0
    assert result.value["strain"] >= 0


@pytest.mark.asyncio
async def test_sleep_debt_variant_buckets_by_utc_day_not_session_timezone(
    session: AsyncSession,
) -> None:
    """A sleep session at 02:00 UTC must bucket into that UTC day even when the DB
    session's TimeZone GUC is non-UTC (e.g. America/New_York, where 02:00 UTC is
    22:00 the previous local day). A bare `::date` cast would bucket it a day early."""
    user_id = uuid4()
    await _insert_user(session, user_id)
    day = date(2026, 8, 4)
    start_at = datetime(day.year, day.month, day.day, 2, 0, tzinfo=UTC)
    await session.execute(
        text(
            "INSERT INTO sleep_session (user_id, external_id, start_at, duration_seconds) "
            "VALUES (:uid, 'sleep-1', :start_at, :duration)"
        ),
        {"uid": str(user_id), "start_at": start_at, "duration": 8 * 3600},
    )
    await session.commit()

    await session.execute(text("SET TIME ZONE 'America/New_York'"))
    direct = await sleep_hours_range(session, user_id=user_id, start=day, end=day)
    assert direct == {day: pytest.approx(8.0)}

    registry = build_default_registry()
    result = await registry.get("sleep_debt", "default").compute(
        session, user_id=user_id, as_of=day
    )
    assert result.coverage_days == 1
    assert result.value is not None
