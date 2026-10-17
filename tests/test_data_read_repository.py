# tests/test_data_read_repository.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.rls import install_rls_listener
from kairos.repositories.data_read import SqlDataReadRepository
from tests.stream_seed import seed_hr_stream


async def _insert_user(session: AsyncSession, user_id: uuid.UUID, email: str, sub: str) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": email, "sub": sub},
    )


@pytest_asyncio.fixture
async def db_session(session: AsyncSession) -> AsyncSession:
    return session


@pytest_asyncio.fixture
async def seeded_hr_samples(db_session: AsyncSession) -> tuple[uuid.UUID, int]:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    metric_id = (
        await db_session.execute(text("SELECT id FROM metric_def WHERE code = 'hr'"))
    ).scalar_one()
    samples = [
        (datetime(2026, 7, 31, 12, 0, tzinfo=UTC), 55.0),  # before range
        (datetime(2026, 8, 1, 6, 0, tzinfo=UTC), 60.0),
        (datetime(2026, 8, 1, 18, 0, tzinfo=UTC), 65.0),
        (datetime(2026, 8, 2, 0, 0, tzinfo=UTC), 58.0),
        # strictly inside the range but on no boundary instant — the row an inclusive-midnight
        # upper bound silently dropped
        (datetime(2026, 8, 2, 18, 0, tzinfo=UTC), 62.0),
        (datetime(2026, 8, 3, 0, 0, tzinfo=UTC), 70.0),  # at/after the exclusive upper bound
    ]
    for observed_at, value in samples:
        await db_session.execute(
            text(
                """
                INSERT INTO wellness_sample (user_id, metric_id, observed_at, value)
                VALUES (:uid, :mid, :ts, :val)
                """
            ),
            {"uid": str(user_id), "mid": metric_id, "ts": observed_at, "val": value},
        )
    await db_session.commit()
    return user_id, metric_id


@pytest_asyncio.fixture
async def seeded_activities(db_session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    for i in range(3):
        await db_session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, :name, 'running', :start_at)
                """
            ),
            {
                "uid": str(user_id),
                "eid": f"act-{i}",
                "name": f"Run {i}",
                "start_at": datetime(2026, 8, 1 + i, 8, 0, tzinfo=UTC),
            },
        )
    await db_session.commit()
    return user_id


@pytest_asyncio.fixture
async def seeded_activities_with_null_start_at(db_session: AsyncSession) -> uuid.UUID:
    """Two activities with start_at IS NULL (inserted first, so smaller ids) plus two with a
    real start_at — used to exercise the cursor-pagination boundary where the last item on a
    page has a NULL start_at (Postgres sorts NULLs first for DESC ordering)."""
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    for i in range(2):
        await db_session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, :name, 'running', NULL)
                """
            ),
            {"uid": str(user_id), "eid": f"act-null-{i}", "name": f"Unstarted {i}"},
        )
    for i in range(2):
        await db_session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, :name, 'running', :start_at)
                """
            ),
            {
                "uid": str(user_id),
                "eid": f"act-dated-{i}",
                "name": f"Run {i}",
                "start_at": datetime(2026, 8, 1 + i, 8, 0, tzinfo=UTC),
            },
        )
    await db_session.commit()
    return user_id


@pytest_asyncio.fixture
async def seeded_sleep_sessions(db_session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    sessions = [
        ("sleep-0", datetime(2026, 7, 31, 22, 0, tzinfo=UTC)),  # before range
        ("sleep-1", datetime(2026, 8, 1, 6, 0, tzinfo=UTC)),
        ("sleep-2", datetime(2026, 8, 1, 22, 0, tzinfo=UTC)),
        ("sleep-3", datetime(2026, 8, 2, 0, 0, tzinfo=UTC)),
        # strictly inside the range but on no boundary instant
        ("sleep-4", datetime(2026, 8, 2, 18, 0, tzinfo=UTC)),
        ("sleep-5", datetime(2026, 8, 3, 0, 0, tzinfo=UTC)),  # at/after exclusive upper bound
    ]
    for external_id, start_at in sessions:
        await db_session.execute(
            text(
                """
                INSERT INTO sleep_session (user_id, external_id, start_at, duration_seconds)
                VALUES (:uid, :eid, :start_at, 25200)
                """
            ),
            {"uid": str(user_id), "eid": external_id, "start_at": start_at},
        )
    await db_session.commit()
    return user_id


@pytest_asyncio.fixture
async def seeded_activity_with_records(db_session: AsyncSession) -> tuple[uuid.UUID, str]:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    external_id = "act-with-records"
    activity_id = (
        await db_session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, 'Run', 'running', :start_at)
                RETURNING id
                """
            ),
            {
                "uid": str(user_id),
                "eid": external_id,
                "start_at": datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            },
        )
    ).scalar_one()
    await seed_hr_stream(
        db_session, user_id=user_id, activity_id=activity_id,
        start_at=datetime(2026, 8, 1, 8, 0, tzinfo=UTC), values=[140.0, 141.0, 142.0],
    )
    await db_session.commit()
    return user_id, external_id


@pytest.mark.asyncio
async def test_list_wellness_series_filters_by_date_range(db_session, seeded_hr_samples):
    """`to_date` is an EXCLUSIVE upper bound: callers pass midnight of the day AFTER the last
    wanted day, so every sample of that last day (not just its 00:00 instant) is returned."""
    user_id, metric_id = seeded_hr_samples
    del metric_id
    repo = SqlDataReadRepository(session=db_session)
    result = await repo.list_wellness_series(
        user_id=user_id,
        metric="hr",
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 3, tzinfo=UTC),
    )
    observed = [s.observed_at for s in result]
    assert datetime(2026, 8, 2, 18, 0, tzinfo=UTC) in observed
    assert datetime(2026, 8, 3, 0, 0, tzinfo=UTC) not in observed
    assert datetime(2026, 7, 31, 12, 0, tzinfo=UTC) not in observed
    assert all(
        datetime(2026, 8, 1, tzinfo=UTC) <= s.observed_at < datetime(2026, 8, 3, tzinfo=UTC)
        for s in result
    )


@pytest.mark.asyncio
async def test_list_activities_paginates_with_cursor(db_session, seeded_activities):
    user_id = seeded_activities
    repo = SqlDataReadRepository(session=db_session)
    page1 = await repo.list_activities(user_id=user_id, limit=2)
    assert len(page1.items) == 2
    assert page1.next_cursor is not None
    page2 = await repo.list_activities(user_id=user_id, limit=2, cursor=page1.next_cursor)
    assert {a.external_id for a in page1.items}.isdisjoint({a.external_id for a in page2.items})


@pytest.mark.asyncio
async def test_get_activity_detail_returns_stream_series(db_session, seeded_activity_with_records):
    user_id, external_id = seeded_activity_with_records
    repo = SqlDataReadRepository(session=db_session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id=external_id)
    assert detail is not None
    assert detail.t_offset_s == [0, 1, 2]
    assert detail.series == {"hr": [140.0, 141.0, 142.0]}


@pytest.mark.asyncio
async def test_get_activity_detail_mean_downsamples_to_max_points(db_session):
    user_id = uuid.uuid4()
    await db_session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'T', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    start_at = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    activity_id = (
        await db_session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'long', :s) RETURNING id"
            ),
            {"uid": str(user_id), "s": start_at},
        )
    ).scalar_one()
    values: list[float | None] = [float(i) for i in range(5000)]
    values[0:50] = [None] * 50  # first bucket (50 samples) is all None
    await seed_hr_stream(
        db_session, user_id=user_id, activity_id=activity_id, start_at=start_at, values=values
    )
    await db_session.commit()

    repo = SqlDataReadRepository(session=db_session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id="long", max_points=100)

    assert detail is not None
    assert len(detail.t_offset_s) == 100
    assert detail.t_offset_s[:3] == [0, 50, 100]
    hr = detail.series["hr"]
    assert len(hr) == 100
    assert hr[0] is None
    assert hr[1] == pytest.approx(74.5)  # mean of 50..99
    assert hr[99] == pytest.approx(4974.5)


@pytest.mark.asyncio
async def test_list_activities_paginates_across_null_start_at_boundary(
    db_session, seeded_activities_with_null_start_at
):
    """Regression test for the cursor-pagination bug: when the last item on a page has
    start_at IS NULL, next_cursor must still be set (not silently dropped), and the next
    page must be reachable and disjoint from the first."""
    user_id = seeded_activities_with_null_start_at
    repo = SqlDataReadRepository(session=db_session)

    page1 = await repo.list_activities(user_id=user_id, limit=2)
    assert len(page1.items) == 2
    # NULLs sort first for DESC ordering, so both null-start_at rows land on page 1.
    assert all(a.start_at is None for a in page1.items)
    assert page1.next_cursor is not None

    page2 = await repo.list_activities(user_id=user_id, limit=2, cursor=page1.next_cursor)
    assert len(page2.items) == 2
    assert all(a.start_at is not None for a in page2.items)
    assert {a.external_id for a in page1.items}.isdisjoint({a.external_id for a in page2.items})


@pytest.mark.asyncio
async def test_list_sleep_sessions_filters_by_date_range(db_session, seeded_sleep_sessions):
    """`to_date` is an EXCLUSIVE upper bound — see the wellness counterpart above."""
    user_id = seeded_sleep_sessions
    repo = SqlDataReadRepository(session=db_session)
    result = await repo.list_sleep_sessions(
        user_id=user_id,
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 3, tzinfo=UTC),
    )
    starts = [s.start_at for s in result]
    assert datetime(2026, 8, 2, 18, 0, tzinfo=UTC) in starts
    assert datetime(2026, 8, 3, 0, 0, tzinfo=UTC) not in starts
    assert datetime(2026, 7, 31, 22, 0, tzinfo=UTC) not in starts
    assert all(
        datetime(2026, 8, 1, tzinfo=UTC) <= s.start_at < datetime(2026, 8, 3, tzinfo=UTC)
        for s in result
    )


@pytest.mark.asyncio
async def test_data_read_repository_enforces_rls_isolation(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    """The read API's RLS enforcement (install_rls_listener) is only real on a non-superuser
    connection — every other test in this file uses the superuser `session` fixture, which
    bypasses RLS. This mirrors tests/test_rls.py::test_rls_isolates_users against the new read
    repository. One method is enough: the RLS policy is table-level, not per-endpoint, so
    proving the listener drives enforcement for list_activities validates the mechanism for
    the whole /api/data/* surface."""
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()

    # Seed via the superuser session (superuser bypasses RLS → no WITH CHECK blocks)
    for user_id, external_id in ((user_a_id, "act-rls-a"), (user_b_id, "act-rls-b")):
        await _insert_user(session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
        await session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, 'Run', 'running', :start_at)
                """
            ),
            {
                "uid": str(user_id),
                "eid": external_id,
                "start_at": datetime(2026, 8, 1, 8, 0, tzinfo=UTC),
            },
        )
    await session.commit()

    # app_session connects as kairos_app (NOSUPERUSER) → RLS is enforced
    install_rls_listener(app_session, user_a_id)
    repo = SqlDataReadRepository(session=app_session)

    page_a = await repo.list_activities(user_id=user_a_id, limit=50)
    assert {a.external_id for a in page_a.items} == {"act-rls-a"}

    # Even asking explicitly for user B's rows returns nothing under user A's RLS context
    page_b = await repo.list_activities(user_id=user_b_id, limit=50)
    assert page_b.items == []
