from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from kairos.api import app
from kairos.routers import sync as sync_module


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        if session_id == "valid":
            return {"user_id": str(uuid4())}
        return None

    import kairos.auth.deps as _deps

    monkeypatch.setattr(_deps, "get_session", _fake_get_session)


@pytest.mark.asyncio
async def test_google_calendar_sync_returns_202_and_job() -> None:
    transport = ASGITransport(app=app)
    with patch.object(sync_module, "_run_calendar_sync_task", new=AsyncMock()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/sync/google_calendar/sync",
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 202
    body = resp.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["connector"] == "google_calendar"
    assert body["jobs"][0]["kind"] == "events"


@pytest.mark.asyncio
async def test_google_calendar_sync_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/sync/google_calendar/sync")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_garmin_backfill_returns_windows_total_for_ui_progress() -> None:
    """windows_total lets the UI show windows_processed as a percentage --
    regression test for a live UX bug report (backfill gave no progress
    indicator, and the trigger button never re-disabled itself)."""
    transport = ASGITransport(app=app)
    with patch.object(sync_module, "_run_backfill_task", new=AsyncMock()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/sync/garmin/backfill",
                json={"from_date": "2026-08-01", "to_date": "2026-08-11", "kinds": ["hr_intraday"]},
                cookies={"session_id": "valid"},
            )
    assert resp.status_code == 202
    body = resp.json()
    assert len(body["jobs"]) == 1
    job = body["jobs"][0]
    assert job["kind"] == "hr_intraday"
    assert job["windows_total"] == 10  # 10 daily windows between the two dates
    assert job["windows_processed"] == 0


@pytest.mark.asyncio
async def test_google_calendar_sync_has_no_windows_total() -> None:
    """google_calendar's single-fetch sync has no meaningful window count."""
    transport = ASGITransport(app=app)
    with patch.object(sync_module, "_run_calendar_sync_task", new=AsyncMock()):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/sync/google_calendar/sync",
                cookies={"session_id": "valid"},
            )
    assert resp.json()["jobs"][0]["windows_total"] is None
