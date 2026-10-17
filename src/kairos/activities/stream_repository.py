from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.activities.streams import STREAM_CHANNELS, StreamSet
from kairos.db.models import ActivityStream, ActivityStreamAxis

STREAM_ALGO_VERSION = 1

_STORAGE = {spec.code: spec.storage for spec in STREAM_CHANNELS}


@dataclass(frozen=True)
class LoadedStream:
    start_at: datetime
    t_offset_s: list[int]
    channels: dict[str, list[float | None]]
    source: str


async def replace_streams(
    session: AsyncSession,
    *,
    user_id: uuid.UUID,
    activity_id: int,
    streams: StreamSet,
    algo_version: int,
) -> int:
    length = len(streams.t_offset_s)
    for code, values in streams.channels.items():
        if code not in _STORAGE:
            raise ValueError(f"unknown stream channel: {code}")
        if len(values) != length:
            raise ValueError(f"channel {code} has {len(values)} values, axis has {length}")

    await session.execute(delete(ActivityStream).where(ActivityStream.activity_id == activity_id))
    await session.execute(
        delete(ActivityStreamAxis).where(ActivityStreamAxis.activity_id == activity_id)
    )
    session.add(
        ActivityStreamAxis(
            activity_id=activity_id,
            user_id=user_id,
            start_at=streams.start_at,
            t_offset_s=streams.t_offset_s,
            source=streams.source,
            algo_version=algo_version,
        )
    )
    await session.flush()
    if streams.channels:
        await session.execute(
            insert(ActivityStream),
            [
                {
                    "activity_id": activity_id,
                    "channel": code,
                    "user_id": user_id,
                    "v4": values if _STORAGE[code] == "v4" else None,
                    "v8": values if _STORAGE[code] == "v8" else None,
                }
                for code, values in streams.channels.items()
            ],
        )
    return len(streams.channels)


async def load_stream(
    session: AsyncSession, *, activity_id: int, channels: Sequence[str] | None = None
) -> LoadedStream | None:
    axis = (
        await session.execute(
            select(ActivityStreamAxis).where(ActivityStreamAxis.activity_id == activity_id)
        )
    ).scalar_one_or_none()
    if axis is None:
        return None
    query = select(ActivityStream).where(ActivityStream.activity_id == activity_id)
    if channels is not None:
        query = query.where(ActivityStream.channel.in_(channels))
    rows = (await session.execute(query.order_by(ActivityStream.channel))).scalars().all()
    return LoadedStream(
        start_at=axis.start_at,
        t_offset_s=list(axis.t_offset_s),
        channels={r.channel: list(r.v4 if r.v4 is not None else r.v8 or []) for r in rows},
        source=axis.source,
    )
