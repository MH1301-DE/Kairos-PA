from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.reconcile import reconcile_deleted_activities
from kairos.connectors.types import Window
from kairos.ingestion import garmin_sync
from kairos.repositories.data_read import SqlDataReadRepository
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily
from tests.stream_seed import seed_hr_stream

WINDOW = Window(
    start=datetime(2026, 8, 1, tzinfo=UTC), end=datetime(2026, 8, 2, tzinfo=UTC)
)


async def _user(session: AsyncSession) -> UUID:
    uid = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :e, 'U', :s, 'UTC', 'user')"
        ),
        {"id": str(uid), "e": f"{uid}@t.com", "s": str(uid)},
    )
    return uid


async def _act(
    session: AsyncSession,
    uid: UUID,
    ext: str,
    start_local: datetime | None,
    start_at: datetime | None = None,
    max_hr: int | None = None,
) -> int:
    row = await session.execute(
        text(
            "INSERT INTO activity (user_id, external_id, start_at, start_local, max_hr) "
            "VALUES (:u, :x, :s, :l, :m) RETURNING id"
        ),
        {"u": str(uid), "x": ext, "s": start_at or start_local, "l": start_local, "m": max_hr},
    )
    return int(row.scalar_one())


async def _deleted(session: AsyncSession, activity_id: int) -> tuple[object, object]:
    row = await session.execute(
        text("SELECT deleted_at, deleted_reason FROM activity WHERE id = :i"), {"i": activity_id}
    )
    return row.one()


@pytest.mark.asyncio
async def test_missing_activity_is_marked_and_present_one_is_kept(session: AsyncSession) -> None:
    uid = await _user(session)
    gone = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0))
    kept = await _act(session, uid, "2", datetime(2026, 8, 2, 9, 0))
    await session.commit()

    ids = await reconcile_deleted_activities(
        session, user_id=uid, window=WINDOW, payload=[{"activityId": 2}]
    )

    assert [i for i, _ in ids] == [gone]
    at, reason = await _deleted(session, gone)
    assert at is not None and reason == "garmin_sync"
    assert (await _deleted(session, kept)) == (None, None)


@pytest.mark.asyncio
async def test_activity_outside_both_days_or_without_start_local_is_untouched(
    session: AsyncSession,
) -> None:
    uid = await _user(session)
    outside = await _act(session, uid, "1", datetime(2026, 8, 3, 0, 5))
    before = await _act(session, uid, "2", datetime(2026, 7, 31, 23, 55))
    no_local = await _act(session, uid, "3", None, start_at=datetime(2026, 8, 1, 9, tzinfo=UTC))
    await session.commit()

    ids = await reconcile_deleted_activities(session, user_id=uid, window=WINDOW, payload=[])

    assert ids == []
    for a in (outside, before, no_local):
        assert (await _deleted(session, a)) == (None, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{"error": "boom"}, None])
async def test_non_list_payload_marks_nothing(session: AsyncSession, payload: object) -> None:
    uid = await _user(session)
    a = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0))
    await session.commit()

    ids = await reconcile_deleted_activities(
        session, user_id=uid, window=WINDOW, payload=payload  # type: ignore[arg-type]
    )

    assert ids == []
    assert (await _deleted(session, a)) == (None, None)


@pytest.mark.asyncio
async def test_run_after_midnight_local_is_found_by_local_date(session: AsyncSession) -> None:
    uid = await _user(session)
    # 00:30 local on Aug 2 (UTC+2) is Aug 1 22:30 UTC; window days are Aug 2 and Aug 3
    window = Window(start=datetime(2026, 8, 2, tzinfo=UTC), end=datetime(2026, 8, 3, tzinfo=UTC))
    utc_start = datetime(2026, 8, 1, 22, 30, tzinfo=UTC)
    a = await _act(session, uid, "1", datetime(2026, 8, 2, 0, 30), start_at=utc_start)
    await session.commit()

    ids = await reconcile_deleted_activities(session, user_id=uid, window=window, payload=[])

    assert [i for i, _ in ids] == [a]


@pytest.mark.asyncio
async def test_already_deleted_is_not_reported_again(session: AsyncSession) -> None:
    uid = await _user(session)
    a = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0))
    await session.commit()
    await reconcile_deleted_activities(session, user_id=uid, window=WINDOW, payload=[])

    assert await reconcile_deleted_activities(
        session, user_id=uid, window=WINDOW, payload=[]
    ) == []
    assert (await _deleted(session, a))[1] == "garmin_sync"


async def _max_hr(session: AsyncSession, uid: UUID) -> int | None:
    result = await session.execute(
        text("SELECT max(max_hr) FROM activity WHERE user_id = :u AND deleted_at IS NULL"),
        {"u": str(uid)},
    )
    return result.scalar_one_or_none()


@pytest.mark.asyncio
async def test_deleted_activity_vanishes_from_hr_buckets_readers_and_max_hr(
    session: AsyncSession,
) -> None:
    uid = await _user(session)
    start = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    a = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0), start_at=start, max_hr=190)
    await seed_hr_stream(session, user_id=uid, activity_id=a, start_at=start, values=[142.0] * 3)
    await session.commit()
    repo = SqlDataReadRepository(session)
    day = date(2026, 8, 1)

    await recompute_hr_bucket_seconds_daily(session, user_id=uid, start=day, end=day)
    assert await _max_hr(session, uid) == 190
    assert await repo.get_activity_detail(user_id=uid, external_id="1") is not None

    await reconcile_deleted_activities(session, user_id=uid, window=WINDOW, payload=[])
    await recompute_hr_bucket_seconds_daily(session, user_id=uid, start=day, end=day)
    await session.commit()

    rows = (
        await session.execute(
            text("SELECT 1 FROM hr_bucket_seconds_daily WHERE user_id = :u"), {"u": str(uid)}
        )
    ).all()
    assert rows == []
    assert await _max_hr(session, uid) is None
    assert await repo.get_activity_detail(user_id=uid, external_id="1") is None
    page = await repo.list_activities(user_id=uid, limit=10, cursor=None)
    assert page.items == []


@pytest.mark.asyncio
async def test_activity_list_hook_reconciles_and_collects_days(session: AsyncSession) -> None:
    from kairos.connectors.types import RawPayloadEnvelope

    uid = await _user(session)
    start = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    a = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0), start_at=start)
    await session.commit()
    days: set[date] = set()
    hook = garmin_sync._make_fit_ingest_hook(session, uid, days)

    await hook("activity_list", RawPayloadEnvelope(window=WINDOW, payload=[]), 1, {})

    assert (await _deleted(session, a))[1] == "garmin_sync"
    assert days == {date(2026, 8, 1)}


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [{"foo": 1}, {"activityId": None}, "x", 5])
async def test_malformed_item_means_no_marking(session: AsyncSession, bad: object) -> None:
    uid = await _user(session)
    a = await _act(session, uid, "1", datetime(2026, 8, 1, 9, 0))
    await session.commit()

    ids = await reconcile_deleted_activities(
        session, user_id=uid, window=WINDOW, payload=[{"activityId": 2}, bad]  # type: ignore[list-item]
    )

    assert ids == []
    assert (await _deleted(session, a)) == (None, None)
