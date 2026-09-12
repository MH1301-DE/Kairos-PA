from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.situation_brief import build_situation_brief
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.goals import SqlGoalRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Max Mustermann', :sub, 'Europe/Berlin', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_brief_degrades_gracefully_with_no_data(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    brief = await build_situation_brief(session, user_id=user_id, now=now)

    assert "AKTUELLE LAGE · Max Mustermann ·" in brief
    assert "Datenstand: Garmin nicht verbunden · Google Cal nicht verbunden" in brief
    assert "HRV: nicht genug Daten" in brief
    assert "nicht genug Daten" in brief  # Belastung block
    assert "Heute keine Termine" in brief
    assert "Morgen: frei" in brief
    assert "Aktive Ziele: keine" in brief


@pytest.mark.asyncio
async def test_brief_includes_calendar_events_and_active_goals(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    goal_repo = SqlGoalRepository(session=session)
    await goal_repo.create(
        user_id=user_id, title="Halbmarathon Berlin", target_value=None, target_unit=None,
        target_date=date(2026, 11, 15), notes=None,
    )
    calendar_repo = CalendarEventRepository(session)
    await calendar_repo.upsert_kairos_event(
        user_id, "google_calendar", "evt-brief-1", "Long Run",
        datetime(2026, 8, 1, 10, 0, tzinfo=UTC), datetime(2026, 8, 1, 11, 0, tzinfo=UTC), None,
    )
    await session.commit()

    now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    brief = await build_situation_brief(session, user_id=user_id, now=now)

    assert "Heute 1 Termine, erster 10:00, letzter endet 11:00" in brief
    assert "Halbmarathon Berlin (2026-11-15)" in brief


@pytest.mark.asyncio
async def test_brief_reports_connected_status(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.execute(
        text(
            "INSERT INTO connection (id, user_id, connector, status, config) "
            "VALUES (:id, :uid, 'garmin', 'active', '{}'::jsonb)"
        ),
        {"id": str(uuid4()), "uid": str(user_id)},
    )
    await session.commit()

    now = datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    brief = await build_situation_brief(session, user_id=user_id, now=now)

    assert "Garmin ✓" in brief
    assert "Google Cal nicht verbunden" in brief
