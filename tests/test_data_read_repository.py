# tests/test_data_read_repository.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.data_read import SqlDataReadRepository


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
        (datetime(2026, 8, 3, 0, 0, tzinfo=UTC), 70.0),  # after range
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
    for i in range(3):
        await db_session.execute(
            text(
                """
                INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value)
                VALUES (:uid, :aid, :ts, 'hr', :val)
                """
            ),
            {
                "uid": str(user_id),
                "aid": activity_id,
                "ts": datetime(2026, 8, 1, 8, 0, i, tzinfo=UTC),
                "val": 140.0 + i,
            },
        )
    await db_session.commit()
    return user_id, external_id


@pytest.mark.asyncio
async def test_list_wellness_series_filters_by_date_range(db_session, seeded_hr_samples):
    user_id, metric_id = seeded_hr_samples
    repo = SqlDataReadRepository(session=db_session)
    result = await repo.list_wellness_series(
        user_id=user_id,
        metric="hr",
        from_date=datetime(2026, 8, 1, tzinfo=UTC),
        to_date=datetime(2026, 8, 2, tzinfo=UTC),
    )
    assert all(
        datetime(2026, 8, 1, tzinfo=UTC) <= s.observed_at <= datetime(2026, 8, 2, tzinfo=UTC)
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
async def test_get_activity_detail_includes_records(db_session, seeded_activity_with_records):
    user_id, external_id = seeded_activity_with_records
    repo = SqlDataReadRepository(session=db_session)
    detail = await repo.get_activity_detail(user_id=user_id, external_id=external_id)
    assert detail is not None
    assert len(detail.records) > 0
