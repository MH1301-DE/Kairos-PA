from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.rls import install_rls_listener
from kairos.planning.algorithm import PlannedBlock
from kairos.repositories.plan import PlanRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


def _blocks(start: date, n: int) -> list[PlannedBlock]:
    return [
        PlannedBlock(
            start + timedelta(days=i), "easy" if i % 2 else "rest", 50.0 if i % 2 else None
        )
        for i in range(n)
    ]


@pytest.mark.asyncio
async def test_create_draft_then_list_blocks_round_trips(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = PlanRepository(session=session)

    start = date(2026, 2, 2)
    plan = await repo.create_draft(
        user_id=user_id, title="Test-Plan", start_date=start, end_date=start + timedelta(days=6),
        goal_date=None, blocks=_blocks(start, 7),
    )
    await session.commit()

    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    assert len(blocks) == 7
    assert [b.day for b in blocks] == [start + timedelta(days=i) for i in range(7)]


@pytest.mark.asyncio
async def test_commit_sets_plan_status_and_block_event_ids(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = PlanRepository(session=session)

    start = date(2026, 2, 2)
    plan = await repo.create_draft(
        user_id=user_id, title="Test-Plan", start_date=start, end_date=start + timedelta(days=1),
        goal_date=None, blocks=_blocks(start, 2),
    )
    await session.commit()

    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    # real calendar_event rows -- plan_block.calendar_event_id has an FK to
    # calendar_event, a fabricated id would correctly be rejected
    event_ids_by_block_id = {}
    for i, b in enumerate(blocks):
        event_id = uuid4()
        await session.execute(
            text(
                "INSERT INTO calendar_event "
                "(id, user_id, connector, external_id, summary, start_at, end_at, source) "
                "VALUES (:id, :uid, 'google_calendar', :ext, 'Plan Event', :start_at, "
                ":end_at, 'kairos')"
            ),
            {
                "id": str(event_id), "uid": str(user_id), "ext": f"plan-evt-{i}",
                "start_at": datetime(b.day.year, b.day.month, b.day.day, 9, 0, tzinfo=UTC),
                "end_at": datetime(b.day.year, b.day.month, b.day.day, 10, 0, tzinfo=UTC),
            },
        )
        event_ids_by_block_id[b.id] = str(event_id)
    await session.commit()

    await repo.commit(user_id=user_id, plan_id=plan.id, event_ids_by_block_id=event_ids_by_block_id)
    await session.commit()

    committed_plan = await repo.get(user_id=user_id, plan_id=plan.id)
    assert committed_plan is not None
    assert committed_plan.status == "committed"

    updated_blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    for b in updated_blocks:
        assert str(b.calendar_event_id) == event_ids_by_block_id[b.id]


@pytest.mark.asyncio
async def test_replace_remaining_blocks_leaves_done_blocks_untouched(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()
    repo = PlanRepository(session=session)

    start = date(2026, 2, 2)
    plan = await repo.create_draft(
        user_id=user_id, title="Test-Plan", start_date=start, end_date=start + timedelta(days=3),
        goal_date=None, blocks=_blocks(start, 4),
    )
    await session.commit()

    blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    # mark the first block as already done -- must survive the replace below
    blocks[0].status = "done"
    await session.commit()

    new_blocks = [PlannedBlock(start + timedelta(days=2), "hard", 80.0)]
    await repo.replace_remaining_blocks(
        user_id=user_id, plan_id=plan.id, from_day=start + timedelta(days=1), blocks=new_blocks
    )
    await session.commit()

    final_blocks = await repo.list_blocks(user_id=user_id, plan_id=plan.id)
    assert len(final_blocks) == 2  # the done block + the one replacement
    done = next(b for b in final_blocks if b.status == "done")
    assert done.day == start
    replaced = next(b for b in final_blocks if b.status == "planned")
    assert replaced.workout_type == "hard"
    assert replaced.day == start + timedelta(days=2)


@pytest.mark.asyncio
async def test_plan_enforces_rls_isolation(
    session: AsyncSession, app_session: AsyncSession
) -> None:
    user_a = uuid4()
    user_b = uuid4()
    await _insert_user(session, user_a)
    await _insert_user(session, user_b)
    await session.commit()

    install_rls_listener(app_session, user_a)
    repo_a = PlanRepository(session=app_session)
    start = date(2026, 2, 2)
    await repo_a.create_draft(
        user_id=user_a, title="A's plan", start_date=start, end_date=start,
        goal_date=None, blocks=_blocks(start, 1),
    )
    await app_session.commit()

    install_rls_listener(app_session, user_b)
    repo_b = PlanRepository(session=app_session)
    assert await repo_b.get_active_for_user(user_id=user_b) is None
