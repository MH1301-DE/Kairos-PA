from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.agent.tools import plan_commit_handler, plan_propose_handler
from kairos.repositories.calendar_event import CalendarEventRepository
from kairos.repositories.plan import PlanRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_propose_then_commit_creates_kairos_calendar_events(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    proposed = await plan_propose_handler(session, user_id=user_id, weeks=1)
    plan_id = UUID(proposed["data"]["plan_id"])

    repo = PlanRepository(session=session)
    blocks_before = await repo.list_blocks(user_id=user_id, plan_id=plan_id)
    non_rest_before = [b for b in blocks_before if b.workout_type != "rest"]
    assert non_rest_before  # a 1-week plan always has at least one non-rest day

    mock_client = MagicMock()
    mock_client.create_event.side_effect = [
        {"id": f"google-evt-{i}"} for i in range(len(non_rest_before))
    ]
    with patch(
        "kairos.routers.calendar._build_google_calendar_client",
        new=AsyncMock(return_value=mock_client),
    ):
        result = await plan_commit_handler(session, user_id=user_id, plan_id=str(plan_id))

    assert result["data"]["events_created"] == len(non_rest_before)

    blocks_after = await repo.list_blocks(user_id=user_id, plan_id=plan_id)
    event_repo = CalendarEventRepository(session)
    for block in blocks_after:
        if block.workout_type == "rest":
            assert block.calendar_event_id is None
            continue
        assert block.calendar_event_id is not None
        event = await event_repo.get_by_id(user_id, block.calendar_event_id)
        assert event is not None
        assert event.source == "kairos"

    committed_plan = await repo.get(user_id=user_id, plan_id=plan_id)
    assert committed_plan is not None
    assert committed_plan.status == "committed"
