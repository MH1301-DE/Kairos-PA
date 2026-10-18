from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session

_PLAN_TYPE = "ausdauer-laufen-pyramidal"
_BODY = {
    "plan_type": _PLAN_TYPE,
    "availability": {
        "di": {"max_min": 60, "quality": True, "time": "18:00"},
        "sa": {"max_min": 90},
        "so": {"max_min": 120},
    },
}


@pytest_asyncio.fixture
async def user_id(session: AsyncSession) -> uuid.UUID:
    uid = uuid.uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(uid), "email": f"{uid}@test.com", "sub": f"sub-{uid}"},
    )
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


@pytest.mark.asyncio
async def test_get_without_profile_lists_plan_types(client: AsyncClient) -> None:
    resp = await client.get("/api/coach/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] is None
    assert _PLAN_TYPE in [p["id"] for p in body["plan_types"]]


@pytest.mark.asyncio
async def test_put_creates_then_updates_profile(client: AsyncClient) -> None:
    resp = await client.put("/api/coach/profile", json=_BODY)
    assert resp.status_code == 200
    profile = resp.json()["profile"]
    assert profile["main_sport"] == "laufen"
    assert profile["availability"]["di"] == {"max_min": 60, "quality": True, "time": "18:00"}
    assert profile["availability"]["sa"] == {"max_min": 90, "quality": False}
    assert profile["onboarded_at"] is not None

    changed = {**_BODY, "availability": {"mi": {"max_min": 45}}}
    resp = await client.put("/api/coach/profile", json=changed)
    assert resp.status_code == 200
    assert resp.json()["profile"]["availability"] == {"mi": {"max_min": 45, "quality": False}}
    assert (await client.get("/api/coach/profile")).json()["profile"]["availability"] == {
        "mi": {"max_min": 45, "quality": False}
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        {**_BODY, "plan_type": "gibt-es-nicht"},
        {**_BODY, "availability": {"xx": {"max_min": 30}}},
        {**_BODY, "availability": {"mo": {"max_min": 0}}},
        {**_BODY, "availability": {"mo": {"max_min": 30, "time": "25:00"}}},
        {**_BODY, "availability": {"mo": {"max_min": 700}}},
    ],
)
async def test_put_rejects_invalid_input(client: AsyncClient, body: dict[str, object]) -> None:
    resp = await client.put("/api/coach/profile", json=body)
    assert resp.status_code == 422
    assert (await client.get("/api/coach/profile")).json()["profile"] is None
