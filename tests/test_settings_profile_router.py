from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session
from kairos.metrics.hr_zones import resolve_hr_max
from kairos.routers import settings_profile


async def _insert_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


async def _insert_activity(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    max_hr: int,
    days_ago: int,
    deleted: bool = False,
) -> None:
    await session.execute(
        text(
            "INSERT INTO activity (user_id, external_id, start_at, max_hr, deleted_at) "
            "VALUES (:u, :x, :s, :m, :d)"
        ),
        {
            "u": user_id,
            "x": str(uuid.uuid4()),
            "s": datetime.now(UTC) - timedelta(days=days_ago),
            "m": max_hr,
            "d": datetime.now(UTC) if deleted else None,
        },
    )


@pytest_asyncio.fixture
async def user_id(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await _insert_user(session, uid)
    await session.commit()
    return uid


@pytest_asyncio.fixture
async def client(session: AsyncSession, user_id: uuid.UUID):
    app.dependency_overrides[current_user] = lambda: {"user_id": str(user_id)}

    async def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


_EMPTY = {
    "birth_date": None,
    "hr_max_override": None,
    "resting_hr_override": None,
    "hr_max_used": None,
    "hr_max_source": None,
    "hr_max_measured_12m": None,
    "hr_max_warning": None,
}


def test_resolve_hr_max_prefers_override() -> None:
    assert resolve_hr_max(date(1990, 1, 1), 214, as_of=date(2026, 10, 14)) == (214, "eingetragen")


def test_resolve_hr_max_falls_back_to_age() -> None:
    # birthday not yet reached in 2026 -> age 35
    assert resolve_hr_max(date(1990, 12, 1), None, as_of=date(2026, 10, 14)) == (184, "aus Alter")


def test_resolve_hr_max_without_inputs_is_none() -> None:
    assert resolve_hr_max(None, None, as_of=date(2026, 10, 14)) == (None, None)


@pytest.mark.asyncio
async def test_profile_requires_auth() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/api/settings/profile")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_without_row_is_all_null(client: AsyncClient) -> None:
    resp = await client.get("/api/settings/profile")
    assert resp.status_code == 200
    assert resp.json() == _EMPTY


@pytest.mark.asyncio
async def test_put_override_is_used(client: AsyncClient) -> None:
    put = await client.put(
        "/api/settings/profile",
        json={"birth_date": "1990-05-01", "hr_max_override": 214, "resting_hr_override": 48},
    )
    assert put.status_code == 200
    body = (await client.get("/api/settings/profile")).json()
    assert body["birth_date"] == "1990-05-01"
    assert body["hr_max_override"] == 214
    assert body["resting_hr_override"] == 48
    assert body["hr_max_used"] == 214
    assert body["hr_max_source"] == "eingetragen"
    assert body["hr_max_warning"] is None


@pytest.mark.asyncio
async def test_put_null_clears_fields(client: AsyncClient) -> None:
    await client.put(
        "/api/settings/profile",
        json={"birth_date": "1990-05-01", "hr_max_override": 214, "resting_hr_override": 48},
    )
    put = await client.put(
        "/api/settings/profile",
        json={"birth_date": None, "hr_max_override": None, "resting_hr_override": None},
    )
    assert put.status_code == 200
    assert (await client.get("/api/settings/profile")).json() == _EMPTY


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {"hr_max_override": 250},
        {"hr_max_override": 119},
        {"resting_hr_override": 29},
        {"resting_hr_override": 101},
        {"birth_date": "1899-12-31"},
        {"birth_date": (date.today() + timedelta(days=1)).isoformat()},
    ],
)
async def test_put_rejects_out_of_range(client: AsyncClient, body: dict[str, object]) -> None:
    resp = await client.put("/api/settings/profile", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_birth_date_only_uses_age(client: AsyncClient) -> None:
    await client.put("/api/settings/profile", json={"birth_date": "1990-05-01"})
    body = (await client.get("/api/settings/profile")).json()
    expected, _ = resolve_hr_max(date(1990, 5, 1), None, as_of=datetime.now(UTC).date())
    assert body["hr_max_used"] == expected
    assert body["hr_max_source"] == "aus Alter"


@pytest.mark.asyncio
async def test_warning_when_measured_exceeds_used(
    client: AsyncClient, session: AsyncSession, user_id: uuid.UUID
) -> None:
    await _insert_activity(session, user_id, max_hr=219, days_ago=30)
    await _insert_activity(session, user_id, max_hr=230, days_ago=400)
    await _insert_activity(session, user_id, max_hr=240, days_ago=10, deleted=True)
    await session.commit()
    await client.put("/api/settings/profile", json={"hr_max_override": 214})

    body = (await client.get("/api/settings/profile")).json()
    assert body["hr_max_measured_12m"] == 219
    assert body["hr_max_warning"] == "gemessen 219 bpm, eingetragen 214 – prüfen"


@pytest.mark.asyncio
async def test_no_warning_when_measured_below_used(
    client: AsyncClient, session: AsyncSession, user_id: uuid.UUID
) -> None:
    await _insert_activity(session, user_id, max_hr=205, days_ago=30)
    await session.commit()
    await client.put("/api/settings/profile", json={"hr_max_override": 214})

    body = (await client.get("/api/settings/profile")).json()
    assert body["hr_max_measured_12m"] == 205
    assert body["hr_max_warning"] is None


@pytest.mark.asyncio
async def test_no_warning_when_measured_equals_used(
    client: AsyncClient, session: AsyncSession, user_id: uuid.UUID
) -> None:
    await _insert_activity(session, user_id, max_hr=214, days_ago=30)
    await session.commit()
    await client.put("/api/settings/profile", json={"hr_max_override": 214})

    body = (await client.get("/api/settings/profile")).json()
    assert body["hr_max_measured_12m"] == 214
    assert body["hr_max_warning"] is None


@pytest.mark.asyncio
async def test_profile_is_isolated_per_user(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    await _insert_user(session, user_a)
    await _insert_user(session, user_b)
    await session.commit()

    async def _override_get_session():
        yield app_session

    app.dependency_overrides[get_session] = _override_get_session
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            app.dependency_overrides[current_user] = lambda: {"user_id": str(user_a)}
            put = await c.put("/api/settings/profile", json={"hr_max_override": 214})
            assert put.status_code == 200
            assert (await c.get("/api/settings/profile")).json()["hr_max_override"] == 214

            app.dependency_overrides[current_user] = lambda: {"user_id": str(user_b)}
            assert (await c.get("/api/settings/profile")).json() == _EMPTY
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_hr_max_change_triggers_history_rederive(
    client: AsyncClient, user_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[uuid.UUID] = []

    async def _record(uid: uuid.UUID) -> None:
        calls.append(uid)

    monkeypatch.setattr(settings_profile, "_rederive_history", _record)
    body = {"birth_date": None, "hr_max_override": 190, "resting_hr_override": None}
    await client.put("/api/settings/profile", json=body)
    assert calls == [user_id]

    await client.put("/api/settings/profile", json=body)
    await client.put("/api/settings/profile", json={**body, "resting_hr_override": 50})
    assert calls == [user_id]

    await client.put("/api/settings/profile", json={**body, "birth_date": "1990-05-01"})
    assert calls == [user_id, user_id]
