from __future__ import annotations

import asyncio
import gzip
import importlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.derive.service import derive_pending, pending_activity_ids
from kairos.activities.fit_archive import ingest_fit_files, load_fit_messages
from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import build_streams
from kairos.connectors.garmin.normalize import normalize_payload
from kairos.connectors.types import CanonicalRecord, RawFile
from kairos.db.models import Activity, RawPayload
from kairos.repositories.canonical import SqlCanonicalRepository
from kairos.repositories.raw_payload import SqlRawPayloadRepository

logger = logging.getLogger(__name__)

_COMMIT_EVERY = 10
_MAX_CONSECUTIVE_FAILURES = 3
# activity_list windows are keyed by Garmin's local start date, not the UTC date
_LIST_WINDOW_SLACK = timedelta(days=2)


@dataclass
class ReprocessResult:
    activities_total: int = 0
    streams_written: int = 0
    from_zip: int = 0
    from_json: int = 0
    no_data: list[str] = field(default_factory=list)
    fetch_failed: list[dict[str, str]] = field(default_factory=list)
    fetched: int = 0
    aborted_reason: str | None = None
    derived: int = 0
    derive_failed: list[str] = field(default_factory=list)


async def reprocess_activities(
    session: AsyncSession,
    *,
    user_id: UUID,
    from_date: date | None,
    to_date: date | None,
    activity_ids: list[int] | None,
    refetch_fit: bool,
    garmin: object | None,
    pause_s: float,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    on_progress: Callable[[int, int], None] | None = None,
) -> ReprocessResult:
    if refetch_fit and garmin is None:
        raise ValueError("refetch_fit requires a Garmin client")
    lower = _utc_midnight(from_date) if from_date is not None else None
    upper = _utc_midnight(to_date + timedelta(days=1)) if to_date is not None else None

    await _renormalize_activity_list(
        session, user_id=user_id, lower=lower, upper=upper, activity_ids=activity_ids
    )
    await session.commit()

    stmt = select(Activity).where(Activity.user_id == user_id)
    if lower is not None:
        stmt = stmt.where(Activity.start_at >= lower)
    if upper is not None:
        stmt = stmt.where(Activity.start_at < upper)
    if activity_ids is not None:
        stmt = stmt.where(Activity.id.in_(activity_ids))
    activities = list(
        (await session.execute(stmt.order_by(Activity.start_at, Activity.id))).scalars()
    )

    result = ReprocessResult(activities_total=len(activities))
    total = len(activities)
    if on_progress is not None:
        on_progress(0, total)
    downloader = _Downloader(garmin, pause_s=pause_s, sleep=sleep) if refetch_fit else None
    raw_repo = SqlRawPayloadRepository(session=session)

    for done, activity in enumerate(activities, start=1):
        handled = False
        if downloader is not None and activity.fit_payload_id is None:
            handled = await _refetch(session, raw_repo, downloader, activity, result)
        if not handled:
            await _rebuild_from_archive(session, activity, result)
        if done % _COMMIT_EVERY == 0:
            await session.commit()
        if on_progress is not None:
            on_progress(done, total)
    if downloader is not None:
        result.aborted_reason = downloader.aborted_reason
    await session.commit()

    first = [a.id for a in activities]
    # the second pass catches activities outside the range with an outdated algo_version
    in_range = set(first)
    stale = [i for i in await pending_activity_ids(session, user_id=user_id) if i not in in_range]
    failed_ids: list[int] = []
    for ids in (first, stale):
        for outcome in await derive_pending(session, user_id=user_id, activity_ids=ids):
            if outcome.status == "failed":
                failed_ids.append(outcome.activity_id)
            elif outcome.status in ("derived", "summary_only"):
                result.derived += 1
        await session.commit()
    if failed_ids:
        external = dict(
            (
                await session.execute(
                    select(Activity.id, Activity.external_id).where(Activity.id.in_(failed_ids))
                )
            )
            .tuples()
            .all()
        )
        result.derive_failed = [external.get(i, str(i)) for i in failed_ids]
    return result


async def _renormalize_activity_list(
    session: AsyncSession,
    *,
    user_id: UUID,
    lower: datetime | None,
    upper: datetime | None,
    activity_ids: list[int] | None,
) -> None:
    wanted: set[str] | None = None
    if activity_ids is not None:
        wanted = set(
            (
                await session.execute(
                    select(Activity.external_id).where(
                        Activity.user_id == user_id, Activity.id.in_(activity_ids)
                    )
                )
            ).scalars()
        )
    stmt = select(RawPayload.id, RawPayload.payload_gzip).where(
        RawPayload.user_id == user_id,
        RawPayload.connector == "garmin",
        RawPayload.kind == "activity_list",
        RawPayload.payload_format == "json_gzip",
    )
    if lower is not None:
        stmt = stmt.where(RawPayload.window_end >= lower - _LIST_WINDOW_SLACK)
    if upper is not None:
        stmt = stmt.where(RawPayload.window_start < upper + _LIST_WINDOW_SLACK)
    # ascending, so the newest payload of an activity is written last and wins
    stmt = stmt.order_by(RawPayload.fetched_at, RawPayload.id)
    canonical = SqlCanonicalRepository(session, revive_deleted=False)
    for payload_id, blob in (await session.execute(stmt)).all():
        if blob is None:
            continue
        records = [
            r
            for r in normalize_payload(
                kind="activity_list", payload=json.loads(gzip.decompress(blob))
            )
            if _in_range(r, lower, upper) and (wanted is None or r.external_id in wanted)
        ]
        if records:
            await canonical.upsert_many(
                user_id=user_id,
                connector_id="garmin",
                kind="activity_list",
                records=records,
                raw_payload_id=payload_id,
            )


def _in_range(record: CanonicalRecord, lower: datetime | None, upper: datetime | None) -> bool:
    if record.occurred_at is None:
        return lower is None and upper is None
    if lower is not None and record.occurred_at < lower:
        return False
    return upper is None or record.occurred_at < upper


class _Downloader:
    def __init__(
        self, garmin: Any, *, pause_s: float, sleep: Callable[[float], Awaitable[None]]
    ) -> None:
        self._garmin = garmin
        self._pause_s = pause_s
        self._sleep = sleep
        self._attempted = False
        self._gc = importlib.import_module("garminconnect")
        self.aborted_reason: str | None = None
        self.consecutive_failures = 0

    async def download(self, external_id: str) -> bytes:
        if self._attempted and self._pause_s > 0:
            await self._sleep(self._pause_s)
        self._attempted = True
        try:
            content: bytes = await asyncio.to_thread(
                self._garmin.download_activity,
                external_id,
                dl_fmt=self._gc.Garmin.ActivityDownloadFormat.ORIGINAL,
            )
        except self._gc.GarminConnectTooManyRequestsError:
            self.aborted_reason = "rate_limited"
            raise
        except self._gc.GarminConnectAuthenticationError:
            self.aborted_reason = "auth"
            raise
        except Exception:
            self.consecutive_failures += 1
            if self.consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                self.aborted_reason = "consecutive_failures"
            raise
        self.consecutive_failures = 0
        return content


async def _refetch(
    session: AsyncSession,
    raw_repo: SqlRawPayloadRepository,
    downloader: _Downloader,
    activity: Activity,
    result: ReprocessResult,
) -> bool:
    if downloader.aborted_reason is not None:
        return False
    try:
        content = await downloader.download(activity.external_id)
    except Exception as exc:
        if downloader.aborted_reason in ("rate_limited", "auth"):
            logger.warning("FIT refetch aborted (%s): %s", downloader.aborted_reason, exc)
        else:
            result.fetch_failed.append({"activity_id": activity.external_id, "reason": str(exc)})
        return False
    result.fetched += 1
    file = RawFile(
        kind="activity_fit_file",
        key=activity.external_id,
        window_start=activity.start_at or activity.created_at,
        content=content,
        payload_format="fit_zip",
    )
    payload_id = await raw_repo.upsert_file(
        user_id=activity.user_id, connector_id="garmin", file=file
    )
    failed = await ingest_fit_files(
        session, user_id=activity.user_id, file_ids_by_key={file.key: payload_id}, files=[file]
    )
    if failed:
        return False
    result.from_zip += 1
    result.streams_written += 1
    return True


async def _rebuild_from_archive(
    session: AsyncSession, activity: Activity, result: ReprocessResult
) -> None:
    loaded = await load_fit_messages(session, activity=activity)
    streams = None
    if loaded is not None:
        messages, source = loaded
        streams = build_streams(messages["record_mesgs"], source=source)
    if loaded is None or streams is None:
        result.no_data.append(activity.external_id)
        return
    await replace_streams(
        session,
        user_id=activity.user_id,
        activity_id=activity.id,
        streams=streams,
        algo_version=STREAM_ALGO_VERSION,
    )
    result.streams_written += 1
    if source == "fit_zip":
        result.from_zip += 1
    else:
        result.from_json += 1


def _utc_midnight(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=UTC)
