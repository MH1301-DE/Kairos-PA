# tests/test_calendar_integration.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.db.rls import install_rls_listener
from kairos.repositories.calendar_event import CalendarEventRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_kairos_created_event_does_not_duplicate_on_next_sync(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)

    # Step 1: Kairos creates an event (simulating what the POST /api/calendar/events
    # handler does — call the Google client directly, then upsert the canonical row).
    mock_client = MagicMock()
    mock_client.create_event.return_value = {"id": "google-evt-round-trip"}
    connector = GoogleCalendarConnector(mock_client)
    created = mock_client.create_event(
        "primary",
        summary="Proposed Training",
        start=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        end=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        description=None,
    )
    del connector  # not exercised in this path — matches Task 9's direct-client-call choice

    repo = CalendarEventRepository(session)
    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        str(created["id"]),
        "Proposed Training",
        datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()

    # Step 2: a later sync poll fetches from Google and sees the SAME event echoed back
    # (this is what google_calendar's real sync would receive from Google's API).
    mock_client.list_events.return_value = {
        "items": [
            {
                "id": "google-evt-round-trip",
                "summary": "Proposed Training",
                "status": "confirmed",
                "start": {"dateTime": "2026-05-01T09:00:00+00:00"},
                "end": {"dateTime": "2026-05-01T10:00:00+00:00"},
            }
        ],
        "nextSyncToken": "tok-1",
    }
    sync_connector = GoogleCalendarConnector(mock_client)
    from kairos.connectors.types import Window

    envelope = sync_connector.fetch(
        user_id,
        "events",
        Window(start=datetime(2026, 4, 25, tzinfo=UTC), end=datetime(2026, 5, 8, tzinfo=UTC)),
    )
    records = sync_connector.normalize("events", envelope.payload)
    written = await repo.upsert_from_records(user_id, "google_calendar", records)
    await session.commit()

    assert written == 1  # upsert ran, but as an UPDATE not an INSERT

    events = await repo.list_between(
        user_id, datetime(2026, 4, 30, tzinfo=UTC), datetime(2026, 5, 2, tzinfo=UTC)
    )
    assert len(events) == 1  # no duplicate row
    assert events[0].source == "kairos"  # source flag from the original create is preserved
