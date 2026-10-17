from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import ScheduledJob, ScheduledJobRun

RUN_HISTORY_KEEP = 200


@dataclass(frozen=True)
class DueJob:
    job_id: UUID
    user_id: UUID
    next_run_at: datetime


async def due_jobs(session: AsyncSession, now: datetime, limit: int) -> list[DueJob]:
    # SECURITY DEFINER: sees all users' jobs without app.current_user_id, ids only
    rows = await session.execute(
        text("SELECT job_id, user_id, next_run_at FROM scheduler_due_jobs(:now, :limit)"),
        {"now": now, "limit": limit},
    )
    return [DueJob(r.job_id, r.user_id, r.next_run_at) for r in rows]


async def mark_interrupted(session: AsyncSession, now: datetime) -> list[tuple[UUID, UUID]]:
    rows = await session.execute(
        text("SELECT job_id, user_id FROM scheduler_mark_interrupted(:now)"), {"now": now}
    )
    return [(r.job_id, r.user_id) for r in rows]


class ScheduledJobRepository:
    """Every method expects a session with install_rls_listener for the job's user."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_jobs(self) -> list[ScheduledJob]:
        result = await self._session.execute(
            select(ScheduledJob).order_by(ScheduledJob.created_at, ScheduledJob.id)
        )
        return list(result.scalars())

    async def count(self) -> int:
        return int(
            (
                await self._session.execute(select(func.count()).select_from(ScheduledJob))
            ).scalar_one()
        )

    async def get(self, job_id: UUID, *, for_update: bool = False) -> ScheduledJob | None:
        stmt = select(ScheduledJob).where(ScheduledJob.id == job_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create(self, **fields: Any) -> ScheduledJob:
        job = ScheduledJob(**fields)
        self._session.add(job)
        await self._session.flush()
        return job

    async def delete(self, job: ScheduledJob) -> None:
        await self._session.delete(job)
        await self._session.flush()

    async def claim(
        self,
        job_id: UUID,
        now: datetime,
        *,
        next_run: Callable[[ScheduledJob], datetime | None],
        catch_up_after: timedelta,
    ) -> tuple[ScheduledJob, ScheduledJobRun] | None:
        job = (
            await self._session.execute(
                select(ScheduledJob)
                .where(
                    ScheduledJob.id == job_id,
                    ScheduledJob.enabled.is_(True),
                    ScheduledJob.running_since.is_(None),
                    ScheduledJob.next_run_at <= now,
                )
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None or job.next_run_at is None:
            return None
        due = job.next_run_at
        trigger = "catch_up" if now - due > catch_up_after else "schedule"
        # skips every missed occurrence: together with this one claim, "catch up once"
        job.next_run_at = next_run(job)
        run = self._start_run(job, now, trigger=trigger, scheduled_for=due)
        await self._session.flush()
        return job, run

    async def start_manual(
        self, job_id: UUID, now: datetime
    ) -> tuple[ScheduledJob, ScheduledJobRun] | None:
        job = (
            await self._session.execute(
                select(ScheduledJob)
                .where(ScheduledJob.id == job_id, ScheduledJob.running_since.is_(None))
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if job is None:
            return None
        run = self._start_run(job, now, trigger="manual", scheduled_for=None)
        await self._session.flush()
        return job, run

    def _start_run(
        self, job: ScheduledJob, now: datetime, *, trigger: str, scheduled_for: datetime | None
    ) -> ScheduledJobRun:
        job.running_since = now
        job.updated_at = now
        run = ScheduledJobRun(
            job_id=job.id,
            user_id=job.user_id,
            trigger=trigger,
            scheduled_for=scheduled_for,
            started_at=now,
            status="running",
            steps=[{**s, "status": "not_run"} for s in job.steps],
        )
        self._session.add(run)
        return run

    async def get_run(self, run_id: UUID) -> ScheduledJobRun | None:
        return (
            await self._session.execute(select(ScheduledJobRun).where(ScheduledJobRun.id == run_id))
        ).scalar_one_or_none()

    async def finish_run(
        self,
        job: ScheduledJob,
        run: ScheduledJobRun,
        *,
        status: str,
        now: datetime,
        skip_reason: str | None = None,
    ) -> None:
        run.status = status
        run.skip_reason = skip_reason
        run.finished_at = now
        job.running_since = None
        job.last_run_id = run.id
        job.last_status = status
        job.updated_at = now
        if status == "ok":
            job.last_success_at = now
            job.consecutive_failures = 0
        elif status == "failed":
            job.consecutive_failures = job.consecutive_failures + 1
        await self._session.flush()

    async def record_overlap(
        self, job: ScheduledJob, now: datetime, scheduled_for: datetime | None
    ) -> ScheduledJobRun:
        run = ScheduledJobRun(
            job_id=job.id,
            user_id=job.user_id,
            trigger="schedule",
            scheduled_for=scheduled_for,
            started_at=now,
            finished_at=now,
            status="skipped",
            skip_reason="overlap",
            steps=[{**s, "status": "not_run"} for s in job.steps],
        )
        self._session.add(run)
        job.last_run_id = run.id
        job.last_status = "skipped"
        await self._session.flush()
        return run

    async def prune_runs(self, job_id: UUID, keep: int = RUN_HISTORY_KEEP) -> None:
        keep_ids = (
            select(ScheduledJobRun.id)
            .where(ScheduledJobRun.job_id == job_id)
            .order_by(ScheduledJobRun.started_at.desc(), ScheduledJobRun.id.desc())
            .limit(keep)
        )
        await self._session.execute(
            delete(ScheduledJobRun).where(
                ScheduledJobRun.job_id == job_id, ScheduledJobRun.id.not_in(keep_ids)
            )
        )

    async def list_runs(self, job_id: UUID, limit: int) -> list[ScheduledJobRun]:
        result = await self._session.execute(
            select(ScheduledJobRun)
            .where(ScheduledJobRun.job_id == job_id)
            .order_by(ScheduledJobRun.started_at.desc(), ScheduledJobRun.id.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def agent_steps_since(self, user_id: UUID, since: datetime) -> int:
        # executed agent steps (ok or failed) of this user since `since`, across all jobs
        row = await self._session.execute(
            text(
                "SELECT count(*) FROM scheduled_job_run r, jsonb_array_elements(r.steps) s "
                "WHERE r.user_id = :uid AND r.started_at >= :since "
                "AND s->>'action' = 'agent.prompt' AND s->>'status' IN ('ok', 'failed')"
            ),
            {"uid": str(user_id), "since": since},
        )
        return int(row.scalar_one())

    async def prompt_seqs(self, job_id: UUID) -> set[int]:
        rows = await self._session.execute(
            select(ScheduledJobRun.prompt_message_seq).where(
                ScheduledJobRun.job_id == job_id, ScheduledJobRun.prompt_message_seq.is_not(None)
            )
        )
        return {int(r) for r in rows.scalars() if r is not None}

    async def job_ids_by_conversation(self) -> dict[UUID, UUID]:
        rows = await self._session.execute(
            select(ScheduledJob.conversation_id, ScheduledJob.id).where(
                ScheduledJob.conversation_id.is_not(None)
            )
        )
        return {conv: job for conv, job in rows.tuples() if conv is not None}

    async def latest_runs(self, job_ids: list[UUID]) -> dict[UUID, ScheduledJobRun]:
        if not job_ids:
            return {}
        result = await self._session.execute(
            select(ScheduledJobRun)
            .where(ScheduledJobRun.job_id.in_(job_ids))
            .order_by(
                ScheduledJobRun.job_id,
                ScheduledJobRun.started_at.desc(),
                ScheduledJobRun.id.desc(),
            )
            .distinct(ScheduledJobRun.job_id)
        )
        return {run.job_id: run for run in result.scalars()}
