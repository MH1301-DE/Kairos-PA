"""Runs one claimed job: its steps in order, stop at the first failure (spec 7.1)."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.job_registry import SyncJobRegistry
from kairos.scheduler.repository import ScheduledJobRepository
from kairos.scheduler.schedule import InvalidSchedule, next_occurrence
from kairos.scheduler.types import (
    ActionContext,
    ActionFailed,
    ActionSkipped,
    ActionSpec,
    StepRecord,
)

logger = logging.getLogger(__name__)


def derive_status(steps: list[StepRecord]) -> tuple[str, str | None]:
    statuses = [s.get("status") for s in steps]
    if "failed" in statuses:
        return "failed", None
    if statuses and all(s == "skipped" for s in statuses):
        return "skipped", "all_steps_skipped"
    return "ok", None


def compute_next_run(cron_exprs: list[str], tz: str, after: datetime) -> datetime | None:
    try:
        return next_occurrence(cron_exprs, tz, after)
    except InvalidSchedule:
        # a schedule that no longer validates stops the job instead of crashing the loop
        logger.warning("Invalid stored schedule, job paused")
        return None


async def run_job(
    *,
    job_id: UUID,
    run_id: UUID,
    user_id: UUID,
    registry: SyncJobRegistry,
    actions: Mapping[str, ActionSpec],
    now: Callable[[], datetime],
) -> str:
    started = time.monotonic()
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        repo = ScheduledJobRepository(session)
        job = await repo.get(job_id)
        run = await repo.get_run(run_id)
        if job is None or run is None:
            return "failed"
        trigger = run.trigger
        records: list[StepRecord] = [dict(s) for s in run.steps]  # type: ignore[misc]

    previous: list[StepRecord] = []
    for record in records:
        record.update({"status": "running", "started_at": now().isoformat()})
        await _save_steps(user_id, run_id, records)
        await _run_step(
            record,
            job=job,
            run_id=run_id,
            trigger=trigger,
            previous=previous,
            registry=registry,
            actions=actions,
            now=now,
            user_id=user_id,
        )
        record["finished_at"] = now().isoformat()
        previous.append(dict(record))  # type: ignore[arg-type]
        await _save_steps(user_id, run_id, records)
        logger.info(
            "Scheduled job %s step %s: %s", job_id, record.get("action"), record.get("status")
        )
        if record.get("status") == "failed":
            break

    status, skip_reason = derive_status(records)
    await _finish(user_id, job_id, run_id, status, skip_reason, now)
    logger.info(
        "Scheduled job %s run %s finished: %s in %.1fs",
        job_id,
        run_id,
        status,
        time.monotonic() - started,
    )
    return status


async def _run_step(
    record: StepRecord,
    *,
    job: Any,
    run_id: UUID,
    trigger: str,
    previous: list[StepRecord],
    registry: SyncJobRegistry,
    actions: Mapping[str, ActionSpec],
    now: Callable[[], datetime],
    user_id: UUID,
) -> None:
    spec = actions.get(record.get("action") or "")
    try:
        if spec is None:
            raise ActionFailed("unknown_action", "Unbekannte Aktion")
        try:
            # validated again at run time: a later schema change must not break a job silently
            params = spec.params.model_validate(record.get("params") or {})
        except ValidationError:
            raise ActionFailed("invalid_params", "Ungültige Parameter") from None
        ctx = ActionContext(
            user_id=user_id,
            job=job,
            run_id=run_id,
            trigger=trigger,
            now=now(),
            previous=list(previous),
            registry=registry,
        )
        outcome = await asyncio.wait_for(spec.run(ctx, params), timeout=spec.timeout_s)
        record.update({"status": outcome.status, "summary": outcome.summary, "data": outcome.data})
    except ActionSkipped as exc:
        record.update({"status": "skipped", "summary": exc.summary, "data": exc.data})
    except ActionFailed as exc:
        record.update({"status": "failed", "summary": exc.message, "error_code": exc.code})
    except TimeoutError:
        record.update(
            {"status": "failed", "summary": "Zeitüberschreitung", "error_code": "timeout"}
        )
    except Exception:
        logger.exception("Scheduled job %s step %s crashed", job.id, record.get("action"))
        record.update(
            {"status": "failed", "summary": "Unerwarteter Fehler", "error_code": "unexpected"}
        )


async def _save_steps(user_id: UUID, run_id: UUID, records: list[StepRecord]) -> None:
    # own commit per step, so the scheduler page shows progress
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        run = await ScheduledJobRepository(session).get_run(run_id)
        if run is not None:
            run.steps = [dict(r) for r in records]
            await session.commit()


async def _finish(
    user_id: UUID,
    job_id: UUID,
    run_id: UUID,
    status: str,
    skip_reason: str | None,
    now: Callable[[], datetime],
) -> None:
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        repo = ScheduledJobRepository(session)
        job = await repo.get(job_id, for_update=True)
        run = await repo.get_run(run_id)
        if job is None or run is None:
            return
        finished = now()
        await repo.finish_run(job, run, status=status, now=finished, skip_reason=skip_reason)
        if job.enabled and job.next_run_at is not None and job.next_run_at <= finished:
            # at least one occurrence came due while this run was busy
            missed = job.next_run_at
            await repo.record_overlap(job, finished, missed)
            job.next_run_at = compute_next_run(job.cron_exprs, job.timezone, finished)
        await repo.prune_runs(job_id)
        await session.commit()
