from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_data import sleep_hours_range
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_wellness_daily_stats,
)
from tests.stream_seed import seed_hr_stream

_BERLIN_SUMMER = "Europe/Berlin"


async def _user(session: AsyncSession, tz: str) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'T', :sub, :tz, 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@t.com", "sub": f"s-{user_id}", "tz": tz},
    )
    return user_id


async def _activity(
    session: AsyncSession, user_id: UUID, start_at: datetime, start_local: datetime | None
) -> int:
    return (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at, start_local) "
                "VALUES (:uid, :ext, :s, :l) RETURNING id"
            ),
            {"uid": str(user_id), "ext": str(uuid4()), "s": start_at, "l": start_local},
        )
    ).scalar_one()


async def _hr_days(session: AsyncSession, user_id: UUID) -> list[tuple[date, int]]:
    rows = await session.execute(
        text(
            "SELECT day, sum(seconds)::int FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid GROUP BY day ORDER BY day"
        ),
        {"uid": str(user_id)},
    )
    return [(d, n) for d, n in rows.all()]


@pytest.mark.asyncio
async def test_hr_after_local_midnight_lands_on_local_day(session: AsyncSession) -> None:
    user_id = await _user(session, _BERLIN_SUMMER)
    start = datetime(2026, 7, 14, 22, 30, tzinfo=UTC)
    act = await _activity(session, user_id, start, datetime(2026, 7, 15, 0, 30))
    await seed_hr_stream(
        session, user_id=user_id, activity_id=act, start_at=start, values=[140.0] * 4
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 7, 14), end=date(2026, 7, 16)
    )

    assert await _hr_days(session, user_id) == [(date(2026, 7, 15), 4)]


@pytest.mark.asyncio
async def test_hr_activity_across_local_midnight_counts_to_start_day(
    session: AsyncSession,
) -> None:
    user_id = await _user(session, _BERLIN_SUMMER)
    start = datetime(2026, 7, 15, 21, 30, tzinfo=UTC)  # 23:30 local
    act = await _activity(session, user_id, start, datetime(2026, 7, 15, 23, 30))
    await seed_hr_stream(
        session, user_id=user_id, activity_id=act, start_at=start,
        values=[150.0] * 4, t_offset_s=[0, 600, 3600, 7200],
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 7, 15), end=date(2026, 7, 16)
    )

    assert await _hr_days(session, user_id) == [(date(2026, 7, 15), 4)]


@pytest.mark.asyncio
async def test_hr_falls_back_to_home_timezone_without_start_local(
    session: AsyncSession,
) -> None:
    user_id = await _user(session, _BERLIN_SUMMER)
    start = datetime(2026, 7, 14, 22, 30, tzinfo=UTC)
    act = await _activity(session, user_id, start, None)
    await seed_hr_stream(
        session, user_id=user_id, activity_id=act, start_at=start, values=[140.0] * 2
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 7, 14), end=date(2026, 7, 16)
    )

    assert await _hr_days(session, user_id) == [(date(2026, 7, 15), 2)]


@pytest.mark.asyncio
async def test_hr_utc_user_unchanged(session: AsyncSession) -> None:
    user_id = await _user(session, "UTC")
    start = datetime(2026, 7, 14, 22, 30, tzinfo=UTC)
    act = await _activity(session, user_id, start, datetime(2026, 7, 14, 22, 30))
    await seed_hr_stream(
        session, user_id=user_id, activity_id=act, start_at=start, values=[140.0] * 2
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 7, 14), end=date(2026, 7, 16)
    )

    assert await _hr_days(session, user_id) == [(date(2026, 7, 14), 2)]


async def _wellness_days(session: AsyncSession, tz: str) -> list[date]:
    user_id = await _user(session, tz)
    await session.execute(
        text(
            "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
            "VALUES (:uid, (SELECT id FROM metric_def WHERE code = 'hr'), :t, 60)"
        ),
        {"uid": str(user_id), "t": datetime(2026, 7, 14, 23, 30, tzinfo=UTC)},
    )
    await session.commit()
    await recompute_wellness_daily_stats(
        session, user_id=user_id, start=date(2026, 7, 14), end=date(2026, 7, 16)
    )
    rows = await session.execute(
        text("SELECT day FROM wellness_daily_stats WHERE user_id = :uid"), {"uid": str(user_id)}
    )
    return [r[0] for r in rows.all()]


@pytest.mark.asyncio
async def test_wellness_sample_2330_utc_summer_is_next_local_day(session: AsyncSession) -> None:
    assert await _wellness_days(session, _BERLIN_SUMMER) == [date(2026, 7, 15)]


@pytest.mark.asyncio
async def test_wellness_utc_user_unchanged(session: AsyncSession) -> None:
    assert await _wellness_days(session, "UTC") == [date(2026, 7, 14)]


@pytest.mark.asyncio
async def test_sleep_hours_range_uses_local_start_day(session: AsyncSession) -> None:
    user_id = await _user(session, _BERLIN_SUMMER)
    await session.execute(
        text(
            "INSERT INTO sleep_session (user_id, external_id, start_at, duration_seconds) "
            "VALUES (:uid, 'sl1', :t, 28800)"
        ),
        {"uid": str(user_id), "t": datetime(2026, 7, 14, 22, 30, tzinfo=UTC)},
    )
    await session.commit()

    result = await sleep_hours_range(
        session, user_id=user_id, start=date(2026, 7, 14), end=date(2026, 7, 16)
    )

    assert result == {date(2026, 7, 15): 8.0}


def test_no_utc_day_cut_left_in_src() -> None:
    offenders = [
        str(p)
        for p in Path("src").rglob("*.py")
        if "AT TIME ZONE 'UTC'" in p.read_text(encoding="utf-8")
    ]
    assert offenders == []
