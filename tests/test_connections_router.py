from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import kairos.auth.session as _sess
from kairos.api import app
from kairos.auth.deps import current_user
from kairos.connectors.garmin.client import (
    AuthTokens,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)
from kairos.db.session import get_session
from kairos.routers import connections as connections_module


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        if session_id == "valid":
            return {"user_id": str(uuid4())}
        return None

    import kairos.auth.deps as _deps

    monkeypatch.setattr(_deps, "get_session", _fake_get_session)
    _ = _sess  # imported only to document which module owns get_session; deps binds its own name


@pytest.mark.asyncio
async def test_garmin_connection_success_returns_201(authed_client: AsyncClient) -> None:
    with patch.object(
        connections_module.GarminClient, "login",
        return_value=AuthTokens(access_token="", refresh_token='{"fake":"token"}'),
    ), patch.object(connections_module, "_store_connection", new=AsyncMock()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "a@b.com", "password": "pw", "mfa_token": None},
        )
    assert resp.status_code == 201
    assert resp.json() == {"status": "connected"}


@pytest.mark.asyncio
async def test_garmin_connection_mfa_required_returns_202(authed_client: AsyncClient) -> None:
    with patch.object(connections_module.GarminClient, "login", side_effect=NeedsMfaToken()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "a@b.com", "password": "pw", "mfa_token": None},
        )
    assert resp.status_code == 202
    assert resp.json() == {"status": "mfa_required"}


@pytest.mark.asyncio
async def test_garmin_connection_invalid_credentials_returns_401(
    authed_client: AsyncClient,
) -> None:
    with patch.object(connections_module.GarminClient, "login", side_effect=InvalidCredentials()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "a@b.com", "password": "wrong", "mfa_token": None},
        )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid_credentials"}


@pytest.mark.asyncio
async def test_garmin_connection_upstream_unavailable_returns_503(
    authed_client: AsyncClient,
) -> None:
    with patch.object(connections_module.GarminClient, "login", side_effect=UpstreamUnavailable()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "a@b.com", "password": "pw", "mfa_token": None},
        )
    assert resp.status_code == 503
    assert resp.json() == {"detail": "garmin_unavailable"}


@pytest.mark.asyncio
async def test_garmin_connection_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/connections/garmin",
            json={"email": "a@b.com", "password": "pw", "mfa_token": None},
        )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_list_connections_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/connections")
    assert resp.status_code == 401


async def _insert_user(session: AsyncSession, user_id: uuid.UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


async def _insert_garmin_connection(
    session: AsyncSession, user_id: uuid.UUID, external_account: str, status: str = "active"
) -> None:
    await session.execute(
        text(
            "INSERT INTO connection (id, user_id, connector, external_account, status, config) "
            "VALUES (:id, :uid, 'garmin', :account, :status, '{}'::jsonb)"
        ),
        {"id": str(uuid4()), "uid": str(user_id), "account": external_account, "status": status},
    )


@pytest_asyncio.fixture
async def authed_client(session: AsyncSession, test_user_id: uuid.UUID):
    app.dependency_overrides[current_user] = lambda: {"user_id": str(test_user_id)}

    async def _override_get_session():
        yield session

    app.dependency_overrides[get_session] = _override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user_id(session: AsyncSession) -> uuid.UUID:
    user_id = uuid.uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    return user_id


@pytest.mark.asyncio
async def test_garmin_connection_different_account_returns_409(
    session: AsyncSession, test_user_id: uuid.UUID, authed_client: AsyncClient
) -> None:
    await _insert_garmin_connection(session, test_user_id, "old@garmin.com")
    await session.commit()

    with patch.object(connections_module.GarminClient, "login") as mock_login:
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "new@garmin.com", "password": "pw", "mfa_token": None},
        )

    assert resp.status_code == 409
    assert resp.json() == {"detail": "different_garmin_account_already_connected"}
    # a doomed request must never spend any of Garmin's rate-limited login budget
    mock_login.assert_not_called()


@pytest.mark.asyncio
async def test_garmin_connection_different_account_blocked_regardless_of_status(
    session: AsyncSession, test_user_id: uuid.UUID, authed_client: AsyncClient
) -> None:
    # even a disabled/reauth_required old connection still counts -- health data for
    # that account may already exist regardless of the connection's current status
    await _insert_garmin_connection(session, test_user_id, "old@garmin.com", status="disabled")
    await session.commit()

    with patch.object(connections_module.GarminClient, "login") as mock_login:
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "new@garmin.com", "password": "pw", "mfa_token": None},
        )

    assert resp.status_code == 409
    mock_login.assert_not_called()


@pytest.mark.asyncio
async def test_garmin_connection_same_account_reconnect_still_allowed(
    session: AsyncSession, test_user_id: uuid.UUID, authed_client: AsyncClient
) -> None:
    # a case-different but same account (e.g. "Same@Garmin.com" vs "same@garmin.com")
    # must not be treated as a different account
    await _insert_garmin_connection(
        session, test_user_id, "Same@Garmin.com", status="reauth_required"
    )
    await session.commit()

    with patch.object(
        connections_module.GarminClient, "login",
        return_value=AuthTokens(access_token="", refresh_token='{"fake":"token"}'),
    ), patch.object(connections_module, "_store_connection", new=AsyncMock()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "same@garmin.com", "password": "pw", "mfa_token": None},
        )

    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_garmin_connection_no_existing_account_allowed(
    session: AsyncSession, test_user_id: uuid.UUID, authed_client: AsyncClient
) -> None:
    with patch.object(
        connections_module.GarminClient, "login",
        return_value=AuthTokens(access_token="", refresh_token='{"fake":"token"}'),
    ), patch.object(connections_module, "_store_connection", new=AsyncMock()):
        resp = await authed_client.post(
            "/api/connections/garmin",
            json={"email": "first@garmin.com", "password": "pw", "mfa_token": None},
        )

    assert resp.status_code == 201
