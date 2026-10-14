from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.fit_archive import ingest_fit_files
from kairos.activities.reconcile import reconcile_deleted_activities
from kairos.auth.crypto import decrypt, kek_from_settings, unwrap_dek
from kairos.auth.deps import current_user
from kairos.config import settings
from kairos.connectors.garmin.connector import GarminConnector
from kairos.connectors.google_calendar.client import GoogleCalendarClient
from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.connectors.types import RawPayloadEnvelope, Window
from kairos.db.models import AppUser, Connection
from kairos.db.rls import install_rls_listener
from kairos.db.session import async_session_factory
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.job_registry import SyncJob, SyncJobRegistry, get_registry
from kairos.ingestion.service import PostWindowHook, SyncService
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.canonical import SqlCanonicalRepository
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_metric_daily_values,
    recompute_wellness_daily_stats,
)
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from kairos.repositories.sync_state import SqlSyncStateRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sync", tags=["sync"])

_DEFAULT_BACKFILL_MONTHS = 24

# minimum time between two backfill/sync triggers per (user, connector) -- guards
# against rapid re-triggering causing repeated Garmin logins (a real incident once
# tripped Garmin's Cloudflare bot-detection and locked the account out); a future
# agent tool calls this same endpoint, so the cooldown protects it too
_GARMIN_BACKFILL_COOLDOWN_SECONDS = 300.0
_GOOGLE_CALENDAR_SYNC_COOLDOWN_SECONDS = 60.0

# activity_fit must run after activity_list (FK dependency on activity.id)
_ALL_KINDS: tuple[str, ...] = (
    "hr_intraday", "sleep", "stress", "body_battery",
    "hrv", "respiration", "spo2", "daily_summary",
    "activity_list", "activity_fit",
)
_VALID_KINDS = frozenset(_ALL_KINDS)


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

    cooldown_remaining = registry.seconds_until_trigger_allowed(
        user_id, "garmin", _GARMIN_BACKFILL_COOLDOWN_SECONDS
    )
    if cooldown_remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Bitte {int(cooldown_remaining) + 1}s warten, bevor erneut synchronisiert wird",
            headers={"Retry-After": str(int(cooldown_remaining) + 1)},
        )

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

    registry.record_trigger(user_id, "garmin")

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

    cooldown_remaining = registry.seconds_until_trigger_allowed(
        user_id, "google_calendar", _GOOGLE_CALENDAR_SYNC_COOLDOWN_SECONDS
    )
    if cooldown_remaining > 0:
        raise HTTPException(
            status_code=429,
            detail=f"Bitte {int(cooldown_remaining) + 1}s warten, bevor erneut synchronisiert wird",
            headers={"Retry-After": str(int(cooldown_remaining) + 1)},
        )

    from_dt = _to_utc_midnight(date.today() - timedelta(days=7))
    to_dt = _to_utc_midnight(date.today() + timedelta(days=83))

    jobs = registry.create_jobs(
        user_id=user_id,
        connector="google_calendar",
        kinds=["events"],
        from_date=from_dt.date().isoformat(),
        to_date=to_dt.date().isoformat(),
    )
    registry.record_trigger(user_id, "google_calendar")

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


def _make_on_progress(job: SyncJob) -> Callable[[int], None]:
    # a plain lambda closing over the `for job in jobs` loop variable by
    # reference triggered ruff's B023 (late-binding gotcha); binding `job` as
    # this factory's parameter instead avoids that entirely, one call per job
    def _on_progress(n: int) -> None:
        job.windows_processed = n

    return _on_progress


def _make_on_windows_total(job: SyncJob) -> Callable[[int], None]:
    def _on_windows_total(n: int) -> None:
        job.windows_total = n

    return _on_windows_total


async def _run_backfill_task(
    *,
    user_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
    jobs: list[SyncJob],
    registry: SyncJobRegistry,
) -> None:
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)

        garmin, garmin_error = await _build_garmin_client(session, user_id)
        if garmin is None:
            for job in jobs:
                job.status = "failed"
                job.error = garmin_error or "No active Garmin connection or decryption failed"
                job.finished_at = datetime.now(UTC).isoformat()
            return

        connector = GarminConnector(
            garmin, fit_download_pause_s=settings.garmin_fit_download_pause_s
        )
        reconciled_days: set[date] = set()
        service = SyncService(
            raw_repo=SqlRawPayloadRepository(session=session),
            canonical_repo=SqlCanonicalRepository(session=session),
            sync_state_repo=SqlSyncStateRepository(session=session),
            hash_payload=payload_sha256,
            post_window=_make_fit_ingest_hook(session, user_id, reconciled_days),
        )

        fetched_froms: list[datetime] = []
        for job in jobs:
            lock = registry.get_lock(user_id, "garmin", job.kind)
            if lock.locked():
                job.status = "skipped"
                job.error = "Already running in another request"
                job.finished_at = datetime.now(UTC).isoformat()
                continue

            async with lock:
                job.status = "running"
                job.started_at = datetime.now(UTC).isoformat()
                try:
                    result = await service.run_backfill(
                        connector=connector,
                        user_id=user_id,
                        kind=job.kind,
                        from_date=from_dt,
                        to_date=to_dt,
                        throttle_seconds=settings.garmin_backfill_throttle_seconds,
                        # updates the in-memory job directly (no DB commit needed,
                        # unlike the once-per-kind session.commit() below) so
                        # GET /api/sync/status shows real progress mid-run instead
                        # of 0 the entire time and then a jump to windows_total
                        on_progress=_make_on_progress(job),
                        # requested range is an upper bound; already-covered days are skipped
                        on_windows_total=_make_on_windows_total(job),
                    )
                    await session.commit()
                    job.status = "done"
                    job.windows_processed = result.windows_processed
                    if result.fetched_from is not None:
                        fetched_froms.append(result.fetched_from)
                except Exception as exc:
                    await session.rollback()
                    job.status = "failed"
                    job.error = str(exc)
                finally:
                    job.finished_at = datetime.now(UTC).isoformat()

        if fetched_froms or reconciled_days:
            starts = [f.date() for f in fetched_froms] + list(reconciled_days)
            await _recompute_after_sync(
                session, user_id, start=min(starts), end=date.today()
            )


def _make_fit_ingest_hook(
    session: AsyncSession, user_id: UUID, reconciled_days: set[date]
) -> PostWindowHook:
    async def _hook(
        kind: str, envelope: RawPayloadEnvelope, raw_payload_id: int, file_ids: dict[str, int]
    ) -> None:
        del raw_payload_id
        if kind == "activity_fit" and envelope.files:
            await ingest_fit_files(
                session, user_id=user_id, file_ids_by_key=file_ids, files=envelope.files
            )
        if kind == "activity_list":
            ids = await reconcile_deleted_activities(
                session, user_id=user_id, window=envelope.window, payload=envelope.payload
            )
            if ids:
                rows = await session.execute(
                    text("SELECT start_at FROM activity WHERE id = ANY(:ids)"), {"ids": ids}
                )
                # UTC sample days of the removed streams, as the HR bucket recompute groups them
                reconciled_days.update(r[0].date() for r in rows if r[0] is not None)

    return _hook


async def _recompute_after_sync(
    session: AsyncSession, user_id: UUID, *, start: date, end: date
) -> None:
    # derived tables are best-effort: a failure here must not flip the finished sync jobs
    try:
        await recompute_wellness_daily_stats(session, user_id=user_id, start=start, end=end)
        await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=start, end=end)
        await recompute_metric_daily_values(session, user_id=user_id, start=start, end=end)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Metric recompute after backfill failed for user %s", user_id)


async def _build_garmin_client(
    session: AsyncSession, user_id: UUID
) -> tuple[object | None, str | None]:
    try:
        # first() not scalar_one_or_none(): pre-existing duplicate rows must not raise here,
        # the bare except below would turn that into an opaque "no connection" failure
        conn_row = (await session.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.connector == "garmin",
                Connection.status.in_(["active", "reauth_required"]),
            ).order_by(Connection.connected_at.desc(), Connection.id.desc())
        )).scalars().first()

        if conn_row is None:
            # info, not warning: the user simply has not connected Garmin yet
            logger.info("No active Garmin connection for user %s", user_id)
            return None, "No active Garmin connection or decryption failed"
        if conn_row.credentials_enc is None:
            logger.warning(
                "Garmin connection %s for user %s has no stored credentials", conn_row.id, user_id
            )
            return None, "No active Garmin connection or decryption failed"

        user_row = (await session.execute(
            select(AppUser).where(AppUser.id == user_id)
        )).scalar_one_or_none()

        if user_row is None:
            logger.warning("No app_user row for user %s while building Garmin client", user_id)
            return None, "No active Garmin connection or decryption failed"
        if user_row.dek_wrapped is None:
            logger.warning("User %s has no wrapped DEK — cannot decrypt Garmin tokens", user_id)
            return None, "No active Garmin connection or decryption failed"

        kek = kek_from_settings(settings.kairos_kek)
        dek = unwrap_dek(user_row.dek_wrapped, kek)
        token_json = decrypt(conn_row.credentials_enc, dek).decode()

        gc = importlib.import_module("garminconnect")
        garmin = cast(Any, gc.Garmin())
        try:
            await asyncio.to_thread(garmin.login, token_json)
        except gc.GarminConnectAuthenticationError as exc:
            # Garmin rejected the stored token outright (expired/revoked session) --
            # distinct from the generic except below, this needs the user to
            # reconnect via POST /api/connections/garmin, not just a retry
            _mark_reauth_required(conn_row, str(exc))
            await session.commit()
            logger.warning("Garmin token rejected for user %s: %s", user_id, exc)
            return None, "Garmin-Sitzung abgelaufen — bitte unter Konto & Sync neu verbinden"

        _mark_connection_healthy(conn_row)
        await session.commit()
        return garmin, None
    except Exception as exc:
        logger.warning("Garmin client build failed for user %s: %s", user_id, exc)
        return None, "No active Garmin connection or decryption failed"


def _mark_reauth_required(conn_row: Connection, error: str) -> None:
    conn_row.status = "reauth_required"
    conn_row.last_error = error
    # set once, when the connection first breaks -- not bumped on every retry
    if conn_row.reauth_since is None:
        conn_row.reauth_since = datetime.now(UTC)


def _mark_connection_healthy(conn_row: Connection) -> None:
    conn_row.status = "active"
    conn_row.last_error = None
    conn_row.reauth_since = None
    conn_row.last_ok_at = datetime.now(UTC)


async def _run_calendar_sync_task(
    *,
    user_id: UUID,
    from_dt: datetime,
    to_dt: datetime,
    jobs: list[SyncJob],
    registry: SyncJobRegistry,
) -> None:
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)

        client = await _build_google_calendar_client(session, user_id)
        job = jobs[0]
        if client is None:
            job.status = "failed"
            job.error = "No active Google Calendar connection or decryption failed"
            job.finished_at = datetime.now(UTC).isoformat()
            return

        connector = GoogleCalendarConnector(client)
        window = Window(start=from_dt, end=to_dt)

        lock = registry.get_lock(user_id, "google_calendar", job.kind)
        if lock.locked():
            job.status = "skipped"
            job.error = "Already running in another request"
            job.finished_at = datetime.now(UTC).isoformat()
            return

        async with lock:
            job.status = "running"
            job.started_at = datetime.now(UTC).isoformat()
            try:
                envelope = await asyncio.to_thread(connector.fetch, user_id, job.kind, window)
                records = connector.normalize(job.kind, envelope.payload)
                repo = CalendarEventRepository(session)
                written = await repo.upsert_from_records(user_id, "google_calendar", records)
                await session.commit()
                job.status = "done"
                job.windows_processed = written
            except Exception as exc:
                await session.rollback()
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.finished_at = datetime.now(UTC).isoformat()


async def _build_google_calendar_client(
    session: AsyncSession, user_id: UUID
) -> GoogleCalendarClient | None:
    try:
        # first() not scalar_one_or_none(): pre-existing duplicate rows must not raise here,
        # the bare except below would turn that into an opaque "no connection" failure
        conn_row = (await session.execute(
            select(Connection).where(
                Connection.user_id == user_id,
                Connection.connector == "google_calendar",
                Connection.status.in_(["active", "reauth_required"]),
            ).order_by(Connection.connected_at.desc(), Connection.id.desc())
        )).scalars().first()

        if conn_row is None or conn_row.credentials_enc is None:
            return None

        user_row = (await session.execute(
            select(AppUser).where(AppUser.id == user_id)
        )).scalar_one_or_none()

        if user_row is None or user_row.dek_wrapped is None:
            return None

        kek = kek_from_settings(settings.kairos_kek)
        dek = unwrap_dek(user_row.dek_wrapped, kek)
        refresh_token = decrypt(conn_row.credentials_enc, dek).decode()

        return GoogleCalendarClient(
            refresh_token=refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )
    except Exception:
        return None


def _to_utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _validate_kinds(kinds: list[str]) -> None:
    invalid = [k for k in kinds if k not in _VALID_KINDS]
    if invalid:
        raise HTTPException(status_code=422, detail=f"Unknown kinds: {invalid}")
