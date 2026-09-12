from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.tools import (
    plan_adjust_handler,
    plan_commit_handler,
    plan_progress_handler,
    plan_propose_handler,
)
from kairos.planning.algorithm import PlannedBlock
from kairos.repositories.plan import PlanRepository


async def _insert_user(session: AsyncSession, user_id) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_plan_propose_handler_creates_a_draft_plan(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await plan_propose_handler(session, user_id=user_id, weeks=2)

    assert "plan_id" in result["data"]
    plan_id = UUID(result["data"]["plan_id"])
    repo = PlanRepository(session=session)
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan_id)
    assert len(blocks) == 14  # 2 weeks
    plan = await repo.get(user_id=user_id, plan_id=plan_id)
    assert plan is not None
    assert plan.status == "draft"


@pytest.mark.asyncio
async def test_plan_commit_handler_creates_calendar_events(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    start = date.today()
    repo = PlanRepository(session=session)
    plan = await repo.create_draft(
        user_id=user_id, title="Test", start_date=start, end_date=start + timedelta(days=2),
        goal_date=None,
        blocks=[
            PlannedBlock(start, "easy", 40.0),
            PlannedBlock(start + timedelta(days=1), "rest", None),
            PlannedBlock(start + timedelta(days=2), "hard", 60.0),
        ],
    )
    await session.commit()

    mock_client = MagicMock()
    mock_client.create_event.side_effect = [
        {"id": "evt-1"}, {"id": "evt-2"},
    ]
    with patch(
        "kairos.routers.calendar._build_google_calendar_client",
        new=AsyncMock(return_value=mock_client),
    ):
        result = await plan_commit_handler(session, user_id=user_id, plan_id=str(plan.id))

    assert result["data"]["events_created"] == 2  # rest block is skipped
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    non_rest = [b for b in blocks if b.workout_type != "rest"]
    assert all(b.calendar_event_id is not None for b in non_rest)
    rest_block = next(b for b in blocks if b.workout_type == "rest")
    assert rest_block.calendar_event_id is None

    committed_plan = await repo.get(user_id=user_id, plan_id=plan.id)
    assert committed_plan is not None
    assert committed_plan.status == "committed"


@pytest.mark.asyncio
async def test_plan_adjust_handler_reduces_future_planned_blocks(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    today = date.today()
    repo = PlanRepository(session=session)
    plan = await repo.create_draft(
        user_id=user_id, title="Test", start_date=today, end_date=today + timedelta(days=1),
        goal_date=None,
        blocks=[
            PlannedBlock(today, "easy", 100.0),
            PlannedBlock(today + timedelta(days=1), "hard", 80.0),
        ],
    )
    await session.commit()

    result = await plan_adjust_handler(
        session, user_id=user_id, plan_id=str(plan.id), reason="Ich habe diese Woche viel Stress"
    )

    assert result["data"]["multiplier"] == pytest.approx(0.7)
    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    for b in blocks:
        assert b.target_trimp in (pytest.approx(70.0), pytest.approx(56.0))


@pytest.mark.asyncio
async def test_plan_progress_handler_with_no_active_plan(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    result = await plan_progress_handler(session, user_id=user_id)
    assert result["data"]["plan_id"] is None


@pytest.mark.asyncio
async def test_plan_progress_handler_sums_planned_load_for_this_week(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    repo = PlanRepository(session=session)
    plan = await repo.create_draft(
        user_id=user_id, title="Test", start_date=week_start,
        end_date=week_start + timedelta(days=6), goal_date=None,
        blocks=[
            PlannedBlock(week_start + timedelta(days=i), "easy" if i % 2 else "rest",
                         50.0 if i % 2 else None)
            for i in range(7)
        ],
    )
    await session.commit()

    result = await plan_progress_handler(session, user_id=user_id, plan_id=str(plan.id))
    assert result["data"]["planned_total"] == pytest.approx(150.0)  # 3 easy days * 50
    assert result["data"]["actual_total"] == pytest.approx(0.0)  # no real activity data seeded
