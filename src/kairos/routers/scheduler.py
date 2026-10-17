from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError
from pydantic_core import ErrorDetails
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.models import AppUser, ScheduledJob, ScheduledJobRun
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.ingestion.job_registry import get_registry
from kairos.scheduler.actions import ACTIONS
from kairos.scheduler.loop import get_scheduler
from kairos.scheduler.repository import ScheduledJobRepository
from kairos.scheduler.runner import compute_next_run
from kairos.scheduler.schedule import (
    InvalidSchedule,
    describe,
    min_gap,
    occurrences,
    validate,
    zone,
)

router = APIRouter(prefix="/api/scheduler", tags=["scheduler"])

MAX_JOBS = 10
MAX_STEPS = 8
_PREVIEW_COUNT = 5


class StepIn(BaseModel):
    action: str
    params: dict[str, Any] = {}


class JobIn(BaseModel):
    name: str
    cron_exprs: list[str]
    # None: the user's home time zone
    timezone: str | None = None
    enabled: bool = True
    steps: list[StepIn]
    context_reset_every: int = 1


class PatchIn(BaseModel):
    enabled: bool


class PreviewIn(BaseModel):
    cron_exprs: list[str]
    timezone: str


@router.get("/actions")
async def list_actions(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    return {
        # the editor preselects the user's home time zone
        "default_timezone": await _home_timezone(session, user_id),
        "actions": [
            {
                "name": spec.name,
                "label": spec.label,
                "description": spec.description,
                "schema": spec.params.model_json_schema(),
                "min_interval_s": spec.min_interval_s,
            }
            for spec in ACTIONS.values()
        ],
    }


@router.post("/preview")
async def preview(req: PreviewIn, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    del user
    try:
        validate(req.cron_exprs, req.timezone)
    except InvalidSchedule as exc:
        return {"label": None, "next": [], "errors": [str(exc)]}
    now = datetime.now(UTC)
    runs = occurrences(req.cron_exprs, req.timezone, now, now.replace(year=now.year + 1))
    zi = zone(req.timezone)
    return {
        "label": describe(req.cron_exprs, req.timezone),
        "next": [
            {"utc": r.isoformat(), "local": r.astimezone(zi).isoformat()}
            for r in runs[:_PREVIEW_COUNT]
        ],
        "errors": [],
    }


@router.get("/status")
async def scheduler_status(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # feeds the error dot on the "Scheduler" navigation entry
    install_rls_listener(session, UUID(user["user_id"]))
    jobs = await ScheduledJobRepository(session).list_jobs()
    return {"failed_jobs": sum(1 for j in jobs if j.enabled and j.last_status == "failed")}


@router.get("/jobs")
async def list_jobs(
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    install_rls_listener(session, UUID(user["user_id"]))
    repo = ScheduledJobRepository(session)
    jobs = await repo.list_jobs()
    latest = await repo.latest_runs([j.id for j in jobs])
    return {"jobs": [_job_dict(j, latest.get(j.id), full=False) for j in jobs]}


@router.post("/jobs", status_code=201)
async def create_job(
    req: JobIn,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ScheduledJobRepository(session)
    if await repo.count() >= MAX_JOBS:
        _raise({"jobs": f"Höchstens {MAX_JOBS} Jobs je Nutzer"})
    tz = req.timezone or await _home_timezone(session, user_id)
    steps = _validated(req, tz)
    now = datetime.now(UTC)
    job = await repo.create(
        user_id=user_id,
        name=req.name.strip(),
        cron_exprs=req.cron_exprs,
        timezone=tz,
        enabled=req.enabled,
        steps=steps,
        context_reset_every=req.context_reset_every,
        next_run_at=compute_next_run(req.cron_exprs, tz, now) if req.enabled else None,
    )
    await session.commit()
    return _job_dict(job, None, full=True)


@router.get("/jobs/{job_id}")
async def get_job(
    job_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    install_rls_listener(session, UUID(user["user_id"]))
    repo = ScheduledJobRepository(session)
    job = await _get_or_404(repo, job_id)
    latest = await repo.latest_runs([job.id])
    return _job_dict(job, latest.get(job.id), full=True)


@router.put("/jobs/{job_id}")
async def replace_job(
    job_id: UUID,
    req: JobIn,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = ScheduledJobRepository(session)
    job = await _get_or_404(repo, job_id, for_update=True)
    tz = req.timezone or job.timezone
    steps = _validated(req, tz)
    now = datetime.now(UTC)
    # a running run keeps its own snapshot; changes apply from the next run
    job.name = req.name.strip()
    job.cron_exprs = req.cron_exprs
    job.timezone = tz
    job.enabled = req.enabled
    job.steps = steps
    job.context_reset_every = req.context_reset_every
    job.next_run_at = compute_next_run(req.cron_exprs, tz, now) if req.enabled else None
    job.updated_at = now
    await session.commit()
    latest = await repo.latest_runs([job.id])
    return _job_dict(job, latest.get(job.id), full=True)


@router.patch("/jobs/{job_id}")
async def toggle_job(
    job_id: UUID,
    req: PatchIn,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    install_rls_listener(session, UUID(user["user_id"]))
    repo = ScheduledJobRepository(session)
    job = await _get_or_404(repo, job_id, for_update=True)
    now = datetime.now(UTC)
    job.enabled = req.enabled
    # switching on counts from now: no catch-up for the time it was off
    job.next_run_at = compute_next_run(job.cron_exprs, job.timezone, now) if req.enabled else None
    job.updated_at = now
    await session.commit()
    latest = await repo.latest_runs([job.id])
    return _job_dict(job, latest.get(job.id), full=True)


@router.delete("/jobs/{job_id}", status_code=204, response_model=None)
async def delete_job(
    job_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    install_rls_listener(session, UUID(user["user_id"]))
    repo = ScheduledJobRepository(session)
    job = await _get_or_404(repo, job_id, for_update=True)
    if job.running_since is not None:
        raise HTTPException(status_code=409, detail="job_running")
    # the job's conversation stays (scheduled_job.conversation_id is the only link)
    await repo.delete(job)
    await session.commit()


@router.post("/jobs/{job_id}/run", status_code=202)
async def run_job_now(
    job_id: UUID,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    await _get_or_404(ScheduledJobRepository(session), job_id)
    await session.commit()
    run_id = await get_scheduler(get_registry()).run_now(user_id, job_id)
    if run_id is None:
        raise HTTPException(status_code=409, detail="job_running")
    return {"run_id": str(run_id)}


@router.get("/jobs/{job_id}/runs")
async def list_runs(
    job_id: UUID,
    limit: int = Query(20, ge=1, le=200),
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    install_rls_listener(session, UUID(user["user_id"]))
    repo = ScheduledJobRepository(session)
    await _get_or_404(repo, job_id)
    return {"runs": [_run_dict(r) for r in await repo.list_runs(job_id, limit)]}


# --- helpers --------------------------------------------------------------------------


def _validated(req: JobIn, tz: str) -> list[dict[str, Any]]:
    errors: dict[str, str] = {}
    name = req.name.strip()
    if not 1 <= len(name) <= 80:
        errors["name"] = "Name mit 1 bis 80 Zeichen angeben"
    schedule_ok = True
    try:
        zone(tz)
    except InvalidSchedule as exc:
        errors["timezone"] = str(exc)
        schedule_ok = False
    try:
        validate(req.cron_exprs, tz if schedule_ok else "UTC")
    except InvalidSchedule as exc:
        errors["cron_exprs"] = str(exc)
        schedule_ok = False
    if not 0 <= req.context_reset_every <= 30:
        errors["context_reset_every"] = "Wert zwischen 0 (nie) und 30"

    steps: list[dict[str, Any]] = []
    if not 1 <= len(req.steps) <= MAX_STEPS:
        errors["steps"] = f"1 bis {MAX_STEPS} Schritte angeben"
    if sum(1 for s in req.steps if s.action == "agent.prompt") > 1:
        errors["steps"] = "Höchstens ein Agent-Schritt je Job"
    for i, step in enumerate(req.steps):
        spec = ACTIONS.get(step.action)
        if spec is None:
            errors[f"steps.{i}.action"] = "Unbekannte Aktion"
            continue
        try:
            params = spec.params.model_validate(step.params)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                errors[f"steps.{i}.params" + (f".{loc}" if loc else "")] = _german(err)
            continue
        steps.append({"action": spec.name, "params": params.model_dump(mode="json")})

    if schedule_ok and not errors:
        strictest = max(ACTIONS[s["action"]].min_interval_s for s in steps)
        gap = min_gap(req.cron_exprs, tz, datetime.now(UTC))
        if gap.total_seconds() < strictest:
            label = next(
                ACTIONS[s["action"]].label
                for s in steps
                if ACTIONS[s["action"]].min_interval_s == strictest
            )
            errors["cron_exprs"] = (
                f"Zu häufig: „{label}“ braucht mindestens {strictest // 60} min Abstand, "
                f"der Zeitplan hat {int(gap.total_seconds() // 60)} min"
            )
    if errors:
        _raise(errors)
    return steps


def _german(err: ErrorDetails) -> str:
    ctx = err.get("ctx") or {}
    match err["type"]:
        case "missing":
            return "Pflichtfeld"
        case "extra_forbidden":
            return "Unbekanntes Feld"
        case "string_too_short":
            return "Darf nicht leer sein"
        case "string_too_long":
            return f"Höchstens {ctx.get('max_length')} Zeichen"
        case "greater_than_equal":
            return f"Mindestens {ctx.get('ge')}"
        case "less_than_equal":
            return f"Höchstens {ctx.get('le')}"
        case "literal_error":
            return "Ungültiger Wert"
        case "value_error":
            return str(ctx.get("error") or "Ungültiger Wert")
        case _:
            return "Ungültiger Wert"


def _raise(errors: dict[str, str]) -> None:
    raise HTTPException(status_code=422, detail={"errors": errors})


async def _home_timezone(session: AsyncSession, user_id: UUID) -> str:
    tz = (
        await session.execute(select(AppUser.home_timezone).where(AppUser.id == user_id))
    ).scalar_one_or_none()
    return tz or "Europe/Berlin"


async def _get_or_404(
    repo: ScheduledJobRepository, job_id: UUID, *, for_update: bool = False
) -> ScheduledJob:
    job = await repo.get(job_id, for_update=for_update)
    if job is None:
        raise HTTPException(status_code=404, detail="job_not_found")
    return job


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _job_dict(job: ScheduledJob, latest: ScheduledJobRun | None, *, full: bool) -> dict[str, Any]:
    try:
        label = describe(job.cron_exprs, job.timezone)
    except InvalidSchedule:
        label = "Ungültiger Zeitplan"
    out: dict[str, Any] = {
        "id": str(job.id),
        "name": job.name,
        "label": label,
        "timezone": job.timezone,
        "enabled": job.enabled,
        "next_run_at": _iso(job.next_run_at),
        "last_status": job.last_status,
        "last_run_at": _iso(latest.started_at) if latest else None,
        "last_success_at": _iso(job.last_success_at),
        "running": job.running_since is not None,
        "conversation_id": str(job.conversation_id) if job.conversation_id else None,
        "consecutive_failures": job.consecutive_failures,
        "proposal_open": bool(
            latest and any((s.get("data") or {}).get("proposal_open") for s in latest.steps or [])
        ),
        "steps": [s["action"] for s in job.steps],
    }
    if full:
        out.update(
            cron_exprs=job.cron_exprs,
            steps=job.steps,
            context_reset_every=job.context_reset_every,
        )
    return out


def _run_dict(run: ScheduledJobRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "trigger": run.trigger,
        "scheduled_for": _iso(run.scheduled_for),
        "started_at": _iso(run.started_at),
        "finished_at": _iso(run.finished_at),
        "status": run.status,
        "skip_reason": run.skip_reason,
        "steps": run.steps,
    }
