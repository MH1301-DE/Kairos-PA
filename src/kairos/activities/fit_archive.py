from __future__ import annotations

import gzip
import json
import logging
from collections.abc import Sequence
from datetime import timedelta
from typing import Any, Literal
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import build_streams
from kairos.connectors.garmin.fit_decoder import decode_fit_zip
from kairos.connectors.types import RawFile
from kairos.db.models import Activity, RawPayload

logger = logging.getLogger(__name__)

FitSource = Literal["fit_zip", "fit_json"]

# activity_fit day windows are UTC days but Garmin filters by local start date
_JSON_FALLBACK_SLACK = timedelta(days=2)


async def ingest_fit_files(
    session: AsyncSession,
    *,
    user_id: UUID,
    file_ids_by_key: dict[str, int],
    files: Sequence[RawFile],
) -> list[str]:
    failed: list[str] = []
    for file in files:
        payload_id = file_ids_by_key.get(file.key)
        if payload_id is None:
            continue
        activity_id = (
            await session.execute(
                select(Activity.id).where(
                    Activity.user_id == user_id, Activity.external_id == file.key
                )
            )
        ).scalar_one_or_none()
        if activity_id is None:
            continue  # activity_list must run before activity_fit
        try:
            async with session.begin_nested():
                await session.execute(
                    update(Activity)
                    .where(Activity.id == activity_id)
                    .values(fit_payload_id=payload_id)
                )
                messages = _decode_strict(file.content)
                streams = build_streams(messages["record_mesgs"], source="fit_zip")
                if streams is not None:
                    await replace_streams(
                        session,
                        user_id=user_id,
                        activity_id=activity_id,
                        streams=streams,
                        algo_version=STREAM_ALGO_VERSION,
                    )
        except Exception as exc:
            logger.warning("FIT ingest failed for activity %s: %s", file.key, exc)
            failed.append(file.key)
    return failed


async def load_fit_messages(
    session: AsyncSession, *, activity: Activity
) -> tuple[dict[str, Any], FitSource] | None:
    if activity.fit_payload_id is not None:
        content = (
            await session.execute(
                select(RawPayload.payload_gzip).where(RawPayload.id == activity.fit_payload_id)
            )
        ).scalar_one_or_none()
        if content is not None:
            try:
                return _decode_strict(content), "fit_zip"
            except Exception as exc:
                logger.warning(
                    "FIT zip for activity %s not decodable, trying JSON: %s",
                    activity.external_id,
                    exc,
                )
    return await _load_from_json(session, activity)


def _decode_strict(content: bytes) -> dict[str, Any]:
    messages = decode_fit_zip(content, strict=True)
    if not messages.get("record_mesgs"):
        raise ValueError("FIT file has no record messages")
    return messages


async def _load_from_json(
    session: AsyncSession, activity: Activity
) -> tuple[dict[str, Any], FitSource] | None:
    stmt = select(RawPayload.payload_gzip).where(
        RawPayload.user_id == activity.user_id,
        RawPayload.connector == "garmin",
        RawPayload.kind == "activity_fit",
        RawPayload.payload_format == "json_gzip",
    )
    if activity.start_at is not None:
        stmt = stmt.where(
            RawPayload.window_start >= activity.start_at - _JSON_FALLBACK_SLACK,
            RawPayload.window_start <= activity.start_at + _JSON_FALLBACK_SLACK,
        )
    stmt = stmt.order_by(RawPayload.fetched_at.desc(), RawPayload.id.desc())
    for blob in (await session.execute(stmt)).scalars():
        if blob is None:
            continue
        payload = json.loads(gzip.decompress(blob))
        entries = payload.get("activities") if isinstance(payload, dict) else None
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get("activity_id") != activity.external_id:
                continue
            records = entry.get("records")
            if not records:
                continue
            return {
                "record_mesgs": records,
                "session_mesgs": entry.get("sessions") or [],
                "lap_mesgs": entry.get("laps") or [],
            }, "fit_json"
    return None
