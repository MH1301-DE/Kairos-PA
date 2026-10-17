"""HTTP-free Garmin sync core shared by the sync button and the scheduler."""

from __future__ import annotations

import asyncio
import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypedDict, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive.service import derive_pending
from kairos.activities.fit_archive import ingest_fit_files
from kairos.activities.reconcile import local_days_of_activities, reconcile_deleted_activities
from kairos.auth.crypto import decrypt, kek_from_settings, unwrap_dek
from kairos.config import settings
from kairos.connectors.garmin.connector import GarminConnector
from kairos.connectors.types import RawPayloadEnvelope
from kairos.db.models import Activity, AppUser, Connection
from kairos.ingestion.connection_status import mark_connection_healthy, mark_reauth_required
from kairos.ingestion.hash import payload_sha256
from kairos.ingestion.job_registry import SyncJob, SyncJobRegistry
from kairos.ingestion.service import (
    BackfillResult,
    PostWindowHook,
    SyncService,
    SyncStateRepository,
)
from kairos.repositories.canonical import SqlCanonicalRepository
from kairos.repositories.metrics_recompute import recompute_daily_tables
from kairos.repositories.raw_payload import SqlRawPayloadRepository
from kairos.repositories.sync_state import SqlSyncStateRepository

logger = logging.getLogger(__name__)

# minimum time between two backfill/sync triggers per (user, connector) -- guards
# against rapid re-triggering causing repeated Garmin logins (a real incident once
# tripped Garmin's Cloudflare bot-detection and locked the account out)
GARMIN_COOLDOWN_SECONDS = 300.0

# activity_fit must run after activity_list (FK dependency on activity.id)
ALL_KINDS: tuple[str, ...] = (
    "hr_intraday",
    "sleep",
    "stress",
    "body_battery",
    "hrv",
    "respiration",
    "spo2",
    "daily_summary",
    "activity_list",
    "activity_fit",
)

NOT_CONNECTED_MESSAGE = "No active Garmin connection or decryption failed"
REAUTH_MESSAGE = "Garmin-Sitzung abgelaufen — bitte unter Konto & Sync neu verbinden"
SYNC_FAILED_MESSAGE = "Synchronisierung fehlgeschlagen"
BUSY_MESSAGE = "Already running in another request"


@dataclass
class GarminSyncPlan:
    kinds: list[str]
    # per kind [from, to)
    ranges: dict[str, tuple[datetime, datetime]]
    # button: True (run_backfill), scheduler: False (run_incremental)
    respect_coverage: bool


KindResult = TypedDict(
    "KindResult",
    {
        "status": str,
        "windows_processed": int,
        "from": str,
        "to": str,
        "error_code": str | None,
    },
)


class GarminSyncResult(TypedDict):
    kinds: dict[str, KindResult]
    recomputed_from: date | None
    error_code: str | None


def utc_midnight(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


async def incremental_plan(
    repo: SyncStateRepository, user_id: UUID, kinds: list[str], now: datetime
) -> GarminSyncPlan:
    to_dt = utc_midnight(now.astimezone(UTC).date() + timedelta(days=1))
    ranges: dict[str, tuple[datetime, datetime]] = {}
    for kind in kinds:
        _, _, complete_to = await repo.get_backfill_state(
            user_id=user_id, connector_id="garmin", kind=kind
        )
        # never synced: today and yesterday only -- the two-year backfill stays a button action
        start = (complete_to or to_dt - timedelta(days=1)) - timedelta(days=1)
        ranges[kind] = (min(start, to_dt - timedelta(days=1)), to_dt)
    return GarminSyncPlan(kinds=kinds, ranges=ranges, respect_coverage=False)


async def sync_garmin(
    session: AsyncSession,
    user_id: UUID,
    plan: GarminSyncPlan,
    *,
    registry: SyncJobRegistry,
    jobs: list[SyncJob],
) -> GarminSyncResult:
    result: GarminSyncResult = {"kinds": {}, "recomputed_from": None, "error_code": None}

    garmin, garmin_error = await _build_garmin_client(session, user_id)
    if garmin is None:
        code = "reauth_required" if garmin_error == REAUTH_MESSAGE else "not_connected"
        result["error_code"] = code
        for job in jobs:
            job.status = "failed"
            job.error = garmin_error or NOT_CONNECTED_MESSAGE
            job.finished_at = datetime.now(UTC).isoformat()
            result["kinds"][job.kind] = _kind_result(plan, job, "failed", 0, code)
        return result

    connector = GarminConnector(garmin, fit_download_pause_s=settings.garmin_fit_download_pause_s)
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
            job.error = BUSY_MESSAGE
            job.finished_at = datetime.now(UTC).isoformat()
            result["kinds"][job.kind] = _kind_result(plan, job, "skipped", 0, "busy")
            continue

        from_dt, to_dt = plan.ranges[job.kind]
        async with lock:
            job.status = "running"
            job.started_at = datetime.now(UTC).isoformat()
            try:
                run = service.run_backfill if plan.respect_coverage else service.run_incremental
                outcome: BackfillResult = await run(
                    connector=connector,
                    user_id=user_id,
                    kind=job.kind,
                    from_date=from_dt,
                    to_date=to_dt,
                    throttle_seconds=settings.garmin_backfill_throttle_seconds,
                    # updates the in-memory job directly so GET /api/sync/status shows
                    # real progress mid-run instead of a jump to windows_total at the end
                    on_progress=_make_on_progress(job),
                    # requested range is an upper bound; already-covered days are skipped
                    on_windows_total=_make_on_windows_total(job),
                )
                await session.commit()
                job.status = "done"
                job.windows_processed = outcome.windows_processed
                if outcome.fetched_from is not None:
                    fetched_froms.append(outcome.fetched_from)
                result["kinds"][job.kind] = _kind_result(
                    plan, job, "done", outcome.windows_processed, None
                )
            except Exception:
                await session.rollback()
                logger.exception("Garmin sync of %s failed for user %s", job.kind, user_id)
                job.status = "failed"
                job.error = SYNC_FAILED_MESSAGE
                result["kinds"][job.kind] = _kind_result(
                    plan, job, "failed", job.windows_processed, "sync_failed"
                )
            finally:
                job.finished_at = datetime.now(UTC).isoformat()

    await _derive_after_sync(session, user_id)

    if fetched_froms or reconciled_days:
        start = min([f.date() for f in fetched_froms] + list(reconciled_days))
        if await recompute_after_sync(session, user_id, start=start, end=date.today()):
            result["recomputed_from"] = start
    return result


def _make_fit_ingest_hook(
    session: AsyncSession, user_id: UUID, reconciled_days: set[date]
) -> PostWindowHook:
    async def _hook(
        kind: str, envelope: RawPayloadEnvelope, raw_payload_id: int, file_ids: dict[str, int]
    ) -> None:
        del raw_payload_id
        if kind == "activity_fit" and envelope.files:
            failed = await ingest_fit_files(
                session, user_id=user_id, file_ids_by_key=file_ids, files=envelope.files
            )
            await _derive_ingested(session, user_id, [k for k in file_ids if k not in failed])
        if kind == "activity_list":
            marked = await reconcile_deleted_activities(
                session, user_id=user_id, window=envelope.window, payload=envelope.payload
            )
            # same local-day rule as the HR bucket recompute (start_local::date)
            if marked:
                reconciled_days.update(
                    await local_days_of_activities(session, [i for i, _ in marked])
                )

    return _hook


async def _derive_ingested(session: AsyncSession, user_id: UUID, keys: list[str]) -> None:
    if not keys:
        return
    ids = (
        await session.execute(
            select(Activity.id).where(Activity.user_id == user_id, Activity.external_id.in_(keys))
        )
    ).scalars()
    await derive_pending(session, user_id=user_id, activity_ids=list(ids))


async def _derive_after_sync(session: AsyncSession, user_id: UUID) -> None:
    # catches a raised ACTIVITY_DERIVED_ALGO_VERSION and activities never derived
    try:
        await derive_pending(session, user_id=user_id)
        await session.commit()
    except Exception:
        await session.rollback()
        logger.exception("Activity derivation after sync failed for user %s", user_id)


async def recompute_after_sync(
    session: AsyncSession, user_id: UUID, *, start: date, end: date
) -> bool:
    # derived tables are best-effort: a failure here must not flip the finished sync jobs
    try:
        await recompute_daily_tables(session, user_id, start, end)
        return True
    except Exception:
        await session.rollback()
        logger.exception("Metric recompute after backfill failed for user %s", user_id)
        return False


def _kind_result(
    plan: GarminSyncPlan, job: SyncJob, status: str, windows: int, error_code: str | None
) -> KindResult:
    from_dt, to_dt = plan.ranges.get(job.kind, (None, None))
    return {
        "status": status,
        "windows_processed": windows,
        "from": from_dt.date().isoformat() if from_dt else job.from_date,
        "to": to_dt.date().isoformat() if to_dt else job.to_date,
        "error_code": error_code,
    }


def _make_on_progress(job: SyncJob) -> Callable[[int], None]:
    # binding `job` as a parameter avoids the late-binding loop-variable gotcha (B023)
    def _on_progress(n: int) -> None:
        job.windows_processed = n

    return _on_progress


def _make_on_windows_total(job: SyncJob) -> Callable[[int], None]:
    def _on_windows_total(n: int) -> None:
        job.windows_total = n

    return _on_windows_total


async def _build_garmin_client(
    session: AsyncSession, user_id: UUID
) -> tuple[object | None, str | None]:
    try:
        # first() not scalar_one_or_none(): pre-existing duplicate rows must not raise here,
        # the bare except below would turn that into an opaque "no connection" failure
        conn_row = (
            (
                await session.execute(
                    select(Connection)
                    .where(
                        Connection.user_id == user_id,
                        Connection.connector == "garmin",
                        Connection.status.in_(["active", "reauth_required"]),
                    )
                    .order_by(Connection.connected_at.desc(), Connection.id.desc())
                )
            )
            .scalars()
            .first()
        )

        if conn_row is None:
            # info, not warning: the user simply has not connected Garmin yet
            logger.info("No active Garmin connection for user %s", user_id)
            return None, NOT_CONNECTED_MESSAGE
        if conn_row.credentials_enc is None:
            logger.warning(
                "Garmin connection %s for user %s has no stored credentials", conn_row.id, user_id
            )
            return None, NOT_CONNECTED_MESSAGE

        user_row = (
            await session.execute(select(AppUser).where(AppUser.id == user_id))
        ).scalar_one_or_none()

        if user_row is None:
            logger.warning("No app_user row for user %s while building Garmin client", user_id)
            return None, NOT_CONNECTED_MESSAGE
        if user_row.dek_wrapped is None:
            logger.warning("User %s has no wrapped DEK — cannot decrypt Garmin tokens", user_id)
            return None, NOT_CONNECTED_MESSAGE

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
            mark_reauth_required(conn_row, str(exc))
            await session.commit()
            logger.warning("Garmin token rejected for user %s: %s", user_id, exc)
            return None, REAUTH_MESSAGE

        mark_connection_healthy(conn_row)
        await session.commit()
        return garmin, None
    except Exception as exc:
        logger.warning("Garmin client build failed for user %s: %s", user_id, exc)
        return None, NOT_CONNECTED_MESSAGE
