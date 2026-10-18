from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.dispatcher import _summarize
from kairos.agent.tools import (
    knowledge_lookup_handler,
    plan_commit_handler,
    plan_progress_handler,
    plan_propose_handler,
    reference_value_set_handler,
)
from kairos.coach import service as coach_service
from kairos.coach.history import load_history
from kairos.coach.model import week_start
from kairos.db.models import Activity, ActivitySplit, ActivityStats, Goal, Plan, PlanBlock
from kairos.repositories.coach import CoachProfileRepository, ReferenceValueRepository
from kairos.repositories.plan import PlanRepository

_PLAN_TYPE = "ausdauer-laufen-pyramidal"
_AVAILABILITY = {
    "di": {"max_min": 60, "quality": True},
    "do": {"max_min": 60, "quality": True},
    "sa": {"max_min": 60},
    "so": {"max_min": 120},
}


async def _user(session: AsyncSession) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'Europe/Berlin', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    return user_id


async def _coach_user(
    session: AsyncSession, *, goal_weeks: int | None = 16, vdot: float | None = 45.0
) -> UUID:
    user_id = await _user(session)
    await CoachProfileRepository(session).upsert(
        user_id, plan_type=_PLAN_TYPE, main_sport="laufen", availability=_AVAILABILITY
    )
    if goal_weeks is not None:
        session.add(
            Goal(
                user_id=user_id,
                title="Halbmarathon Frühjahr",
                target_date=coach_service.next_monday(date.today())
                + timedelta(weeks=goal_weeks, days=6),
            )
        )
    if vdot is not None:
        await ReferenceValueRepository(session).add(
            user_id, kind="vdot", value=vdot, measured_on=date.today(), source="manuell"
        )
    await session.commit()
    return user_id


async def _run(
    session: AsyncSession,
    user_id: UUID,
    day: date,
    *,
    distance_m: float,
    seconds: float,
    sport: str = "running",
) -> int:
    activity = Activity(
        user_id=user_id,
        external_id=str(uuid4()),
        sport=sport,
        sport_profile="running" if sport == "running" else "generic",
        start_local=datetime(day.year, day.month, day.day, 7, 0),
        distance_m=distance_m,
        duration_s=seconds,
    )
    session.add(activity)
    await session.flush()
    session.add(
        ActivityStats(
            activity_id=activity.id,
            user_id=user_id,
            sport_profile=activity.sport_profile,
            algo_version=1,
            distance_m=distance_m,
            timer_s=seconds,
            moving_s=seconds,
            quality="ok",
        )
    )
    await session.commit()
    return activity.id


def _no_calendar() -> object:
    client = MagicMock()
    client.create_event.side_effect = lambda *a, **k: {"id": f"g-{uuid4()}"}
    return patch(
        "kairos.routers.calendar._build_google_calendar_client",
        new=AsyncMock(return_value=client),
    )


@pytest.mark.asyncio
async def test_propose_without_coach_profile_explains_what_is_missing(
    session: AsyncSession,
) -> None:
    user_id = await _user(session)

    result = await plan_propose_handler(session, user_id=user_id)

    assert result["data"]["plan_id"] is None
    assert "Coach-Profil" in result["summary"]


@pytest.mark.asyncio
async def test_propose_builds_a_phased_draft_towards_the_goal(session: AsyncSession) -> None:
    user_id = await _coach_user(session)

    result = await plan_propose_handler(session, user_id=user_id)
    await session.commit()

    plan_id = UUID(result["data"]["plan_id"])
    repo = PlanRepository(session=session)
    plan = await repo.get(user_id=user_id, plan_id=plan_id)
    assert plan is not None
    assert plan.status == "draft"
    assert plan.plan_type == _PLAN_TYPE
    assert plan.goal_id is not None
    phases = await repo.list_phases(user_id=user_id, plan_id=plan_id)
    assert phases[-1].kind == "taper"
    assert phases[-1].end_date == plan.goal_date
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan_id)
    assert blocks
    assert plan.detail_until is not None
    assert all(b.day <= plan.detail_until for b in blocks)
    # blocks get local start times so the calendar shows them on the right day
    assert all(b.start_at is not None and b.phase_id is not None for b in blocks)
    assert all(b.unit_id for b in blocks)
    assert result["data"]["einheiten"]


@pytest.mark.asyncio
async def test_new_proposal_replaces_the_previous_draft(session: AsyncSession) -> None:
    user_id = await _coach_user(session)
    first = await plan_propose_handler(session, user_id=user_id)
    second = await plan_propose_handler(session, user_id=user_id)
    await session.commit()

    drafts = (
        await session.execute(
            select(Plan.id).where(Plan.user_id == user_id, Plan.status == "draft")
        )
    ).scalars().all()
    assert drafts == [UUID(second["data"]["plan_id"])]
    assert first["data"]["plan_id"] != second["data"]["plan_id"]


@pytest.mark.asyncio
async def test_committing_a_new_plan_ends_the_active_one(session: AsyncSession) -> None:
    user_id = await _coach_user(session)
    with _no_calendar():
        first = await plan_propose_handler(session, user_id=user_id)
        await plan_commit_handler(session, user_id=user_id, plan_id=first["data"]["plan_id"])
        second = await plan_propose_handler(session, user_id=user_id)
        committed = await plan_commit_handler(
            session, user_id=user_id, plan_id=second["data"]["plan_id"]
        )
    await session.commit()

    repo = PlanRepository(session=session)
    old = await repo.get(user_id=user_id, plan_id=UUID(first["data"]["plan_id"]))
    new = await repo.get(user_id=user_id, plan_id=UUID(second["data"]["plan_id"]))
    assert old is not None and old.status == "abandoned"
    assert new is not None and new.status == "committed"
    assert committed["data"]["events_created"] > 0


@pytest.mark.asyncio
async def test_activities_are_matched_and_missed_days_skipped(session: AsyncSession) -> None:
    user_id = await _coach_user(session)
    today = date.today()
    start = week_start(today) - timedelta(weeks=1)
    plan, _, _ = await coach_service.propose(session, user_id, today=today, start=start)
    repo = PlanRepository(session=session)
    await repo.commit(user_id=user_id, plan_id=plan.id, event_ids_by_block_id={})
    await session.commit()
    past = sorted(
        (b for b in await repo.list_blocks(user_id=user_id, plan_id=plan.id) if b.day < today),
        key=lambda b: b.day,
    )
    assert len(past) >= 2
    hit, short = past[0], past[1]
    full = await _run(
        session, user_id, hit.day, distance_m=10_000, seconds=hit.planned_duration_s or 3600
    )
    half = await _run(
        session, user_id, short.day, distance_m=3_000,
        seconds=(short.planned_duration_s or 3600) * 0.5,
    )

    changed = await coach_service.match_activities(session, user_id, today)
    await session.commit()

    assert changed >= len(past)
    by_id = {b.id: b for b in await repo.list_blocks(user_id=user_id, plan_id=plan.id)}
    assert (by_id[hit.id].status, by_id[hit.id].activity_id) == ("done", full)
    assert (by_id[short.id].status, by_id[short.id].activity_id) == ("partial", half)
    assert all(by_id[b.id].status == "skipped" for b in past[2:])
    # a second run neither re-assigns activities nor touches settled blocks
    assert await coach_service.match_activities(session, user_id, today) == 0


@pytest.mark.asyncio
async def test_progress_scopes_report_plan_week_and_today(session: AsyncSession) -> None:
    user_id = await _coach_user(session)
    today = date.today()
    plan, _, _ = await coach_service.propose(
        session, user_id, today=today, start=week_start(today)
    )
    await PlanRepository(session=session).commit(
        user_id=user_id, plan_id=plan.id, event_ids_by_block_id={}
    )
    await session.commit()

    week = await plan_progress_handler(session, user_id=user_id, scope="woche")
    assert week["data"]["status"] == "aktiv"
    assert week["data"]["woche"] == week_start(today).isoformat()
    assert week["data"]["umfang_km"]["soll"] > 0
    assert week["data"]["bezugswerte"]["vdot"]["wert"] == pytest.approx(45.0)

    today_view = await plan_progress_handler(session, user_id=user_id, scope="heute")
    assert today_view["summary"].startswith("Heute:")

    whole = await plan_progress_handler(session, user_id=user_id, scope="plan")
    assert [p["art"] for p in whole["data"]["phasen"]][-1] == "taper"

    with pytest.raises(ValueError):
        await plan_progress_handler(session, user_id=user_id, scope="monat")


@pytest.mark.asyncio
async def test_progress_without_coach_plan(session: AsyncSession) -> None:
    user_id = await _user(session)

    result = await plan_progress_handler(session, user_id=user_id)

    assert result["data"]["plan_id"] is None


@pytest.mark.asyncio
async def test_vdot_from_an_activity_is_stored_with_its_calculation(
    session: AsyncSession,
) -> None:
    user_id = await _coach_user(session, vdot=None)
    activity_id = await _run(session, user_id, date.today(), distance_m=10_000, seconds=45 * 60)

    result = await reference_value_set_handler(
        session, user_id=user_id, kind="vdot", activity_id=activity_id, source="test"
    )
    await session.commit()

    # Daniels & Gilbert: 10 km in 45:00 is VDOT ~45
    assert result["data"]["wert"] == pytest.approx(45.3, abs=0.5)
    assert "Daniels" in result["data"]["rechnung"]
    assert set(result["data"]["bereiche"]) >= {"E", "T", "HM", "Marathon"}
    current = await ReferenceValueRepository(session).current(user_id)
    assert current["vdot"].activity_id == activity_id
    assert current["vdot"].source == "test"


@pytest.mark.asyncio
async def test_vdot_refuses_runs_outside_the_test_distance(session: AsyncSession) -> None:
    user_id = await _coach_user(session, vdot=None)
    activity_id = await _run(
        session, user_id, date.today(), distance_m=30_000, seconds=3 * 3600
    )

    with pytest.raises(ValueError, match="3 bis 15 km"):
        await reference_value_set_handler(
            session, user_id=user_id, kind="vdot", activity_id=activity_id
        )


@pytest.mark.asyncio
async def test_lthr_uses_the_last_twenty_minutes_of_km_splits(session: AsyncSession) -> None:
    user_id = await _coach_user(session)
    activity_id = await _run(session, user_id, date.today(), distance_m=6_000, seconds=1800)
    for idx in range(6):
        session.add(
            ActivitySplit(
                activity_id=activity_id,
                kind="distance",
                idx=idx,
                user_id=user_id,
                start_offset_s=idx * 300.0,
                timer_s=300.0,
                hr_avg=150 if idx < 2 else 170,
                quality="ok",
            )
        )
    await session.commit()

    result = await reference_value_set_handler(
        session, user_id=user_id, kind="lthr_laufen", activity_id=activity_id
    )

    assert result["data"]["wert"] == pytest.approx(170.0)


@pytest.mark.asyncio
async def test_manual_reference_value_and_confirmation_text(session: AsyncSession) -> None:
    user_id = await _coach_user(session, vdot=None)
    args = {"kind": "vdot", "value": 48.5, "measured_on": "2026-10-01"}

    assert _summarize("reference_value_set", args) == "VDOT = 48.5 speichern"
    result = await reference_value_set_handler(session, user_id=user_id, **args)

    assert result["data"]["datum"] == "2026-10-01"
    with pytest.raises(ValueError):
        await reference_value_set_handler(session, user_id=user_id, kind="ftp", value=250)


@pytest.mark.asyncio
async def test_brief_line_only_with_an_active_coach_plan(session: AsyncSession) -> None:
    user_id = await _coach_user(session, vdot=None)
    today = date.today()
    assert await coach_service.brief_line(session, user_id, today) is None

    plan, _, _ = await coach_service.propose(
        session, user_id, today=today, start=week_start(today)
    )
    await PlanRepository(session=session).commit(
        user_id=user_id, plan_id=plan.id, event_ids_by_block_id={}
    )
    await session.commit()

    line = await coach_service.brief_line(session, user_id, today)
    assert line is not None
    assert line.startswith("Coach: Plan")
    assert "heute:" in line
    assert "VDOT fehlt" in line


@pytest.mark.asyncio
async def test_history_counts_only_running_activities(session: AsyncSession) -> None:
    user_id = await _user(session)
    today = date.today()
    monday = week_start(today)
    await _run(session, user_id, monday - timedelta(days=3), distance_m=12_000, seconds=4000)
    await _run(session, user_id, monday - timedelta(days=2), distance_m=8_000, seconds=2800)
    await _run(
        session, user_id, monday - timedelta(days=1), distance_m=40_000, seconds=5000,
        sport="cycling",
    )

    history = await load_history(session, user_id, monday)

    assert history.weekly_km(monday, 1) == [pytest.approx(20.0)]
    assert history.longest_run_m(monday, 30) == pytest.approx(12_000)


@pytest.mark.asyncio
async def test_knowledge_lookup_by_id_and_by_question() -> None:
    by_id = await knowledge_lookup_handler(
        None, user_id=uuid4(), rule_id="lauf.progression.einzellauf"  # type: ignore[arg-type]
    )
    assert by_id["data"][0]["art"] == "leitplanke"
    assert by_id["data"][0]["quellen"]

    by_query = await knowledge_lookup_handler(
        None, user_id=uuid4(), query="Warum so viel locker laufen?"  # type: ignore[arg-type]
    )
    assert any(row["regel"].startswith("lauf.intensitaet.z1-anteil") for row in by_query["data"])

    with pytest.raises(ValueError):
        await knowledge_lookup_handler(None, user_id=uuid4())  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_deleting_an_activity_unlinks_its_plan_block(
    session: AsyncSession,
) -> None:
    # activity_id on plan_block must not block deleting an activity (FK set null)
    user_id = await _coach_user(session)
    today = date.today()
    plan, _, _ = await coach_service.propose(
        session, user_id, today=today, start=week_start(today) - timedelta(weeks=1)
    )
    await PlanRepository(session=session).commit(
        user_id=user_id, plan_id=plan.id, event_ids_by_block_id={}
    )
    block = (
        await session.execute(
            select(PlanBlock).where(PlanBlock.plan_id == plan.id).order_by(PlanBlock.day)
        )
    ).scalars().first()
    assert block is not None
    activity_id = await _run(session, user_id, block.day, distance_m=8_000, seconds=3000)
    await coach_service.match_activities(session, user_id, today)
    await session.commit()

    await session.execute(text("DELETE FROM activity WHERE id = :id"), {"id": activity_id})
    await session.commit()
    await session.refresh(block)
    assert block.activity_id is None
