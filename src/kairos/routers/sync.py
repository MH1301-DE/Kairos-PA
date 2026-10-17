from __future__ import annotations

import logging
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from kairos.auth.deps import current_user
from kairos.calendar.sync import (
    GOOGLE_CALENDAR_COOLDOWN_SECONDS,
    CalendarNotConnected,
    sync_google_calendar,
)
from kairos.connectors.types import Window
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.garmin_sync import (
    ALL_KINDS,
    BUSY_MESSAGE,
    GARMIN_COOLDOWN_SECONDS,
    SYNC_FAILED_MESSAGE,
    GarminSyncPlan,
    sync_garmin,
)
from kairos.ingestion.job_registry import (
    SyncBusy,
    SyncCooldown,
    SyncJob,
    SyncJobRegistry,
    acquire_trigger,
    get_registry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

_DEFAULT_BACKFILL_MONTHS = 24

# the scheduler and a future agent tool share these cooldowns (garmin_sync, calendar.sync)
_ALL_KINDS = ALL_KINDS
_VALID_KINDS = frozenset(_ALL_KINDS)

_CALENDAR_ERRORS = {
    "reauth_required": "Google-Kalender-Zugriff abgelaufen — bitte neu anmelden",
    "unavailable": "Google Kalender nicht erreichbar",
}


class BackfillRequest(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    # None means all kinds in the default order
    kinds: list[str] | None = None


@router.post("/garmin/backfill", status_code=202)
async def trigger_garmin_backfill(
    req: BackfillRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])

    remaining = registry.seconds_until_trigger_allowed(user_id, "garmin", GARMIN_COOLDOWN_SECONDS)
    if remaining > 0:
        raise _cooldown_http(SyncCooldown(int(remaining) + 1))

    to_dt = _to_utc_midnight(req.to_date or date.today())
    from_dt = _to_utc_midnight(
        req.from_date or date.today() - timedelta(days=_DEFAULT_BACKFILL_MONTHS * 30)
    )

    kinds = req.kinds or list(_ALL_KINDS)
    _validate_kinds(kinds)

    # skip any kind that is already actively processing for this user
    queued = [k for k in kinds if not registry.is_locked(user_id, "garmin", k)]
    if not queued:
        raise HTTPException(status_code=409, detail="All requested kinds are already running")

    try:
        acquire_trigger(registry, user_id, "garmin", GARMIN_COOLDOWN_SECONDS)
    except SyncCooldown as exc:
        raise _cooldown_http(exc) from None

    # SyncService.run_backfill windows one calendar day at a time (its `step`
    # default) -- matches this count so the UI can show windows_processed as
    # a percentage of a real total.
    total_days = max((to_dt.date() - from_dt.date()).days, 0)

    jobs = registry.create_jobs(
        user_id=user_id,
        connector="garmin",
        kinds=queued,
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
        windows_total=total_days,
    )

    background_tasks.add_task(
        _run_backfill_task,
        user_id=user_id,
        from_dt=from_dt,
        to_dt=to_dt,
        jobs=jobs,
        registry=registry,
    )

    return {"jobs": [j.to_dict() for j in jobs]}


def _cooldown_http(exc: SyncCooldown) -> HTTPException:
    return HTTPException(
        status_code=429,
        detail=f"Bitte {exc.retry_after_s}s warten, bevor erneut synchronisiert wird",
        headers={"Retry-After": str(exc.retry_after_s)},
    )


@router.get("/status")
async def sync_status(
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    return {"jobs": [j.to_dict() for j in registry.get_jobs_for_user(user_id)]}


@router.post("/google_calendar/sync", status_code=202)
async def trigger_google_calendar_sync(
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    if registry.is_locked(user_id, "google_calendar", "events"):
        raise HTTPException(status_code=409, detail="Sync already running")

    try:
        acquire_trigger(registry, user_id, "google_calendar", GOOGLE_CALENDAR_COOLDOWN_SECONDS)
    except SyncCooldown as exc:
        raise _cooldown_http(exc) from None

    from_dt = _to_utc_midnight(date.today() - timedelta(days=7))
    to_dt = _to_utc_midnight(date.today() + timedelta(days=83))

    jobs = registry.create_jobs(
        user_id=user_id,
        connector="google_calendar",
        kinds=["events"],
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
    )

    background_tasks.add_task(
        _run_calendar_sync_task,
        user_id=user_id,
        from_dt=from_dt,
        to_dt=to_dt,
        jobs=jobs,
        registry=registry,
    )

    return {"jobs": [j.to_dict() for j in jobs]}


# ── Background task ───────────────────────────────────────────────────────────


async def _run_backfill_task(
    *,
    user_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
    jobs: list[SyncJob],
    registry: SyncJobRegistry,
) -> None:
    plan = GarminSyncPlan(
        kinds=[j.kind for j in jobs],
        ranges={j.kind: (from_dt, to_dt) for j in jobs},
        respect_coverage=True,
    )
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        await sync_garmin(session, user_id, plan, registry=registry, jobs=jobs)


async def _run_calendar_sync_task(
    *,
    user_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
    jobs: list[SyncJob],
    registry: SyncJobRegistry,
) -> None:
    del registry  # the core takes the shared lock itself
    job = jobs[0]
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        job.status = "running"
        job.started_at = datetime.now(UTC).isoformat()
        try:
            result = await sync_google_calendar(session, user_id, Window(start=from_dt, end=to_dt))
        except SyncBusy:
            job.status = "skipped"
            job.error = BUSY_MESSAGE
        except CalendarNotConnected:
            job.status = "failed"
            job.error = "No active Google Calendar connection or decryption failed"
        except Exception:
            logger.exception("Calendar sync failed for user %s", user_id)
            job.status = "failed"
            job.error = SYNC_FAILED_MESSAGE
        else:
            if result["error_code"] is None:
                job.status = "done"
                job.windows_processed = result["upserted"]
            else:
                job.status = "failed"
                job.error = _CALENDAR_ERRORS.get(result["error_code"], SYNC_FAILED_MESSAGE)
        finally:
            job.finished_at = datetime.now(UTC).isoformat()


def _to_utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _validate_kinds(kinds: list[str]) -> None:
    invalid = [k for k in kinds if k not in _VALID_KINDS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown kinds: {invalid}")
