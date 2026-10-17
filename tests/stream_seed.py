from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.stream_repository import STREAM_ALGO_VERSION, replace_streams
from kairos.activities.streams import StreamSet


async def seed_hr_stream(
    session: AsyncSession,
    *,
    user_id: UUID,
    activity_id: int,
    start_at: datetime,
    values: list[float | None],
    t_offset_s: list[int] | None = None,
) -> None:
    offsets = list(range(len(values))) if t_offset_s is None else t_offset_s
    await replace_streams(
        session,
        user_id=user_id,
        activity_id=activity_id,
        streams=StreamSet(
            start_at=start_at, t_offset_s=offsets, channels={"hr": values}, source="fit_zip"
        ),
        algo_version=STREAM_ALGO_VERSION,
    )
