from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command
from kairos.db.models import Base, PlanPhase
from kairos.db.rls import install_rls_listener
from kairos.repositories.coach import (
    CoachProfileRepository,
    PlanReviewRepository,
    ReferenceValueRepository,
)

_COACH_TABLES = {"coach_profile", "athlete_reference_value", "plan_phase", "plan_review"}
_TOUCHED = _COACH_TABLES | {"plan", "plan_block"}
_AVAILABILITY = {"so": {"max_min": 120, "quality": True}}


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


async def _plan(session: AsyncSession, user_id: UUID, status: str = "draft") -> UUID:
    plan_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO plan (id, user_id, title, start_date, end_date, status) "
            "VALUES (:id, :u, 'P', '2026-11-02', '2027-04-25', :s)"
        ),
        {"id": str(plan_id), "u": str(user_id), "s": status},
    )
    await session.commit()
    return plan_id


@pytest_asyncio.fixture
async def app_factory(
    app_db_url: str, run_migrations: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del run_migrations
    engine = create_async_engine(app_db_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _touches(diff: Any) -> bool:
    flat = diff if isinstance(diff, tuple) else diff[0]
    for part in flat:
        names = {getattr(part, "name", None), getattr(getattr(part, "table", None), "name", None)}
        if names & _TOUCHED or (isinstance(part, str) and part in _TOUCHED):
            return True
    return False


@pytest.mark.asyncio
async def test_orm_matches_the_coach_migration(db_url: str, run_migrations: None) -> None:
    del run_migrations
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        diffs = await conn.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )
    await engine.dispose()
    assert [d for d in diffs if _touches(d)] == []


@pytest.mark.asyncio
async def test_rls_isolates_all_four_coach_tables(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner, other = await _user(session), await _user(session)
    plan_id = await _plan(session, owner)
    async with app_factory() as s:
        install_rls_listener(s, owner)
        await CoachProfileRepository(s).upsert(
            owner,
            plan_type="ausdauer-laufen-pyramidal",
            main_sport="laufen",
            availability=_AVAILABILITY,
        )
        await ReferenceValueRepository(s).add(
            owner, kind="vdot", value=45.0, measured_on=date(2026, 10, 31), source="test"
        )
        s.add(
            PlanPhase(
                plan_id=plan_id,
                user_id=owner,
                seq=0,
                kind="basis",
                start_date=date(2026, 11, 2),
                end_date=date(2026, 12, 27),
            )
        )
        await PlanReviewRepository(s).create(
            plan_id=plan_id, user_id=owner, week_start=date(2026, 11, 2), facts={"x": 1}
        )
        await s.commit()

    async with app_factory() as s:
        install_rls_listener(s, other)
        for table in _COACH_TABLES:
            count = await s.execute(text(f"SELECT count(*) FROM {table}"))
            assert count.scalar_one() == 0, table
        assert await CoachProfileRepository(s).get(owner) is None
        with pytest.raises(Exception, match="row-level security"):
            await ReferenceValueRepository(s).add(
                owner, kind="vdot", value=50.0, measured_on=date(2026, 10, 31), source="manuell"
            )


@pytest.mark.asyncio
async def test_reference_values_keep_history_and_return_the_newest(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    async with app_factory() as s:
        install_rls_listener(s, user_id)
        repo = ReferenceValueRepository(s)
        await repo.add(
            user_id, kind="vdot", value=44.0, measured_on=date(2026, 9, 20), source="wettkampf"
        )
        await repo.add(
            user_id, kind="vdot", value=45.5, measured_on=date(2026, 10, 31), source="test"
        )
        await repo.add(
            user_id, kind="lthr_laufen", value=172, measured_on=date(2026, 10, 1), source="test"
        )
        await s.commit()
        current = await repo.current(user_id)
        history = await repo.history(user_id, "vdot")
    assert current["vdot"].value == 45.5
    assert current["lthr_laufen"].value == 172
    assert [h.value for h in history] == [45.5, 44.0]


@pytest.mark.asyncio
async def test_only_one_committed_plan_per_user(session: AsyncSession) -> None:
    user_id = await _user(session)
    await _plan(session, user_id, "committed")
    with pytest.raises(IntegrityError):
        await _plan(session, user_id, "committed")
    await session.rollback()
    # drafts and finished plans are not limited
    await _plan(session, user_id, "draft")
    await _plan(session, user_id, "completed")


@pytest.mark.asyncio
async def test_coach_profile_defaults_to_sunday_evening_review(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _user(session)
    async with app_factory() as s:
        install_rls_listener(s, user_id)
        repo = CoachProfileRepository(s)
        profile = await repo.upsert(
            user_id,
            plan_type="ausdauer-laufen-pyramidal",
            main_sport="laufen",
            availability=_AVAILABILITY,
        )
        await s.commit()
        await s.refresh(profile)
        assert (profile.review_weekday, profile.review_time.isoformat()) == (6, "19:00:00")
        updated = await repo.upsert(user_id, supplementary=["kraft"])
        await s.commit()
    assert updated.supplementary == ["kraft"] and updated.onboarded_at is not None


@pytest.mark.asyncio
async def test_migration_round_trip_keeps_phase5_plans(db_url: str, session: AsyncSession) -> None:
    user_id = await _user(session)
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    # alembic env.py runs its own event loop
    await asyncio.to_thread(command.downgrade, cfg, "5d2f8a6c1e47")
    try:
        # phase-5 data from before the coach mode: two committed plans for one user
        first = await _plan(session, user_id, "committed")
        await session.execute(
            text("UPDATE plan SET updated_at = now() - interval '1 day' WHERE id = :p"),
            {"p": str(first)},
        )
        second = await _plan(session, user_id, "committed")
        await session.execute(
            text(
                "INSERT INTO plan_block (id, plan_id, user_id, day, workout_type, status) "
                "VALUES (gen_random_uuid(), :p, :u, '2026-11-03', 'long_run', 'planned')"
            ),
            {"p": str(second), "u": str(user_id)},
        )
        await session.commit()
    finally:
        await asyncio.to_thread(command.upgrade, cfg, "head")
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            # the session-wide grant in conftest predates the recreated tables
            await conn.execute(
                text(
                    "GRANT SELECT, INSERT, UPDATE, DELETE ON coach_profile, "
                    "athlete_reference_value, plan_phase, plan_review TO kairos_app"
                )
            )
        await engine.dispose()

    rows = await session.execute(
        text("SELECT id, status, plan_type FROM plan WHERE user_id = :u ORDER BY updated_at"),
        {"u": str(user_id)},
    )
    plans = [(r.id, r.status, r.plan_type) for r in rows]
    # the older one gives way so the unique index can exist; both stay phase-5 plans
    assert plans == [(first, "abandoned", None), (second, "committed", None)]
    block = await session.execute(
        text("SELECT rule_refs, workout_type FROM plan_block WHERE plan_id = :p"),
        {"p": str(second)},
    )
    assert block.one() == ([], "long_run")
