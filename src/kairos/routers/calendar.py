from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.calendar.free_time import BusyBlock, CalendarPrefs, compute_free_blocks
from kairos.db.models import UserSetting
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.calendar_event import CalendarEventRepository

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/events")
async def list_events(
    from_: date = Query(alias="from"),
    to: date = Query(),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, _to_utc(from_), _to_utc(to))
    return {
        "events": [
            {
                "id": str(e.id),
                "summary": e.summary,
                "description": e.description,
                "location": e.location,
                "start_at": e.start_at.isoformat(),
                "end_at": e.end_at.isoformat(),
                "all_day": e.all_day,
                "status": e.status,
                "source": e.source,
            }
            for e in events
        ]
    }


@router.get("/free-slots")
async def free_slots(
    duration_minutes: int,
    from_: date = Query(alias="from"),
    to: date = Query(),
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, _to_utc(from_), _to_utc(to))
    prefs_row = await _load_prefs(session, user_id)

    busy = [BusyBlock(start=e.start_at, end=e.end_at) for e in events]
    prefs = CalendarPrefs(
        work_hours_start=prefs_row["work_hours_start"],
        work_hours_end=prefs_row["work_hours_end"],
        buffer_minutes=prefs_row["calendar_buffer_minutes"],
        min_free_minutes=prefs_row["min_free_block_minutes"],
    )
    blocks = compute_free_blocks(busy, _to_utc(from_), _to_utc(to), prefs)
    slots = [b for b in blocks if (b.end - b.start).total_seconds() / 60 >= duration_minutes]
    return {"slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots]}


async def _load_prefs(session: AsyncSession, user_id: UUID) -> dict:
    row = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return {
            "work_hours_start": None,
            "work_hours_end": None,
            "calendar_buffer_minutes": 15,
            "min_free_block_minutes": 30,
        }
    return {
        "work_hours_start": row.work_hours_start,
        "work_hours_end": row.work_hours_end,
        "calendar_buffer_minutes": row.calendar_buffer_minutes,
        "min_free_block_minutes": row.min_free_block_minutes,
    }


def _to_utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)
