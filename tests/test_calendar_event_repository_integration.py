from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.rls import install_rls_listener
from kairos.repositories.calendar_event import CalendarEventRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_upsert_from_records_then_list_between(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="evt-1",
            data={
                "summary": "Long Run",
                "description": None,
                "location": None,
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "all_day": False,
                "status": "confirmed",
            },
            occurred_at=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        )
    ]
    written = await repo.upsert_from_records(user_id, "google_calendar", records)
    await session.commit()
    assert written == 1

    events = await repo.list_between(
        user_id, datetime(2026, 2, 28, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert len(events) == 1
    assert events[0].summary == "Long Run"
    assert events[0].source == "external"


@pytest.mark.asyncio
async def test_upsert_from_records_is_idempotent_on_external_id(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    def _record(summary: str) -> CanonicalRecord:
        return CanonicalRecord(
            record_type="calendar_event",
            external_id="evt-dedup",
            data={
                "summary": summary,
                "description": None,
                "location": None,
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "all_day": False,
                "status": "confirmed",
            },
            occurred_at=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        )

    await repo.upsert_from_records(user_id, "google_calendar", [_record("First Title")])
    await session.commit()
    await repo.upsert_from_records(user_id, "google_calendar", [_record("Renamed Title")])
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 2, 28, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert len(events) == 1
    assert events[0].summary == "Renamed Title"


@pytest.mark.asyncio
async def test_upsert_kairos_event_then_dedup_against_sync(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        "kairos-created-evt",
        "Proposed Slot",
        datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()

    # a later sync poll sees the same event echoed back by Google
    record = CanonicalRecord(
        record_type="calendar_event",
        external_id="kairos-created-evt",
        data={
            "summary": "Proposed Slot",
            "description": None,
            "location": None,
            "start_at": "2026-04-01T09:00:00+00:00",
            "end_at": "2026-04-01T10:00:00+00:00",
            "all_day": False,
            "status": "confirmed",
        },
        occurred_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
    )
    await repo.upsert_from_records(user_id, "google_calendar", [record])
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 3, 31, tzinfo=UTC), datetime(2026, 4, 2, tzinfo=UTC)
    )
    assert len(events) == 1  # no duplicate row


@pytest.mark.asyncio
async def test_mark_deleted_excludes_from_list_between(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        "evt-to-delete",
        "Will be cancelled",
        datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()
    await repo.mark_deleted(user_id, "google_calendar", "evt-to-delete")
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 4, 30, tzinfo=UTC), datetime(2026, 5, 2, tzinfo=UTC)
    )
    assert events == []
