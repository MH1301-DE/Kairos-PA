# tests/test_memory_router.py
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


@pytest.mark.asyncio
async def test_memory_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/memory")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_create_list_update_delete_memory(authed_client: AsyncClient) -> None:
    create_resp = await authed_client.post(
        "/api/memory", json={"content": "trainiert ungern vor 7 Uhr"}
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["content"] == "trainiert ungern vor 7 Uhr"
    # client can never spoof the "agent" badge -- always created as "user"
    assert created["source"] == "user"
    memory_id = created["id"]

    list_resp = await authed_client.get("/api/memory")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["entries"]) == 1

    update_resp = await authed_client.patch(
        f"/api/memory/{memory_id}", json={"content": "trainiert ungern vor 6 Uhr"}
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["content"] == "trainiert ungern vor 6 Uhr"
    assert update_resp.json()["source"] == "user"

    delete_resp = await authed_client.delete(f"/api/memory/{memory_id}")
    assert delete_resp.status_code == 204

    final_list = await authed_client.get("/api/memory")
    assert final_list.json()["entries"] == []


@pytest.mark.asyncio
async def test_create_memory_rejects_empty_content(authed_client: AsyncClient) -> None:
    resp = await authed_client.post("/api/memory", json={"content": "   "})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_update_unknown_memory_returns_404(authed_client: AsyncClient) -> None:
    resp = await authed_client.patch(f"/api/memory/{uuid.uuid4()}", json={"content": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_unknown_memory_returns_404(authed_client: AsyncClient) -> None:
    resp = await authed_client.delete(f"/api/memory/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_memory_enforce_rls_isolation(
    db_session: AsyncSession, session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session, user_a, f"{user_a}@test.com", f"sub-{user_a}")
    await _insert_user(session, user_b, f"{user_b}@test.com", f"sub-{user_b}")
    await session.commit()

    install_rls_listener(app_session, user_a)

    from kairos.repositories.memory import SqlMemoryRepository

    repo_a = SqlMemoryRepository(session=app_session)
    await repo_a.create(user_id=user_a, content="A's memory", source="user")
    await app_session.commit()

    install_rls_listener(app_session, user_b)
    repo_b = SqlMemoryRepository(session=app_session)
    entries_for_b = await repo_b.list_for_user(user_id=user_b)
    assert entries_for_b == []
