from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from kairos.activities.reprocess import reprocess_activities
from kairos.auth.deps import current_user
from kairos.config import settings
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.garmin_sync import GARMIN_COOLDOWN_SECONDS, _build_garmin_client
from kairos.ingestion.job_registry import SyncJob, SyncJobRegistry, get_registry

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/activities", tags=["activities"])

# shares the backfill locks: both write activities and streams
_LOCK_KINDS: tuple[str, ...] = ("activity_list", "activity_fit", "reprocess")


class ReprocessRequest(BaseModel):
    from_date: date | None = None
    to_date: date | None = None
    activity_ids: list[int] | None = None
    refetch_fit: bool = False


@router.post("/reprocess", status_code=202)
async def trigger_reprocess(
    req: ReprocessRequest,
    background_tasks: BackgroundTasks,
    user: dict[str, Any] = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    if any(registry.is_locked(user_id, "garmin", kind) for kind in _LOCK_KINDS):
        raise HTTPException(status_code=409, detail="Garmin-Aktivitäten werden bereits verarbeitet")

    cooldown_remaining = registry.seconds_until_trigger_allowed(
        user_id, "garmin", GARMIN_COOLDOWN_SECONDS
    )
    if cooldown_remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Bitte {int(cooldown_remaining) + 1}s warten, bevor erneut synchronisiert wird",
            headers={"Retry-After": str(int(cooldown_remaining) + 1)},
        )

    registry.record_trigger(user_id, "garmin")
    [job] = registry.create_jobs(
        user_id=user_id,
        connector="garmin",
        kinds=["reprocess"],
        from_date=req.from_date.isoformat() if req.from_date else "",
        to_date=req.to_date.isoformat() if req.to_date else "",
    )
    background_tasks.add_task(
        _run_reprocess_task, user_id=user_id, req=req, job=job, registry=registry
    )
    return {"job": job.to_dict()}


async def _run_reprocess_task(
    *, user_id: UUID, req: ReprocessRequest, job: SyncJob, registry: SyncJobRegistry
) -> None:
    locks = [registry.get_lock(user_id, "garmin", kind) for kind in _LOCK_KINDS]
    if any(lock.locked() for lock in locks):
        job.status = "skipped"
        job.error = "Already running in another request"
        job.finished_at = datetime.now(UTC).isoformat()
        return

    def _on_progress(done: int, total: int) -> None:
        job.windows_processed = done
        job.windows_total = total

    async with locks[0], locks[1], locks[2]:
        job.status = "running"
        job.started_at = datetime.now(UTC).isoformat()
        try:
            async with async_session_factory() as session:
                install_rls_listener(session, user_id)
                garmin: object | None = None
                if req.refetch_fit:
                    garmin, garmin_error = await _build_garmin_client(session, user_id)
                    if garmin is None:
                        job.status = "failed"
                        job.error = garmin_error or "No active Garmin connection"
                        return
                result = await reprocess_activities(
                    session,
                    user_id=user_id,
                    from_date=req.from_date,
                    to_date=req.to_date,
                    activity_ids=req.activity_ids,
                    refetch_fit=req.refetch_fit,
                    garmin=garmin,
                    pause_s=settings.garmin_fit_download_pause_s,
                    on_progress=_on_progress,
                )
            job.result = asdict(result)
            job.status = "done"
        except Exception as exc:
            logger.exception("Reprocess failed for user %s", user_id)
            job.status = "failed"
            job.error = str(exc)
        finally:
            job.finished_at = datetime.now(UTC).isoformat()
