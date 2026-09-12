# tests/test_custom_metrics_router.py
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
async def test_custom_metrics_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/custom")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_custom_resolves_to_custom_router_not_metric_id_catchall(
    authed_client: AsyncClient,
) -> None:
    # regression test for the router-registration-order fix in api.py: this must
    # be an empty {"definitions": []}, not a 404 "Unknown metric: custom" from
    # metrics_router's GET /api/metrics/{metric_id}
    resp = await authed_client.get("/api/metrics/custom")
    assert resp.status_code == 200
    assert resp.json() == {"definitions": []}


@pytest.mark.asyncio
async def test_create_list_delete_custom_metric(authed_client: AsyncClient) -> None:
    create_resp = await authed_client.post(
        "/api/metrics/custom",
        json={
            "code": "my_recovery_score",
            "display_name": "Mein Recovery Score",
            "expression": "hr * 0.5",
        },
    )
    assert create_resp.status_code == 201
    created = create_resp.json()
    assert created["code"] == "my_recovery_score"
    assert created["created_by"] == "user"
    definition_id = created["id"]

    list_resp = await authed_client.get("/api/metrics/custom")
    assert list_resp.status_code == 200
    assert len(list_resp.json()["definitions"]) == 1

    delete_resp = await authed_client.delete(f"/api/metrics/custom/{definition_id}")
    assert delete_resp.status_code == 204

    final_list = await authed_client.get("/api/metrics/custom")
    assert final_list.json()["definitions"] == []


@pytest.mark.asyncio
async def test_create_rejects_unknown_metric_reference(authed_client: AsyncClient) -> None:
    resp = await authed_client.post(
        "/api/metrics/custom",
        json={
            "code": "bogus",
            "display_name": "Bogus",
            "expression": "not_a_real_metric * 2",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_invalid_expression(authed_client: AsyncClient) -> None:
    resp = await authed_client.post(
        "/api/metrics/custom",
        json={"code": "bogus2", "display_name": "Bogus 2", "expression": "__import__('os')"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_accepts_a_formula_metric_reference(authed_client: AsyncClient) -> None:
    # 'trimp' is a MetricRegistry formula id (not a metric_def row) -- must also
    # be accepted, not just raw ingested metric codes like 'hr'
    resp = await authed_client.post(
        "/api/metrics/custom",
        json={"code": "trimp_scaled", "display_name": "Scaled TRIMP", "expression": "trimp * 2"},
    )
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_delete_unknown_custom_metric_returns_404(authed_client: AsyncClient) -> None:
    resp = await authed_client.delete(f"/api/metrics/custom/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_custom_metrics_enforce_rls_isolation(
    db_session: AsyncSession, session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()
    await _insert_user(session, user_a, f"{user_a}@test.com", f"sub-{user_a}")
    await _insert_user(session, user_b, f"{user_b}@test.com", f"sub-{user_b}")
    await session.commit()

    install_rls_listener(app_session, user_a)

    from kairos.repositories.custom_metrics import CustomMetricRepository

    repo_a = CustomMetricRepository(session=app_session)
    await repo_a.create(
        user_id=user_a, code="a_metric", display_name="A", expression="hr * 1",
        created_by="user",
    )
    await app_session.commit()

    install_rls_listener(app_session, user_b)
    repo_b = CustomMetricRepository(session=app_session)
    definitions_for_b = await repo_b.list_for_user(user_id=user_b)
    assert definitions_for_b == []
