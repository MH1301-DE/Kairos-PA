from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.api import app
from kairos.connectors.garmin.client import (
    AuthTokens,
    InvalidCredentials,
    NeedsMfaToken,
    UpstreamUnavailable,
)
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
async def test_garmin_connection_success_returns_201() -> None:
    transport = ASGITransport(app=app)
    with patch.object(
        connections_module.GarminClient, "login",
        return_value=AuthTokens(access_token="", refresh_token='{"fake":"token"}'),
    ), patch.object(connections_module, "_store_connection", new=AsyncMock()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 201
    assert resp.json() == {"status": "connected"}


@pytest.mark.asyncio
async def test_garmin_connection_mfa_required_returns_202() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=NeedsMfaToken()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 202
    assert resp.json() == {"status": "mfa_required"}


@pytest.mark.asyncio
async def test_garmin_connection_invalid_credentials_returns_401() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=InvalidCredentials()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "wrong", "mfa_token": None},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 401
    assert resp.json() == {"detail": "invalid_credentials"}


@pytest.mark.asyncio
async def test_garmin_connection_upstream_unavailable_returns_503() -> None:
    transport = ASGITransport(app=app)
    with patch.object(connections_module.GarminClient, "login", side_effect=UpstreamUnavailable()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/connections/garmin",
                json={"email": "a@b.com", "password": "pw", "mfa_token": None},
                cookies={"session_id": "valid"},
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
