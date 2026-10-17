from __future__ import annotations

import asyncio
from typing import Any

import pytest
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from kairos.db.models import Base

_TABLES = {"scheduled_job", "scheduled_job_run"}


def test_single_alembic_head() -> None:
    heads = ScriptDirectory.from_config(Config("alembic.ini")).get_heads()
    assert heads == ["5c8e1d2f7a90"]


def _touches_scheduler(diff: Any) -> bool:
    flat = diff if isinstance(diff, tuple) else diff[0]
    return any(
        getattr(part, "name", None) in _TABLES
        or getattr(getattr(part, "table", None), "name", None) in _TABLES
        or part in _TABLES
        for part in flat
    )


@pytest.mark.asyncio
async def test_orm_matches_migration_and_downgrade_round_trips(
    db_url: str, run_migrations: None
) -> None:
    del run_migrations
    engine = create_async_engine(db_url)
    async with engine.connect() as conn:
        diffs = await conn.run_sync(
            lambda sync: compare_metadata(MigrationContext.configure(sync), Base.metadata)
        )
    assert [d for d in diffs if _touches_scheduler(d)] == []

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    # alembic env.py runs its own event loop
    await asyncio.to_thread(command.downgrade, cfg, "7a1c2e9d4b30")
    async with engine.connect() as conn:
        gone = await conn.execute(text("SELECT to_regclass('scheduled_job')"))
        assert gone.scalar_one() is None
    await asyncio.to_thread(command.upgrade, cfg, "head")
    async with engine.begin() as conn:
        # the session-wide grant in conftest predates the recreated tables
        await conn.execute(
            text(
                "GRANT SELECT, INSERT, UPDATE, DELETE "
                "ON scheduled_job, scheduled_job_run TO kairos_app"
            )
        )
        forced = await conn.execute(
            text(
                "SELECT count(*) FROM pg_class WHERE relname IN ('scheduled_job', "
                "'scheduled_job_run') AND relrowsecurity AND relforcerowsecurity"
            )
        )
        assert forced.scalar_one() == 2
    await engine.dispose()
