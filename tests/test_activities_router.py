from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from kairos.activities.reprocess import ReprocessResult
from kairos.api import app
from kairos.ingestion.job_registry import get_registry
from kairos.routers import activities as activities_module
from kairos.routers import sync as sync_module


@pytest.fixture
def user_id(monkeypatch: pytest.MonkeyPatch) -> str:
    fixed = str(uuid4())

    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        return {"user_id": fixed} if session_id == "valid" else None

    import kairos.auth.deps as _deps

    monkeypatch.setattr(_deps, "get_session", _fake_get_session)
    return fixed


@pytest.fixture
def fake_session_factory(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    session = MagicMock()

    @asynccontextmanager
    async def _factory() -> AsyncIterator[MagicMock]:
        yield session

    monkeypatch.setattr(activities_module, "async_session_factory", _factory)
    monkeypatch.setattr(activities_module, "install_rls_listener", MagicMock())
    return session


def _result() -> ReprocessResult:
    return ReprocessResult(
        activities_total=2,
        streams_written=1,
        from_zip=1,
        from_json=0,
        no_data=["9"],
        fetch_failed=[],
        fetched=0,
        aborted_reason=None,
    )


async def _post(client: AsyncClient, body: dict[str, Any]) -> Any:
    return await client.post(
        "/api/activities/reprocess", json=body, cookies={"session_id": "valid"}
    )


@pytest.mark.asyncio
async def test_reprocess_without_refetch_never_builds_garmin_client(
    user_id: str, fake_session_factory: MagicMock
) -> None:
    build = AsyncMock(return_value=(object(), None))
    reprocess = AsyncMock(return_value=_result())
    with (
        patch.object(activities_module, "_build_garmin_client", build),
        patch.object(activities_module, "reprocess_activities", reprocess),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await _post(client, {"from_date": "2026-08-01", "activity_ids": [5]})
            status = await client.get("/api/sync/status", cookies={"session_id": "valid"})

    assert resp.status_code == 202
    job = resp.json()["job"]
    assert (job["connector"], job["kind"]) == ("garmin", "reprocess")
    build.assert_not_awaited()
    kwargs = reprocess.await_args.kwargs
    assert kwargs["garmin"] is None
    assert kwargs["refetch_fit"] is False
    assert kwargs["activity_ids"] == [5]
    assert str(kwargs["from_date"]) == "2026-08-01"
    assert kwargs["to_date"] is None
    listed = [j for j in status.json()["jobs"] if j["job_id"] == job["job_id"]]
    assert listed[0]["status"] == "done"
    assert listed[0]["result"]["no_data"] == ["9"]
    registry = get_registry()
    assert not any(
        registry.is_locked(UUID(user_id), "garmin", k)
        for k in ("activity_list", "activity_fit", "reprocess")
    )


@pytest.mark.asyncio
async def test_reprocess_with_refetch_builds_one_client(
    user_id: str, fake_session_factory: MagicMock
) -> None:
    garmin = object()
    build = AsyncMock(return_value=(garmin, None))
    reprocess = AsyncMock(return_value=_result())
    with (
        patch.object(activities_module, "_build_garmin_client", build),
        patch.object(activities_module, "reprocess_activities", reprocess),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await _post(client, {"refetch_fit": True})

    assert resp.status_code == 202
    build.assert_awaited_once_with(fake_session_factory, UUID(user_id))
    assert reprocess.await_args.kwargs["garmin"] is garmin
    assert reprocess.await_args.kwargs["pause_s"] == 2.0


@pytest.mark.asyncio
async def test_reprocess_job_fails_when_garmin_client_unavailable(
    user_id: str, fake_session_factory: MagicMock
) -> None:
    reprocess = AsyncMock(return_value=_result())
    build = AsyncMock(return_value=(None, "x"))
    with (
        patch.object(activities_module, "_build_garmin_client", build),
        patch.object(activities_module, "reprocess_activities", reprocess),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            resp = await _post(client, {"refetch_fit": True})
            status = await client.get("/api/sync/status", cookies={"session_id": "valid"})

    reprocess.assert_not_awaited()
    job = [j for j in status.json()["jobs"] if j["job_id"] == resp.json()["job"]["job_id"]][0]
    assert (job["status"], job["error"]) == ("failed", "x")


@pytest.mark.asyncio
async def test_reprocess_rejected_inside_backfill_cooldown(user_id: str) -> None:
    with (
        patch.object(sync_module, "_run_backfill_task", new=AsyncMock()),
        patch.object(activities_module, "_run_reprocess_task", new=AsyncMock()) as task,
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            backfill = await client.post(
                "/api/sync/garmin/backfill",
                json={"kinds": ["hr_intraday"]},
                cookies={"session_id": "valid"},
            )
            resp = await _post(client, {})

    assert backfill.status_code == 202
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
    task.assert_not_awaited()


@pytest.mark.asyncio
async def test_reprocess_sets_cooldown_for_backfill(user_id: str) -> None:
    with (
        patch.object(sync_module, "_run_backfill_task", new=AsyncMock()),
        patch.object(activities_module, "_run_reprocess_task", new=AsyncMock()),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
            first = await _post(client, {})
            backfill = await client.post(
                "/api/sync/garmin/backfill",
                json={"kinds": ["hr_intraday"]},
                cookies={"session_id": "valid"},
            )

    assert first.status_code == 202
    assert backfill.status_code == 429


@pytest.mark.asyncio
async def test_reprocess_conflicts_with_running_activity_fit(user_id: str) -> None:
    lock = get_registry().get_lock(UUID(user_id), "garmin", "activity_fit")
    await lock.acquire()
    try:
        with patch.object(activities_module, "_run_reprocess_task", new=AsyncMock()) as task:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://t"
            ) as client:
                resp = await _post(client, {})
    finally:
        lock.release()

    assert resp.status_code == 409
    task.assert_not_awaited()
