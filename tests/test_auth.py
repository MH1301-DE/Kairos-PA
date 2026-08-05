import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.auth import google as google_auth
from kairos.api import app


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
