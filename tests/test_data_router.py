# tests/test_data_router.py
from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session


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
async def test_user_id(db_session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id, f"{user_id}@test.com", f"sub-{user_id}")
    await db_session.commit()
    return user_id


@pytest_asyncio.fixture
async def authed_client(db_session: AsyncSession, test_user_id: uuid.UUID):
    app.dependency_overrides[current_user] = lambda: {"user_id": str(test_user_id)}

    async def _override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def seeded_hr_samples(
    db_session: AsyncSession, test_user_id: uuid.UUID
) -> tuple[uuid.UUID, int]:
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
            {"uid": str(test_user_id), "mid": metric_id, "ts": observed_at, "val": value},
        )
    await db_session.commit()
    return test_user_id, metric_id


@pytest_asyncio.fixture
async def seeded_activities(db_session: AsyncSession, test_user_id: uuid.UUID) -> uuid.UUID:
    for i in range(3):
        await db_session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, name, sport, start_at)
                VALUES (:uid, :eid, :name, 'running', :start_at)
                """
            ),
            {
                "uid": str(test_user_id),
                "eid": f"act-{i}",
                "name": f"Run {i}",
                "start_at": datetime(2026, 8, 1 + i, 8, 0, tzinfo=UTC),
            },
        )
    await db_session.commit()
    return test_user_id


@pytest.mark.asyncio
async def test_wellness_series_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/data/wellness/hr")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_wellness_series_returns_ordered_points(authed_client, seeded_hr_samples):
    resp = await authed_client.get(
        "/api/data/wellness/hr", params={"from_date": "2026-08-01", "to_date": "2026-08-02"}
    )
    assert resp.status_code == 200
    body = resp.json()
    values = [p["observed_at"] for p in body["points"]]
    assert values == sorted(values)


@pytest.mark.asyncio
async def test_activities_list_paginates(authed_client, seeded_activities):
    resp = await authed_client.get("/api/data/activities", params={"limit": 2})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2
    assert "next_cursor" in body
