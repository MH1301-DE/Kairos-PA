from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.ingestion.job_registry import SyncJobRegistry, acquire_trigger
from kairos.scheduler import actions as actions_module
from kairos.scheduler import loop as loop_module
from kairos.scheduler import runner as runner_module
from kairos.scheduler.actions import ACTIONS
from kairos.scheduler.loop import SchedulerLoop
from kairos.scheduler.repository import ScheduledJobRepository
from kairos.scheduler.runner import derive_status, run_job
from kairos.scheduler.types import (
    ActionContext,
    ActionFailed,
    ActionSkipped,
    ActionSpec,
    StepOutcome,
)

# Thursday 08:00 in Berlin
_NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)


class _NoParams(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def _spec(name: str, behaviour: str, calls: list[str], timeout_s: float = 5) -> ActionSpec:
    async def run(ctx: ActionContext, params: Any) -> StepOutcome:
        calls.append(name)
        if behaviour == "skip":
            raise ActionSkipped("übersprungen")
        if behaviour == "fail":
            raise ActionFailed("boom", "kaputt")
        if behaviour == "sleep":
            await asyncio.sleep(10)
        if behaviour == "crash":
            raise RuntimeError("secret upstream text")
        return StepOutcome(summary=f"{name} ok", data={"previous": len(ctx.previous)})

    return ActionSpec(name, name, "", _NoParams, timeout_s, 60, run)


def _registry(calls: list[str]) -> dict[str, ActionSpec]:
    return {
        "ok": _spec("ok", "ok", calls),
        "skip": _spec("skip", "skip", calls),
        "fail": _spec("fail", "fail", calls),
        "sleep": _spec("sleep", "sleep", calls, timeout_s=0.05),
        "crash": _spec("crash", "crash", calls),
    }


@pytest_asyncio.fixture
async def factory(
    db_url: str, run_migrations: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del run_migrations
    engine = create_async_engine(db_url)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    originals = (
        runner_module.async_session_factory,
        loop_module.async_session_factory,
        actions_module.async_session_factory,
    )
    runner_module.async_session_factory = maker  # type: ignore[assignment]
    loop_module.async_session_factory = maker  # type: ignore[assignment]
    actions_module.async_session_factory = maker  # type: ignore[assignment]
    yield maker
    (
        runner_module.async_session_factory,
        loop_module.async_session_factory,
        actions_module.async_session_factory,
    ) = originals
    await engine.dispose()


async def _user(session: AsyncSession) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    return user_id


async def _job(session: AsyncSession, user_id: UUID, steps: list[str], **fields: Any) -> UUID:
    values: dict[str, Any] = {
        "user_id": user_id,
        "name": "Job",
        "cron_exprs": ["0 8 * * *"],
        "timezone": "Europe/Berlin",
        "steps": [{"action": s, "params": {}} for s in steps],
        "next_run_at": _NOW,
    }
    values.update(fields)
    job = await ScheduledJobRepository(session).create(**values)
    await session.commit()
    return job.id


async def _claim(session: AsyncSession, job_id: UUID, now: datetime = _NOW) -> UUID:
    claimed = await ScheduledJobRepository(session).claim(
        job_id, now, next_run=lambda _: now + timedelta(days=1), catch_up_after=timedelta(minutes=1)
    )
    assert claimed is not None
    await session.commit()
    return claimed[1].id


async def _load(factory: async_sessionmaker[AsyncSession], job_id: UUID) -> tuple[Any, list[Any]]:
    async with factory() as s:
        repo = ScheduledJobRepository(s)
        return await repo.get(job_id), await repo.list_runs(job_id, 50)


def test_derive_status() -> None:
    assert derive_status([{"status": "ok"}, {"status": "skipped"}]) == ("ok", None)
    assert derive_status([{"status": "skipped"}, {"status": "skipped"}]) == (
        "skipped",
        "all_steps_skipped",
    )
    assert derive_status([{"status": "ok"}, {"status": "failed"}, {"status": "not_run"}]) == (
        "failed",
        None,
    )


@pytest.mark.asyncio
async def test_skip_continues_and_failure_aborts_the_chain(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    job_id = await _job(session, user_id, ["skip", "ok", "fail", "ok"])
    run_id = await _claim(session, job_id)

    status = await run_job(
        job_id=job_id,
        run_id=run_id,
        user_id=user_id,
        registry=SyncJobRegistry(),
        actions=_registry(calls),
        now=_Clock(_NOW),
    )

    assert status == "failed"
    assert calls == ["skip", "ok", "fail"]
    job, runs = await _load(factory, job_id)
    steps = runs[0].steps
    assert [s["status"] for s in steps] == ["skipped", "ok", "failed", "not_run"]
    assert steps[1]["data"] == {"previous": 1}
    assert steps[2]["error_code"] == "boom" and steps[2]["summary"] == "kaputt"
    assert runs[0].status == "failed" and runs[0].finished_at is not None
    assert job.running_since is None and job.last_status == "failed"
    assert job.consecutive_failures == 1 and job.last_success_at is None


@pytest.mark.asyncio
async def test_all_skipped_is_a_skipped_run_and_ok_resets_failures(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    job_id = await _job(session, user_id, ["skip"], consecutive_failures=3)
    run_id = await _claim(session, job_id)
    await run_job(
        job_id=job_id,
        run_id=run_id,
        user_id=user_id,
        registry=SyncJobRegistry(),
        actions=_registry(calls),
        now=_Clock(_NOW),
    )
    job, runs = await _load(factory, job_id)
    assert runs[0].status == "skipped" and runs[0].skip_reason == "all_steps_skipped"
    assert job.consecutive_failures == 3

    async with factory() as s:
        await s.execute(
            text(
                "UPDATE scheduled_job SET steps = CAST(:s AS jsonb), next_run_at = :n WHERE id = :j"
            ),
            {"s": '[{"action": "ok", "params": {}}]', "n": _NOW, "j": str(job_id)},
        )
        await s.commit()
        run_id = await _claim(s, job_id)
    await run_job(
        job_id=job_id,
        run_id=run_id,
        user_id=user_id,
        registry=SyncJobRegistry(),
        actions=_registry(calls),
        now=_Clock(_NOW + timedelta(minutes=1)),
    )
    job, _ = await _load(factory, job_id)
    assert job.consecutive_failures == 0 and job.last_success_at is not None


@pytest.mark.asyncio
async def test_timeout_crash_unknown_and_invalid_params_fail_with_fixed_codes(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    for action, params, code in (
        ("sleep", {}, "timeout"),
        ("crash", {}, "unexpected"),
        ("nope", {}, "unknown_action"),
        ("ok", {"unexpected": 1}, "invalid_params"),
    ):
        job_id = await _job(session, user_id, [action])
        async with factory() as s:
            await s.execute(
                text("UPDATE scheduled_job SET steps = CAST(:s AS jsonb) WHERE id = :j"),
                {
                    "s": json.dumps([{"action": action, "params": params}]),
                    "j": str(job_id),
                },
            )
            await s.commit()
            run_id = await _claim(s, job_id)
        await run_job(
            job_id=job_id,
            run_id=run_id,
            user_id=user_id,
            registry=SyncJobRegistry(),
            actions=_registry([]),
            now=_Clock(_NOW),
        )
        _, runs = await _load(factory, job_id)
        step = runs[0].steps[0]
        assert (step["status"], step["error_code"]) == ("failed", code)
        assert "secret" not in str(step)


@pytest.mark.asyncio
async def test_overlap_records_a_skipped_run_and_moves_next_run_at(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    job_id = await _job(session, user_id, ["ok"], cron_exprs=["*/15 * * * *"])
    async with factory() as s:
        claimed = await ScheduledJobRepository(s).claim(
            job_id,
            _NOW,
            next_run=lambda _: _NOW + timedelta(minutes=15),
            catch_up_after=timedelta(minutes=1),
        )
        assert claimed is not None
        await s.commit()
    # the run ends after 40 minutes: the 06:15 and 06:30 occurrences came due meanwhile
    end = _Clock(_NOW + timedelta(minutes=40))
    await run_job(
        job_id=job_id,
        run_id=claimed[1].id,
        user_id=user_id,
        registry=SyncJobRegistry(),
        actions=_registry([]),
        now=end,
    )
    job, runs = await _load(factory, job_id)
    assert [r.status for r in runs] == ["skipped", "ok"]
    assert runs[0].skip_reason == "overlap"
    assert job.next_run_at == _NOW + timedelta(minutes=45)


@pytest.mark.asyncio
async def test_cooldown_in_a_real_action_is_skipped_not_failed(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    # seam AP 1 <-> AP 4: the shared cooldown surfaces as skipped and the chain goes on
    user_id = await _user(session)
    calls: list[str] = []
    registry = SyncJobRegistry()
    acquire_trigger(registry, user_id, "garmin", 300)
    job_id = await _job(session, user_id, ["garmin.sync", "ok"])
    run_id = await _claim(session, job_id)
    status = await run_job(
        job_id=job_id,
        run_id=run_id,
        user_id=user_id,
        registry=registry,
        actions={**ACTIONS, **_registry(calls)},
        now=_Clock(_NOW),
    )
    _, runs = await _load(factory, job_id)
    assert status == "ok"
    assert [s["status"] for s in runs[0].steps] == ["skipped", "ok"]
    assert runs[0].steps[0]["summary"] == "Garmin wurde gerade erst synchronisiert"


@pytest.mark.asyncio
async def test_lock_in_a_real_action_is_skipped_not_failed(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    registry = SyncJobRegistry()
    job_id = await _job(session, user_id, ["calendar.sync"])
    async with factory() as s:
        await s.execute(
            text("UPDATE scheduled_job SET steps = CAST(:s AS jsonb) WHERE id = :j"),
            {"s": '[{"action": "calendar.sync", "params": {}}]', "j": str(job_id)},
        )
        await s.commit()
        run_id = await _claim(s, job_id)
    from kairos.ingestion.job_registry import get_registry

    async with get_registry().get_lock(user_id, "google_calendar", "events"):
        status = await run_job(
            job_id=job_id,
            run_id=run_id,
            user_id=user_id,
            registry=registry,
            actions=ACTIONS,
            now=_Clock(_NOW),
        )
    _, runs = await _load(factory, job_id)
    assert status == "skipped"
    assert runs[0].steps[0]["summary"] == "Kalender-Sync läuft bereits"


# --- loop -----------------------------------------------------------------------------


async def _only(session: AsyncSession, *user_ids: UUID) -> None:
    # the container is shared across tests: keep other tests' due jobs out of the tick
    await session.execute(
        text("UPDATE scheduled_job SET enabled = false WHERE NOT (user_id = ANY(:ids))"),
        {"ids": list(user_ids)},
    )
    await session.commit()


def _loop(clock: _Clock, calls: list[str], max_parallel: int = 2) -> SchedulerLoop:
    return SchedulerLoop(
        registry=SyncJobRegistry(),
        actions=_registry(calls),
        now=clock,
        tick_seconds=30,
        max_parallel=max_parallel,
    )


@pytest.mark.asyncio
async def test_tick_runs_a_due_job_and_schedules_the_next_occurrence(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    job_id = await _job(session, user_id, ["ok"])
    await _only(session, user_id)
    clock = _Clock(_NOW + timedelta(seconds=10))
    tasks = await _loop(clock, calls).tick()
    assert await asyncio.gather(*tasks) == ["ok"]
    job, runs = await _load(factory, job_id)
    assert runs[0].trigger == "schedule" and runs[0].scheduled_for == _NOW
    assert job.next_run_at == _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_missed_runs_are_caught_up_exactly_once(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    # three days of missed 08:00 runs
    job_id = await _job(session, user_id, ["ok"], next_run_at=_NOW - timedelta(days=3))
    await _only(session, user_id)
    clock = _Clock(_NOW + timedelta(hours=2))
    loop = _loop(clock, calls)
    await asyncio.gather(*await loop.tick())
    assert await loop.tick() == []
    job, runs = await _load(factory, job_id)
    assert [r.trigger for r in runs] == ["catch_up"]
    assert job.next_run_at == _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_restart_marks_running_runs_interrupted_then_catches_up_once(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    job_id = await _job(session, user_id, ["ok"])
    await _only(session, user_id)
    async with factory() as s:
        claimed = await ScheduledJobRepository(s).claim(
            job_id,
            _NOW,
            next_run=lambda _: _NOW + timedelta(minutes=30),
            catch_up_after=timedelta(minutes=1),
        )
        assert claimed is not None
        await s.commit()
    # process died mid-run; it restarts two hours later
    clock = _Clock(_NOW + timedelta(hours=2))
    loop = _loop(clock, calls)
    await loop.start()
    await asyncio.gather(*await loop.tick())
    await loop.stop()

    job, runs = await _load(factory, job_id)
    assert sorted(r.status for r in runs) == ["interrupted", "ok"]
    assert [r.trigger for r in runs if r.status == "ok"] == ["catch_up"]
    assert job.next_run_at == _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_one_run_per_user_at_a_time_and_parallel_limit(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_a, user_b, user_c = await _user(session), await _user(session), await _user(session)
    calls: list[str] = []
    a1 = await _job(session, user_a, ["ok"])
    a2 = await _job(session, user_a, ["ok"])
    await _job(session, user_b, ["ok"])
    await _job(session, user_c, ["ok"])
    await _only(session, user_a, user_b, user_c)
    clock = _Clock(_NOW + timedelta(seconds=5))
    loop = _loop(clock, calls, max_parallel=2)

    first = await loop.tick()
    # A's second job waits while A runs, and the parallel limit stops the tick at two
    assert len(first) == 2
    assert len(set(loop._owner.values())) == 2
    await asyncio.gather(*first)
    second = await loop.tick()
    await asyncio.gather(*second)
    third = await loop.tick()
    await asyncio.gather(*third)

    assert len(first) + len(second) + len(third) == 4
    _, runs_a1 = await _load(factory, a1)
    _, runs_a2 = await _load(factory, a2)
    assert len(runs_a1) == 1 and len(runs_a2) == 1


@pytest.mark.asyncio
async def test_run_now_is_manual_and_refuses_a_running_job(
    session: AsyncSession, factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    calls: list[str] = []
    job_id = await _job(session, user_id, ["sleep"], next_run_at=_NOW + timedelta(days=1))
    loop = _loop(_Clock(_NOW), calls)
    run_id = await loop.run_now(user_id, job_id)
    assert run_id is not None
    assert await loop.run_now(user_id, job_id) is None
    await asyncio.gather(*loop._running.values(), return_exceptions=True)
    job, runs = await _load(factory, job_id)
    assert runs[0].trigger == "manual" and runs[0].scheduled_for is None
    assert job.next_run_at == _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_start_warns_about_several_workers(
    factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("WEB_CONCURRENCY", "2")
    # alembic's fileConfig in the migration fixture disables loggers that already exist
    monkeypatch.setattr(loop_module.logger, "disabled", False)
    loop = _loop(_Clock(_NOW), [])
    with caplog.at_level("WARNING", logger="kairos.scheduler.loop"):
        await loop.start()
        await loop.stop()
    assert any("WEB_CONCURRENCY=2" in r.getMessage() for r in caplog.records)
