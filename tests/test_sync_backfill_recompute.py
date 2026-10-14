from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kairos.ingestion.job_registry import SyncJobRegistry
from kairos.ingestion.service import BackfillResult
from kairos.routers import sync as sync_module

_FROM = datetime(2026, 8, 1, tzinfo=UTC)
_TO = datetime(2026, 8, 10, tzinfo=UTC)


class _FakeSessionCtx:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(self, *_: object) -> None:
        return None


@pytest.fixture
def harness() -> Iterator[SimpleNamespace]:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    recompute = SimpleNamespace(
        wellness=AsyncMock(), hr=AsyncMock(), metrics=AsyncMock(),
    )
    service = MagicMock()
    with (
        patch.object(sync_module, "async_session_factory", lambda: _FakeSessionCtx(session)),
        patch.object(sync_module, "install_rls_listener"),
        patch.object(sync_module, "_build_garmin_client", AsyncMock(return_value=(object(), None))),
        patch.object(sync_module, "GarminConnector"),
        patch.object(sync_module, "SyncService", return_value=service),
        patch.object(sync_module, "recompute_wellness_daily_stats", recompute.wellness),
        patch.object(sync_module, "recompute_hr_bucket_seconds_daily", recompute.hr),
        patch.object(sync_module, "recompute_metric_daily_values", recompute.metrics),
    ):
        yield SimpleNamespace(session=session, recompute=recompute, service=service)


async def _run(harness: SimpleNamespace, results: list[BackfillResult | Exception]) -> Any:
    registry = SyncJobRegistry()
    user_id = uuid4()
    jobs = registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=["sleep", "hrv"][: len(results)],
        from_date="2026-08-01", to_date="2026-08-10",
    )
    harness.service.run_backfill = AsyncMock(side_effect=results)
    await sync_module._run_backfill_task(
        user_id=user_id, from_dt=_FROM, to_dt=_TO, jobs=jobs, registry=registry
    )
    return jobs, user_id


@pytest.mark.asyncio
async def test_recomputes_from_earliest_fetched_window(harness: SimpleNamespace) -> None:
    results: list[BackfillResult | Exception] = [
        BackfillResult(2, True, None, fetched_from=datetime(2026, 8, 5, 12, tzinfo=UTC)),
        BackfillResult(3, True, None, fetched_from=datetime(2026, 8, 3, tzinfo=UTC)),
    ]
    jobs, user_id = await _run(harness, results)

    expected = {"user_id": user_id, "start": date(2026, 8, 3), "end": date.today()}
    for fn in (harness.recompute.wellness, harness.recompute.hr, harness.recompute.metrics):
        fn.assert_awaited_once_with(harness.session, **expected)
    assert [j.status for j in jobs] == ["done", "done"]


@pytest.mark.asyncio
async def test_no_recompute_when_nothing_fetched(harness: SimpleNamespace) -> None:
    jobs, _ = await _run(harness, [BackfillResult(0, True, None)])

    harness.recompute.wellness.assert_not_awaited()
    harness.recompute.hr.assert_not_awaited()
    harness.recompute.metrics.assert_not_awaited()
    assert jobs[0].status == "done"


@pytest.mark.asyncio
async def test_no_recompute_when_every_job_failed(harness: SimpleNamespace) -> None:
    jobs, _ = await _run(harness, [RuntimeError("boom")])

    harness.recompute.wellness.assert_not_awaited()
    assert jobs[0].status == "failed"


@pytest.mark.asyncio
async def test_recompute_failure_keeps_jobs_done(harness: SimpleNamespace) -> None:
    harness.recompute.hr.side_effect = RuntimeError("db down")
    results: list[BackfillResult | Exception] = [
        BackfillResult(1, True, None, fetched_from=datetime(2026, 8, 5, tzinfo=UTC)),
    ]
    jobs, _ = await _run(harness, results)

    assert jobs[0].status == "done"
    assert jobs[0].error is None
    harness.session.rollback.assert_awaited()
    harness.recompute.metrics.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconciled_days_extend_recompute_start(harness: SimpleNamespace) -> None:
    async def _backfill(**_: Any) -> BackfillResult:
        hook = sync_module.SyncService.call_args.kwargs["post_window"]
        envelope = SimpleNamespace(window=None, payload=[], files=())
        await hook("activity_list", envelope, 1, {})
        return BackfillResult(1, True, None, fetched_from=datetime(2026, 8, 5, tzinfo=UTC))

    marked = [(7, datetime(2026, 8, 1, 23, 0, tzinfo=UTC))]
    registry = SyncJobRegistry()
    user_id = uuid4()
    jobs = registry.create_jobs(
        user_id=user_id, connector="garmin", kinds=["activity_list"],
        from_date="2026-08-01", to_date="2026-08-10",
    )
    harness.service.run_backfill = AsyncMock(side_effect=_backfill)
    with (
        patch.object(sync_module, "reconcile_deleted_activities", AsyncMock(return_value=marked)),
        patch.object(
            sync_module, "local_days_of_activities", AsyncMock(return_value={date(2026, 8, 2)})
        ),
    ):
        await sync_module._run_backfill_task(
            user_id=user_id, from_dt=_FROM, to_dt=_TO, jobs=jobs, registry=registry
        )

    harness.recompute.hr.assert_awaited_once_with(
        harness.session, user_id=user_id, start=date(2026, 8, 2), end=date.today()
    )
