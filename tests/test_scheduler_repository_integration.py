from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from kairos.db.models import ScheduledJob
from kairos.db.rls import install_rls_listener
from kairos.scheduler.repository import ScheduledJobRepository, due_jobs, mark_interrupted

_NOW = datetime(2026, 10, 15, 6, 0, tzinfo=UTC)
_STEPS = [{"action": "calendar.sync", "params": {}}]


async def _insert_user(session: AsyncSession) -> UUID:
    user_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()
    return user_id


async def _job(session: AsyncSession, user_id: UUID, **fields: object) -> ScheduledJob:
    # superuser session: setup bypasses RLS
    values: dict[str, object] = {
        "user_id": user_id,
        "name": "Test",
        "cron_exprs": ["0 8 * * *"],
        "steps": _STEPS,
        "next_run_at": _NOW - timedelta(minutes=1),
    }
    values.update(fields)
    job = await ScheduledJobRepository(session).create(**values)
    await session.commit()
    return job


@pytest_asyncio.fixture
async def app_factory(
    app_db_url: str, run_migrations: None
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    del run_migrations
    engine = create_async_engine(app_db_url)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _next(_: ScheduledJob) -> datetime:
    return _NOW + timedelta(days=1)


@pytest.mark.asyncio
async def test_rls_isolates_jobs_and_runs(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_a, user_b = await _insert_user(session), await _insert_user(session)
    async with app_factory() as s:
        install_rls_listener(s, user_a)
        repo = ScheduledJobRepository(s)
        job = await repo.create(
            user_id=user_a, name="A", cron_exprs=["0 8 * * *"], steps=_STEPS, next_run_at=_NOW
        )
        claimed = await repo.claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
        assert claimed is not None
        await s.commit()
        job_id = job.id

    async with app_factory() as s:
        install_rls_listener(s, user_b)
        repo = ScheduledJobRepository(s)
        assert await repo.list_jobs() == []
        assert await repo.get(job_id) is None
        assert await repo.list_runs(job_id, 10) == []
        run_count = await s.execute(text("SELECT count(*) FROM scheduled_job_run"))
        assert run_count.scalar_one() == 0
        # writing a row for another user is refused by the policy
        with pytest.raises(Exception, match="row-level security"):
            await repo.create(user_id=user_a, name="X", cron_exprs=["0 8 * * *"], steps=_STEPS)


@pytest.mark.asyncio
async def test_due_jobs_sees_all_users_without_rls_context(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_a, user_b = await _insert_user(session), await _insert_user(session)
    job_a = await _job(session, user_a)
    job_b = await _job(session, user_b)
    await _job(session, user_b, enabled=False)
    await _job(session, user_b, next_run_at=_NOW + timedelta(hours=1))

    async with app_factory() as s:
        # without app.current_user_id the table itself is invisible to kairos_app ...
        visible = await s.execute(text("SELECT count(*) FROM scheduled_job"))
        assert visible.scalar_one() == 0
        # ... the SECURITY DEFINER function still finds due jobs of every user
        due = await due_jobs(s, _NOW, 100)
        cols = await s.execute(text("SELECT * FROM scheduler_due_jobs(:now, 1)"), {"now": _NOW})

    ids = {d.job_id for d in due}
    assert {job_a.id, job_b.id} <= ids
    assert {d.user_id for d in due if d.job_id in (job_a.id, job_b.id)} == {user_a, user_b}
    assert list(cols.keys()) == ["job_id", "user_id", "next_run_at"]


@pytest.mark.asyncio
async def test_parallel_claims_on_one_job_have_exactly_one_winner(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _insert_user(session)
    job = await _job(session, user_id)

    async with app_factory() as first, app_factory() as second:
        install_rls_listener(first, user_id)
        install_rls_listener(second, user_id)
        won = await ScheduledJobRepository(first).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
        # SKIP LOCKED: the second claim does not wait for the first transaction
        lost = await ScheduledJobRepository(second).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
        await first.commit()
        await second.rollback()
        again = await ScheduledJobRepository(second).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )

    assert won is not None and lost is None and again is None
    claimed_job, run = won
    assert claimed_job.running_since == _NOW
    assert claimed_job.next_run_at == _NOW + timedelta(days=1)
    assert run.trigger == "schedule" and run.status == "running"
    assert run.steps == [{**_STEPS[0], "status": "not_run"}]


@pytest.mark.asyncio
async def test_claim_under_another_users_rls_finds_nothing(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    owner, other = await _insert_user(session), await _insert_user(session)
    job = await _job(session, owner)
    async with app_factory() as s:
        install_rls_listener(s, other)
        claimed = await ScheduledJobRepository(s).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
    assert claimed is None


@pytest.mark.asyncio
async def test_overdue_claim_is_a_catch_up(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _insert_user(session)
    job = await _job(session, user_id, next_run_at=_NOW - timedelta(hours=10))
    async with app_factory() as s:
        install_rls_listener(s, user_id)
        claimed = await ScheduledJobRepository(s).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
        await s.commit()
    assert claimed is not None
    assert claimed[1].trigger == "catch_up"
    assert claimed[1].scheduled_for == _NOW - timedelta(hours=10)


@pytest.mark.asyncio
async def test_mark_interrupted_after_restart(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _insert_user(session)
    job = await _job(session, user_id)
    async with app_factory() as s:
        install_rls_listener(s, user_id)
        claimed = await ScheduledJobRepository(s).claim(
            job.id, _NOW, next_run=_next, catch_up_after=timedelta(minutes=1)
        )
        assert claimed is not None
        run_id = claimed[1].id
        await s.commit()

    async with app_factory() as s:
        marked = await mark_interrupted(s, _NOW + timedelta(minutes=5))
        await s.commit()
    assert (job.id, user_id) in marked

    async with app_factory() as s:
        install_rls_listener(s, user_id)
        repo = ScheduledJobRepository(s)
        reloaded = await repo.get(job.id)
        run = await repo.get_run(run_id)
    assert reloaded is not None and reloaded.running_since is None
    assert reloaded.last_status == "interrupted"
    assert run is not None and run.status == "interrupted"


@pytest.mark.asyncio
async def test_prune_keeps_the_newest_runs_and_counts_agent_steps(
    session: AsyncSession, app_factory: async_sessionmaker[AsyncSession]
) -> None:
    user_id = await _insert_user(session)
    job = await _job(session, user_id)
    await session.execute(
        text(
            "INSERT INTO scheduled_job_run"
            " (id, job_id, user_id, trigger, started_at, status, steps)"
            " SELECT gen_random_uuid(), :job, :uid, 'schedule',"
            " CAST(:now AS timestamptz) - make_interval(mins => g),"
            " 'ok', CAST(:steps AS jsonb) FROM generate_series(1, 205) g"
        ),
        {
            "job": str(job.id),
            "uid": str(user_id),
            "now": _NOW,
            "steps": '[{"action": "agent.prompt", "status": "ok"},'
            ' {"action": "garmin.sync", "status": "ok"}]',
        },
    )
    await session.commit()

    async with app_factory() as s:
        install_rls_listener(s, user_id)
        repo = ScheduledJobRepository(s)
        assert await repo.agent_steps_since(user_id, _NOW - timedelta(minutes=10)) == 10
        await repo.prune_runs(job.id, keep=200)
        await s.commit()
        runs = await repo.list_runs(job.id, 500)

    assert len(runs) == 200
    assert min(r.started_at for r in runs) == _NOW - timedelta(minutes=200)
