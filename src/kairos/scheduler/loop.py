"""In-process scheduler loop, started from the FastAPI lifespan (spec 7, ADR-0007).

Assumes exactly one API process: the sync locks and cooldowns it shares with the buttons
live in this process's memory, and runs still "running" at start-up count as interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from uuid import UUID

from kairos.config import settings
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.job_registry import SyncJobRegistry
from kairos.scheduler.actions import ACTIONS
from kairos.scheduler.repository import (
    DueJob,
    ScheduledJobRepository,
    due_jobs,
    mark_interrupted,
)
from kairos.scheduler.runner import compute_next_run, run_job
from kairos.scheduler.types import ActionSpec

logger = logging.getLogger(__name__)

DUE_BATCH = 20
# migrations run as their own service before the API, connections need a moment
FIRST_TICK_DELAY_S = 15.0


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SchedulerLoop:
    def __init__(
        self,
        *,
        registry: SyncJobRegistry,
        actions: Mapping[str, ActionSpec] = ACTIONS,
        now: Callable[[], datetime] = _utcnow,
        tick_seconds: float | None = None,
        max_parallel: int | None = None,
    ) -> None:
        self._registry = registry
        self._actions = actions
        self._now = now
        self._tick_s = tick_seconds or settings.scheduler_tick_seconds
        self._max_parallel = max_parallel or settings.scheduler_max_parallel_runs
        # users with a run in progress: their further due jobs wait for the next tick
        self._active_users: set[UUID] = set()
        self._running: dict[UUID, asyncio.Task[str]] = {}
        self._owner: dict[UUID, UUID] = {}
        self._loop_task: asyncio.Task[None] | None = None

    @property
    def running_jobs(self) -> set[UUID]:
        return set(self._running)

    async def start(self) -> None:
        workers = os.environ.get("WEB_CONCURRENCY", "1")
        if workers.isdigit() and int(workers) > 1:
            logger.warning(
                "WEB_CONCURRENCY=%s: the in-process scheduler runs once per worker, "
                "its locks do not span processes -- use a single worker (ADR-0007)",
                workers,
            )
        async with async_session_factory() as session:
            interrupted = await mark_interrupted(session, self._now())
            await session.commit()
        if interrupted:
            logger.warning("Marked %d scheduled run(s) as interrupted", len(interrupted))
        self._loop_task = asyncio.create_task(self.run_forever())

    async def stop(self) -> None:
        if self._loop_task is not None:
            self._loop_task.cancel()
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if tasks:
            try:
                async with async_session_factory() as session:
                    await mark_interrupted(session, self._now())
                    await session.commit()
            except Exception:
                logger.warning("Could not mark cancelled runs as interrupted", exc_info=True)

    async def run_forever(self) -> None:
        await asyncio.sleep(FIRST_TICK_DELAY_S)
        while True:
            try:
                await self.tick()
            except Exception:
                logger.exception("Scheduler tick failed")
            await asyncio.sleep(self._tick_s)

    async def tick(self, now: datetime | None = None) -> list[asyncio.Task[str]]:
        now = now or self._now()
        async with async_session_factory() as session:
            due = await due_jobs(session, now, DUE_BATCH)
        started: list[asyncio.Task[str]] = []
        for item in due:
            if item.user_id in self._active_users:
                continue
            if len(self._running) >= self._max_parallel:
                break
            run_id = await self._claim(item, now)
            if run_id is not None:
                started.append(self._spawn(item.user_id, item.job_id, run_id))
        return started

    async def run_now(self, user_id: UUID, job_id: UUID) -> UUID | None:
        """Manual run: does not touch next_run_at; None if the job is already running."""
        async with async_session_factory() as session:
            install_rls_listener(session, user_id)
            claimed = await ScheduledJobRepository(session).start_manual(job_id, self._now())
            if claimed is None:
                return None
            await session.commit()
        run_id = claimed[1].id
        self._spawn(user_id, job_id, run_id)
        return run_id

    async def _claim(self, item: DueJob, now: datetime) -> UUID | None:
        async with async_session_factory() as session:
            install_rls_listener(session, item.user_id)
            claimed = await ScheduledJobRepository(session).claim(
                item.job_id,
                now,
                next_run=lambda job: compute_next_run(job.cron_exprs, job.timezone, now),
                catch_up_after=timedelta(seconds=2 * self._tick_s),
            )
            if claimed is None:
                return None
            await session.commit()
            return claimed[1].id

    def _spawn(self, user_id: UUID, job_id: UUID, run_id: UUID) -> asyncio.Task[str]:
        self._active_users.add(user_id)
        task = asyncio.create_task(
            run_job(
                job_id=job_id,
                run_id=run_id,
                user_id=user_id,
                registry=self._registry,
                actions=self._actions,
                now=self._now,
            )
        )
        self._running[job_id] = task

        self._owner[job_id] = user_id

        def _done(_: asyncio.Task[str]) -> None:
            self._running.pop(job_id, None)
            self._owner.pop(job_id, None)
            if user_id not in self._owner.values():
                self._active_users.discard(user_id)

        task.add_done_callback(_done)
        return task


_scheduler: SchedulerLoop | None = None


def get_scheduler(registry: SyncJobRegistry) -> SchedulerLoop:
    # without a lifespan (tests) a non-ticking instance still serves manual runs
    global _scheduler
    if _scheduler is None:
        _scheduler = SchedulerLoop(registry=registry)
    return _scheduler


def set_scheduler(loop: SchedulerLoop | None) -> None:
    global _scheduler
    _scheduler = loop
