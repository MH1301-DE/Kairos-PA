# tests/test_dashboard_router.py
from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.routers.dashboard import _DEFAULT_MODULE_ORDER


async def _insert_user(session: AsyncSession, user_id: uuid.UUID, email: str, sub: str) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
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


@pytest.mark.asyncio
async def test_dashboard_layout_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/dashboard/layout")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_layout_returns_default_order_with_no_saved_rows(
    authed_client: AsyncClient,
) -> None:
    resp = await authed_client.get("/api/dashboard/layout")
    assert resp.status_code == 200
    tiles = resp.json()["tiles"]
    assert [t["module_id"] for t in tiles] == list(_DEFAULT_MODULE_ORDER)
    assert all(t["visible"] for t in tiles)
    assert [t["position"] for t in tiles] == list(range(len(_DEFAULT_MODULE_ORDER)))


@pytest.mark.asyncio
async def test_put_then_get_round_trips_custom_layout(authed_client: AsyncClient) -> None:
    custom = [
        {"module_id": "hrv_baseline", "position": 0, "visible": True},
        {"module_id": "trimp", "position": 1, "visible": False},
    ]
    put_resp = await authed_client.put("/api/dashboard/layout", json={"tiles": custom})
    assert put_resp.status_code == 200

    get_resp = await authed_client.get("/api/dashboard/layout")
    assert get_resp.json()["tiles"] == custom


@pytest.mark.asyncio
async def test_put_rejects_unknown_module_id(authed_client: AsyncClient) -> None:
    resp = await authed_client.put(
        "/api/dashboard/layout",
        json={"tiles": [{"module_id": "not_a_real_module", "position": 0, "visible": True}]},
    )
    assert resp.status_code == 422

    # nothing was written -- GET still falls back to the default
    get_resp = await authed_client.get("/api/dashboard/layout")
    assert [t["module_id"] for t in get_resp.json()["tiles"]] == list(_DEFAULT_MODULE_ORDER)


@pytest.mark.asyncio
async def test_dashboard_layout_enforces_rls_isolation(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session, user_a, f"{user_a}@test.com", f"sub-{user_a}")
    await _insert_user(session, user_b, f"{user_b}@test.com", f"sub-{user_b}")
    await session.commit()

    install_rls_listener(app_session, user_a)
    await app_session.execute(
        text(
            "INSERT INTO user_dashboard_tile (user_id, module_id, position, visible) "
            "VALUES (:uid, 'trimp', 0, true)"
        ),
        {"uid": str(user_a)},
    )
    await app_session.commit()

    install_rls_listener(app_session, user_b)
    from sqlalchemy import select

    from kairos.db.models import UserDashboardTile

    rows = (
        await app_session.execute(
            select(UserDashboardTile).where(UserDashboardTile.user_id == user_b)
        )
    ).scalars().all()
    assert rows == []
