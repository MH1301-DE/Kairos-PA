"""HTTP-free calendar sync core.

Transition until CalDAV spec AP 3: ``sync_google_calendar`` has the signature and result of
the later ``sync_calendar(session, user_id, provider_id, window)``, minus ``provider_id`` and
minus the deletion reconcile.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, date, datetime, timedelta
from typing import TypedDict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.crypto import decrypt, kek_from_settings, unwrap_dek
from kairos.config import settings
from kairos.connectors.google_calendar.client import GoogleCalendarClient, TokenExpired
from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.connectors.types import Window
from kairos.db.models import AppUser, Connection
from kairos.ingestion.connection_status import mark_connection_healthy, mark_reauth_required
from kairos.ingestion.job_registry import SyncBusy, get_registry
from kairos.repositories.calendar_event import CalendarEventRepository

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_COOLDOWN_SECONDS = 60.0
_UNAVAILABLE_MESSAGE = "Kalender nicht erreichbar"


class SyncResult(TypedDict):
    fetched: int
    upserted: int
    cancelled: int
    failed_calendars: list[str]
    error_code: str | None  # "reauth_required" | "unavailable" | None


class CalendarNotConnected(Exception):
    def __init__(self, provider: str) -> None:
        super().__init__(f"{provider} not connected")
        self.provider = provider


def default_window(today: date | None = None) -> Window:
    d = today or date.today()
    return Window(
        start=datetime.combine(d - timedelta(days=7), datetime.min.time(), UTC),
        end=datetime.combine(d + timedelta(days=83), datetime.min.time(), UTC),
    )


async def sync_google_calendar(
    session: AsyncSession, user_id: UUID, window: Window | None = None
) -> SyncResult:
    # expects install_rls_listener(session, user_id); commits itself
    lock = get_registry().get_lock(user_id, "google_calendar", "events")
    if lock.locked():
        raise SyncBusy()
    async with lock:
        conn_row = await _active_connection(session, user_id)
        client = await build_google_calendar_client(session, user_id)
        if conn_row is None or client is None:
            raise CalendarNotConnected("google_calendar")

        connector = GoogleCalendarConnector(client)
        result: SyncResult = {
            "fetched": 0,
            "upserted": 0,
            "cancelled": 0,
            "failed_calendars": [],
            "error_code": None,
        }
        try:
            envelope = await asyncio.to_thread(
                connector.fetch, user_id, "events", window or default_window()
            )
            records = connector.normalize("events", envelope.payload)
            result["upserted"] = await CalendarEventRepository(session).upsert_from_records(
                user_id, "google_calendar", records
            )
            result["fetched"] = len(records)
            result["cancelled"] = sum(
                1
                for r in records
                if isinstance(r.data, dict) and r.data.get("status") == "cancelled"
            )
            mark_connection_healthy(conn_row)
        except TokenExpired:
            await session.rollback()
            logger.warning("Google Calendar token rejected for user %s", user_id)
            mark_reauth_required(conn_row, "Google-Kalender-Zugriff abgelaufen")
            result["error_code"] = "reauth_required"
            result["failed_calendars"] = ["primary"]
        except Exception:
            await session.rollback()
            logger.exception("Google Calendar sync failed for user %s", user_id)
            conn_row.last_error = _UNAVAILABLE_MESSAGE
            result["error_code"] = "unavailable"
            result["failed_calendars"] = ["primary"]
        await session.commit()
        return result


async def _active_connection(session: AsyncSession, user_id: UUID) -> Connection | None:
    # first() not scalar_one_or_none(): pre-existing duplicate rows must not raise here
    return (
        (
            await session.execute(
                select(Connection)
                .where(
                    Connection.user_id == user_id,
                    Connection.connector == "google_calendar",
                    Connection.status.in_(["active", "reauth_required"]),
                )
                .order_by(Connection.connected_at.desc(), Connection.id.desc())
            )
        )
        .scalars()
        .first()
    )


async def build_google_calendar_client(
    session: AsyncSession, user_id: UUID
) -> GoogleCalendarClient | None:
    try:
        conn_row = await _active_connection(session, user_id)
        if conn_row is None or conn_row.credentials_enc is None:
            return None

        user_row = (
            await session.execute(select(AppUser).where(AppUser.id == user_id))
        ).scalar_one_or_none()

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
        logger.exception("Google Calendar client build failed for user %s", user_id)
        return None
