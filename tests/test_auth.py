import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.api import app


@pytest.fixture(autouse=True)
async def fresh_redis() -> None:
    """Reset the module-level Redis singleton so each test gets a fresh connection on its own loop."""
    if _sess._redis is not None:
        await _sess._redis.aclose()
        _sess._redis = None
    yield
    if _sess._redis is not None:
        await _sess._redis.aclose()
        _sess._redis = None


@pytest.mark.asyncio
async def test_login_redirects_to_google() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]


@pytest.mark.asyncio
async def test_callback_rejects_invalid_state() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/callback?code=abc&state=invalid-state")
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_state"
