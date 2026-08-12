from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.calendar.free_time import BusyBlock, CalendarPrefs, compute_free_blocks
from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.db.models import UserSetting
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.routers.sync import _build_google_calendar_client

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


class CreateEventRequest(BaseModel):
    summary: str
    start_at: datetime
    end_at: datetime
    description: str | None = None


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


@router.post("/events", status_code=201)
async def create_event(
    req: CreateEventRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    client = await _build_google_calendar_client(session, user_id)
    if client is None:
        raise HTTPException(status_code=503, detail="no_active_google_calendar_connection")

    connector = GoogleCalendarConnector(client)
    created = client.create_event(
        "primary",
        summary=req.summary,
        start=req.start_at,
        end=req.end_at,
        description=req.description,
    )
    del connector  # write_back not used here; single-record path calls the client directly

    repo = CalendarEventRepository(session)
    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        str(created["id"]),
        req.summary,
        req.start_at,
        req.end_at,
        req.description,
    )
    await session.commit()
    return {
        "summary": req.summary,
        "start_at": req.start_at.isoformat(),
        "end_at": req.end_at.isoformat(),
        "description": req.description,
    }


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    event = await repo.get_by_id(user_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    client = await _build_google_calendar_client(session, user_id)
    if client is not None:
        client.delete_event(event.calendar_id, event.external_id)
    await repo.mark_deleted(user_id, event.connector, event.external_id)
    await session.commit()


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
