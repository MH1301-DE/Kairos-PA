from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import JSONValue, Window


async def reconcile_deleted_activities(
    session: AsyncSession, *, user_id: UUID, window: Window, payload: JSONValue
) -> list[tuple[int, datetime | None]]:
    if not isinstance(payload, list):
        return []
    # a malformed entry means the page is untrustworthy; never soft-delete on it
    if not all(isinstance(i, dict) and i.get("activityId") is not None for i in payload):
        return []
    present = [str(item["activityId"]) for item in payload if isinstance(item, dict)]
    result = await session.execute(
        text(
            "UPDATE activity SET deleted_at = now(), deleted_reason = 'garmin_sync' "
            "WHERE user_id = :uid AND deleted_at IS NULL AND start_local IS NOT NULL "
            "AND start_local::date IN (:d0, :d1) AND NOT (external_id = ANY(:present)) "
            "RETURNING id, start_at"
        ),
        {
            "uid": str(user_id),
            "d0": window.start.date(),
            "d1": window.end.date(),
            "present": present,
        },
    )
    return sorted((int(r[0]), r[1]) for r in result.all())
