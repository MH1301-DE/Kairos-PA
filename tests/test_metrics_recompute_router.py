# tests/test_metrics_recompute_router.py
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


async def _insert_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest_asyncio.fixture
async def db_session(session: AsyncSession) -> AsyncSession:
    return session


@pytest_asyncio.fixture
async def test_user_id(db_session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(db_session, user_id)
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


@pytest.mark.asyncio
async def test_recompute_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/metrics/recompute")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_recompute_populates_daily_stats_from_wellness_samples(
    authed_client: AsyncClient, db_session: AsyncSession, test_user_id: uuid.UUID
) -> None:
    metric_id = (
        await db_session.execute(text("SELECT id FROM metric_def WHERE code = 'hr'"))
    ).scalar_one()
    for minute, value in enumerate((60.0, 62.0, 58.0)):
        await db_session.execute(
            text(
                "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value, quality) "
                "VALUES (:uid, :mid, :ts, :val, 'ok')"
            ),
            {
                "uid": str(test_user_id),
                "mid": metric_id,
                "ts": datetime(2026, 8, 1, 9, minute, tzinfo=UTC),
                "val": value,
            },
        )
    await db_session.commit()

    resp = await authed_client.post(
        "/api/metrics/recompute",
        params={"from_date": "2026-08-01", "to_date": "2026-08-01"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["from_date"] == "2026-08-01"
    assert body["to_date"] == "2026-08-01"

    row = (
        await db_session.execute(
            text(
                "SELECT avg_value, min_value, max_value, sample_count FROM wellness_daily_stats "
                "WHERE user_id = :uid AND metric_id = :mid AND day = '2026-08-01'"
            ),
            {"uid": str(test_user_id), "mid": metric_id},
        )
    ).one()
    assert row.sample_count == 3
    assert row.min_value == 58.0
    assert row.max_value == 62.0


@pytest.mark.asyncio
async def test_recompute_defaults_to_two_year_window(authed_client: AsyncClient) -> None:
    resp = await authed_client.post("/api/metrics/recompute")
    assert resp.status_code == 200
    body = resp.json()
    from datetime import date, timedelta

    expected_start = date.today() - timedelta(days=730)
    assert body["from_date"] == expected_start.isoformat()
    assert body["to_date"] == date.today().isoformat()
