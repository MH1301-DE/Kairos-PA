import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.api import app
from kairos.auth import google as google_auth
from kairos.db import models


class _MemoryRedis:
    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> bool:
        del ex
        self._data[key] = value
        return True

    async def get(self, key: str) -> str | None:
        return self._data.get(key)

    async def getdel(self, key: str) -> str | None:
        value = self._data.get(key)
        if key in self._data:
            del self._data[key]
        return value

    async def delete(self, key: str) -> int:
        existed = key in self._data
        if existed:
            del self._data[key]
        return 1 if existed else 0


@pytest.fixture(autouse=True)
async def fresh_redis() -> None:
    """Reset the module-level Redis singleton so each test gets a fresh
    connection on its own loop."""
    if _sess._redis is not None:
        await _sess._redis.aclose()
        _sess._redis = None
    yield
    if _sess._redis is not None:
        await _sess._redis.aclose()
        _sess._redis = None


@pytest.fixture(autouse=True)
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    redis_stub = _MemoryRedis()
    monkeypatch.setattr(google_auth, "get_redis", lambda: redis_stub)


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


@pytest.mark.asyncio
async def test_callback_redirects_to_frontend_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Set up a valid state in Redis
    redis_stub = google_auth.get_redis()
    state = "valid-test-state"
    await redis_stub.set(f"oauth_state:{state}", "1", ex=600)

    # Mock httpx.AsyncClient responses for token and userinfo
    mock_token_resp = AsyncMock()
    mock_token_resp.json = lambda: {"access_token": "test-token"}
    mock_token_resp.raise_for_status = lambda: None

    mock_info_resp = AsyncMock()
    mock_info_resp.json = lambda: {
        "sub": "google-sub-123",
        "email": "test@example.com",
        "name": "Test User",
    }
    mock_info_resp.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_token_resp)
    mock_client.get = AsyncMock(return_value=mock_info_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(google_auth, "httpx", AsyncMock(AsyncClient=lambda: mock_client))

    # Mock database session
    mock_user = MagicMock(spec=models.AppUser)
    mock_user.id = 123
    mock_user.email = "test@example.com"
    mock_user.google_sub = "google-sub-123"

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock()
    mock_db.execute.return_value.scalar_one_or_none = lambda: None  # New user
    mock_db.add = MagicMock()
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)

    monkeypatch.setattr(google_auth, "async_session_factory", lambda: mock_db)

    # Mock session creation
    monkeypatch.setattr(google_auth, "create_session", AsyncMock(return_value="test-session-id"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/auth/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/"
    assert "session_id" in response.cookies

    # Verify cookie security attributes via Set-Cookie header
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "max-age=2592000" in set_cookie
    # secure flag should NOT be present since is_dev=True (development mode)
    assert "secure" not in set_cookie


@pytest.mark.asyncio
async def test_logout_redirects_to_root_and_clears_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_stub = google_auth.get_redis()
    # create_session/delete_session resolve get_redis through their own module
    monkeypatch.setattr(_sess, "get_redis", lambda: redis_stub)

    session_id = await _sess.create_session(uuid.uuid4(), "logout@example.com")
    assert await _sess.get_session(session_id) is not None

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/auth/logout",
            cookies={"session_id": session_id},
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/"

    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "session_id=" in set_cookie
    assert "max-age=0" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    # secure flag should NOT be present since is_dev=True (development mode)
    assert "secure" not in set_cookie

    assert await _sess.get_session(session_id) is None
    assert f"session:{session_id}" not in redis_stub._data
