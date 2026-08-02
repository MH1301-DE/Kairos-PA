import pytest
from httpx import ASGITransport, AsyncClient
from kairos.api import app


@pytest.mark.asyncio
async def test_healthz_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
