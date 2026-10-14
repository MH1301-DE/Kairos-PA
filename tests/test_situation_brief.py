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


async def _insert_setting_and_activity(
    session: AsyncSession, user_id: UUID, *, hr_max_override: int | None, max_hr: int | None
) -> None:
    if hr_max_override is not None:
        await session.execute(
            text("INSERT INTO user_setting (user_id, hr_max_override) VALUES (:u, :hr)"),
            {"u": str(user_id), "hr": hr_max_override},
        )
    if max_hr is not None:
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at, max_hr) "
                "VALUES (:u, 'brief-1', now() - interval '10 days', :m)"
            ),
            {"u": str(user_id), "m": max_hr},
        )
    await session.commit()


@pytest.mark.asyncio
async def test_brief_warns_when_measured_max_exceeds_hr_max(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await _insert_setting_and_activity(session, user_id, hr_max_override=214, max_hr=219)

    brief = await build_situation_brief(
        session, user_id=user_id, now=datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    )

    assert "HFmax: gemessen 219 bpm, eingetragen 214 – prüfen" in brief


@pytest.mark.asyncio
async def test_brief_says_hr_max_missing(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    brief = await build_situation_brief(
        session, user_id=user_id, now=datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    )

    assert "HFmax fehlt (Einstellungen)" in brief


@pytest.mark.asyncio
async def test_brief_has_no_hr_max_line_without_warning(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await _insert_setting_and_activity(session, user_id, hr_max_override=214, max_hr=190)

    brief = await build_situation_brief(
        session, user_id=user_id, now=datetime(2026, 8, 1, 9, 0, tzinfo=UTC)
    )

    assert "HFmax" not in brief
