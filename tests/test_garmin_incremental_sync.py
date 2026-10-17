from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kairos.connectors.types import Window
from kairos.ingestion import garmin_sync
from kairos.ingestion.garmin_sync import GarminSyncPlan, incremental_plan, sync_garmin
from kairos.ingestion.job_registry import (
    SyncCooldown,
    SyncJobRegistry,
    acquire_trigger,
)
from kairos.ingestion.service import BackfillResult
from tests.test_backfill_cursor import StubConnector, StubSyncStateRepo, _service

_NOW = datetime(2026, 10, 15, 8, 0, tzinfo=UTC)
_TODAY = datetime(2026, 10, 15, tzinfo=UTC)
_TOMORROW = _TODAY + timedelta(days=1)


async def _plan(repo: StubSyncStateRepo, now: datetime = _NOW) -> GarminSyncPlan:
    return await incremental_plan(repo, uuid4(), ["sleep"], now)


@pytest.mark.asyncio
async def test_plan_starts_one_day_before_complete_to_and_ends_tomorrow() -> None:
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2025, 1, 1, tzinfo=UTC)
    repo.complete_to = datetime(2026, 10, 12, tzinfo=UTC)

    plan = await _plan(repo)

    assert plan.respect_coverage is False
    assert plan.ranges["sleep"] == (datetime(2026, 10, 11, tzinfo=UTC), _TOMORROW)


@pytest.mark.asyncio
async def test_plan_for_never_synced_kind_covers_yesterday_and_today() -> None:
    plan = await _plan(StubSyncStateRepo())
    assert plan.ranges["sleep"] == (_TODAY - timedelta(days=1), _TOMORROW)


@pytest.mark.asyncio
async def test_second_run_on_the_same_day_fetches_today() -> None:
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2025, 1, 1, tzinfo=UTC)
    repo.complete_to = datetime(2026, 10, 14, tzinfo=UTC)
    service = _service(repo)

    for hour in (8, 10):
        connector = StubConnector()
        plan = await _plan(repo, _NOW.replace(hour=hour))
        start, end = plan.ranges["sleep"]
        await service.run_incremental(
            connector=connector, user_id=uuid4(), kind="sleep", from_date=start, to_date=end
        )
        # run_backfill would skip the second run entirely: [complete_from, complete_to] covers it
        assert Window(start=_TODAY, end=_TOMORROW) in connector.windows

    assert repo.complete_to == _TOMORROW


@pytest.mark.asyncio
async def test_incremental_run_ignores_coverage_and_stored_cursor() -> None:
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2026, 10, 1, tzinfo=UTC)
    repo.complete_to = _TOMORROW
    repo.cursor = datetime(2026, 10, 5, tzinfo=UTC)
    connector = StubConnector()

    result = await _service(repo).run_incremental(
        connector=connector,
        user_id=uuid4(),
        kind="sleep",
        from_date=_TODAY - timedelta(days=1),
        to_date=_TOMORROW,
    )

    assert result == BackfillResult(2, True, None, fetched_from=_TODAY - timedelta(days=1))
    assert len(connector.windows) == 2
    assert repo.cursor_updates == []


@pytest.mark.asyncio
async def test_failed_incremental_run_marks_nothing_as_covered() -> None:
    repo = StubSyncStateRepo()
    repo.complete_from = datetime(2026, 1, 1, tzinfo=UTC)
    repo.complete_to = datetime(2026, 10, 10, tzinfo=UTC)

    class FailingConnector(StubConnector):
        def fetch(self, user_id: Any, kind: str, window: Window) -> Any:
            if window.start < datetime(2026, 10, 12, tzinfo=UTC):
                raise RuntimeError("garmin down")
            return super().fetch(user_id, kind, window)

    with pytest.raises(RuntimeError):
        await _service(repo).run_incremental(
            connector=FailingConnector(),
            user_id=uuid4(),
            kind="sleep",
            from_date=datetime(2026, 10, 9, tzinfo=UTC),
            to_date=_TOMORROW,
        )

    assert repo.complete_updates == []
    assert repo.complete_to == datetime(2026, 10, 10, tzinfo=UTC)


def test_button_and_scheduler_share_the_cooldown() -> None:
    registry = SyncJobRegistry()
    user_id = uuid4()
    acquire_trigger(registry, user_id, "garmin", 300)

    with pytest.raises(SyncCooldown) as exc:
        acquire_trigger(registry, user_id, "garmin", 300)

    assert 0 < exc.value.retry_after_s <= 301
    # another connector or user is unaffected
    acquire_trigger(registry, user_id, "google_calendar", 60)
    acquire_trigger(registry, uuid4(), "garmin", 300)


def test_prune_drops_finished_jobs_older_than_a_day() -> None:
    registry = SyncJobRegistry()
    user_id = uuid4()
    old, running = registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=["sleep", "hrv"], from_date="", to_date=""
    )
    old.finished_at = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    running.started_at = old.finished_at

    (fresh,) = registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=["stress"], from_date="", to_date=""
    )

    assert registry.get_jobs_for_user(user_id) == [running, fresh]


@pytest.fixture
def harness() -> Iterator[SimpleNamespace]:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    service = MagicMock()
    service.run_incremental = AsyncMock(return_value=BackfillResult(2, True, None, _TODAY))
    service.run_backfill = AsyncMock(return_value=BackfillResult(1, True, None, _TODAY))
    with (
        patch.object(garmin_sync, "_build_garmin_client", AsyncMock(return_value=(object(), None))),
        patch.object(garmin_sync, "GarminConnector"),
        patch.object(garmin_sync, "SyncService", return_value=service),
        patch.object(garmin_sync, "recompute_daily_tables", AsyncMock()),
    ):
        yield SimpleNamespace(session=session, service=service)


def _jobs(registry: SyncJobRegistry, user_id: Any, kinds: list[str]) -> Any:
    return registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=kinds, from_date="", to_date=""
    )


@pytest.mark.asyncio
async def test_sync_garmin_skips_locked_kind_and_runs_the_rest(harness: SimpleNamespace) -> None:
    registry = SyncJobRegistry()
    user_id = uuid4()
    jobs = _jobs(registry, user_id, ["sleep", "hrv"])
    plan = GarminSyncPlan(
        kinds=["sleep", "hrv"],
        ranges={k: (_TODAY - timedelta(days=1), _TOMORROW) for k in ("sleep", "hrv")},
        respect_coverage=False,
    )

    async with registry.get_lock(user_id, "garmin", "sleep"):
        result = await sync_garmin(harness.session, user_id, plan, registry=registry, jobs=jobs)

    assert result["kinds"]["sleep"]["status"] == "skipped"
    assert result["kinds"]["sleep"]["error_code"] == "busy"
    assert result["kinds"]["hrv"]["status"] == "done"
    assert result["kinds"]["hrv"]["from"] == "2026-10-14"
    assert result["recomputed_from"] == _TODAY.date()
    harness.service.run_incremental.assert_awaited_once()
    harness.service.run_backfill.assert_not_awaited()


@pytest.mark.asyncio
async def test_sync_garmin_failure_stores_a_fixed_message(harness: SimpleNamespace) -> None:
    harness.service.run_incremental.side_effect = RuntimeError("secret upstream text")
    registry = SyncJobRegistry()
    user_id = uuid4()
    jobs = _jobs(registry, user_id, ["sleep"])
    plan = GarminSyncPlan(["sleep"], {"sleep": (_TODAY, _TOMORROW)}, respect_coverage=False)

    result = await sync_garmin(harness.session, user_id, plan, registry=registry, jobs=jobs)

    assert jobs[0].status == "failed"
    assert jobs[0].error == garmin_sync.SYNC_FAILED_MESSAGE
    assert result["kinds"]["sleep"]["error_code"] == "sync_failed"
    assert result["recomputed_from"] is None


@pytest.mark.asyncio
async def test_sync_garmin_reports_reauth_required(harness: SimpleNamespace) -> None:
    registry = SyncJobRegistry()
    user_id = uuid4()
    jobs = _jobs(registry, user_id, ["sleep"])
    plan = GarminSyncPlan(["sleep"], {"sleep": (_TODAY, _TOMORROW)}, respect_coverage=True)

    with patch.object(
        garmin_sync,
        "_build_garmin_client",
        AsyncMock(return_value=(None, garmin_sync.REAUTH_MESSAGE)),
    ):
        result = await sync_garmin(harness.session, user_id, plan, registry=registry, jobs=jobs)

    assert result["error_code"] == "reauth_required"
    assert jobs[0].error == garmin_sync.REAUTH_MESSAGE


@pytest.mark.asyncio
async def test_scheduler_trigger_blocks_the_button(monkeypatch: pytest.MonkeyPatch) -> None:
    from httpx import ASGITransport, AsyncClient

    import kairos.auth.deps as deps
    from kairos.api import app
    from kairos.ingestion.job_registry import get_registry
    from kairos.routers import sync as sync_module

    user_id = uuid4()

    async def _session(session_id: str) -> dict[str, str] | None:
        return {"user_id": str(user_id)} if session_id == "valid" else None

    monkeypatch.setattr(deps, "get_session", _session)
    acquire_trigger(get_registry(), user_id, "garmin", garmin_sync.GARMIN_COOLDOWN_SECONDS)

    with patch.object(sync_module, "_run_backfill_task", new=AsyncMock()) as task:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            c.cookies.set("session_id", "valid")
            resp = await c.post("/api/sync/garmin/backfill", json={"kinds": ["sleep"]})

    assert resp.status_code == 429
    assert int(resp.headers["Retry-After"]) > 0
    task.assert_not_called()
