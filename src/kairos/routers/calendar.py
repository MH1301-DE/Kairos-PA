from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.calendar.free_time import BusyBlock, CalendarPrefs, FreeBlock, compute_free_blocks
from kairos.calendar.sync import build_google_calendar_client as _build_google_calendar_client
from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.db.models import CalendarEvent, UserSetting
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.calendar_event import CalendarEventRepository

router = APIRouter(prefix="/api/calendar", tags=["calendar"])

# cap per free block so a multi-day block can't generate hundreds of candidates
_MAX_SLOTS_PER_BLOCK = 20


def _slice_into_slots(blocks: list[FreeBlock], duration_minutes: int) -> list[FreeBlock]:
    step = timedelta(minutes=duration_minutes)
    slots: list[FreeBlock] = []
    for block in blocks:
        cursor = block.start
        count = 0
        while cursor + step <= block.end and count < _MAX_SLOTS_PER_BLOCK:
            slots.append(FreeBlock(start=cursor, end=cursor + step))
            cursor += step
            count += 1
    return slots


class CreateEventRequest(BaseModel):
    summary: str
    start_at: datetime
    end_at: datetime
    description: str | None = None


@router.get("/events")
async def list_events(
    from_: date = Query(alias="from"),
    to: date = Query(),
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, _to_utc(from_), _to_utc(to))
    return {"events": [_event_to_dict(e) for e in events]}


@router.get("/free-slots")
async def free_slots(
    duration_minutes: int,
    from_: date = Query(alias="from"),
    to: date = Query(),
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
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
    slots = _slice_into_slots(blocks, duration_minutes)
    return {"slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots]}


@router.post("/events", status_code=201)
async def create_event(
    req: CreateEventRequest,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    created = await _create_calendar_event(session, user_id, req)
    await session.commit()
    return created


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    confirm: bool = Query(default=False),
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    await _delete_calendar_event(session, user_id, event_id, confirm)
    await session.commit()


# plain functions (not FastAPI endpoints) so src/kairos/agent/tools.py's
# propose_calendar_event/delete_calendar_event handlers can call the exact same
# logic instead of duplicating it -- no behavior change from the router's point
# of view, both endpoints above just forward into these unchanged.
# They never commit: the agent's confirm endpoint must hold its row lock until its own commit.


async def _create_calendar_event(
    session: AsyncSession, user_id: UUID, req: CreateEventRequest
) -> dict[str, Any]:
    client = await _build_google_calendar_client(session, user_id)
    if client is None:
        raise HTTPException(status_code=503, detail="no_active_google_calendar_connection")

    connector = GoogleCalendarConnector(client)
    created = await asyncio.to_thread(
        client.create_event,
        "primary",
        summary=req.summary,
        start=req.start_at,
        end=req.end_at,
        description=req.description,
    )
    # Google returns {"error": {...}} with no "id" on a 4xx — surface it instead of a KeyError
    if isinstance(created, dict) and "error" in created:
        raise HTTPException(
            status_code=502,
            detail=f"google_calendar_create_failed:{created['error']}",
        )
    del connector  # write_back not used here; single-record path calls the client directly

    repo = CalendarEventRepository(session)
    row = await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        str(created["id"]),
        req.summary,
        req.start_at,
        req.end_at,
        req.description,
    )
    return _event_to_dict(row)


async def _delete_calendar_event(
    session: AsyncSession, user_id: UUID, event_id: UUID, confirm: bool
) -> None:
    repo = CalendarEventRepository(session)
    event = await repo.get_by_id(user_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    # events synced in from the user's real Google Calendar need an explicit
    # confirmation, both from a human accidentally misclicking and from a
    # future agent tool -- enforced here so the API itself can't be bypassed,
    # not just the frontend's confirm() dialog. Kairos' own proposed events
    # carry no such risk and delete immediately, same as before.
    if event.source == "external" and not confirm:
        raise HTTPException(
            status_code=409,
            detail={
                "needs_confirmation": True,
                "summary": event.summary,
                "start_at": event.start_at.isoformat(),
            },
        )

    client = await _build_google_calendar_client(session, user_id)
    if client is not None:
        await asyncio.to_thread(client.delete_event, event.calendar_id, event.external_id)
    await repo.mark_deleted(user_id, event.connector, event.external_id)


def _event_to_dict(e: CalendarEvent) -> dict[str, Any]:
    return {
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


async def _load_prefs(session: AsyncSession, user_id: UUID) -> dict[str, Any]:
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
