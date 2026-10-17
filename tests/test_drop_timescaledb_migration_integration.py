from __future__ import annotations

import asyncio
import importlib.util
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from alembic import command

_PREVIOUS = "8c6af9fb1361"


async def _execute(url: str, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params or {})
            return list(result.all()) if result.returns_rows else []
    finally:
        await engine.dispose()


def _run(url: str, sql: str, params: dict[str, Any] | None = None) -> list[Any]:
    return asyncio.run(_execute(url, sql, params))


def _alembic(url: str) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


@pytest.fixture
def fresh_db_url(db_url: str) -> Iterator[str]:
    name = f"mig_{uuid.uuid4().hex[:12]}"
    _run(db_url, f"CREATE DATABASE {name}")
    yield re.sub(r"/[^/]+$", f"/{name}", db_url)
    _run(db_url, f"DROP DATABASE {name} WITH (FORCE)")


def _seed_user_and_wellness(url: str, n: int) -> tuple[str, int]:
    user_id = str(uuid.uuid4())
    _run(
        url,
        "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
        "VALUES (:id, :e, 'T', :s, 'UTC', 'user')",
        {"id": user_id, "e": f"{user_id}@test.com", "s": f"sub-{user_id}"},
    )
    metric_id = _run(url, "SELECT id FROM metric_def ORDER BY id LIMIT 1")[0][0]
    for i in range(n):
        _run(
            url,
            "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
            "VALUES (:u, :m, TIMESTAMPTZ '2026-08-01 00:00+00' + make_interval(hours => :i), :v)",
            {"u": user_id, "m": metric_id, "i": i, "v": float(50 + i)},
        )
    return user_id, metric_id


async def test_head_schema_has_plain_wellness_sample(session: AsyncSession) -> None:
    pk_cols = (
        await session.execute(
            text(
                "SELECT a.attname FROM pg_index i "
                "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                "WHERE i.indrelid = 'wellness_sample'::regclass AND i.indisprimary"
            )
        )
    ).scalars().all()
    assert pk_cols == ["id"]

    rls = (
        await session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'wellness_sample'::regclass"
            )
        )
    ).one()
    assert tuple(rls) == (True, True)

    policy = (
        await session.execute(
            text(
                "SELECT count(*) FROM pg_policies "
                "WHERE tablename = 'wellness_sample' AND policyname = 'tenant_isolation'"
            )
        )
    ).scalar_one()
    assert policy == 1

    unique = (
        await session.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'wellness_sample'::regclass AND conname = 'uq_wellness_sample'"
            )
        )
    ).scalar_one()
    assert unique == "UNIQUE (user_id, metric_id, observed_at)"

    fks = (
        await session.execute(
            text(
                "SELECT count(*) FROM pg_constraint "
                "WHERE conrelid = 'wellness_sample'::regclass AND contype = 'f'"
            )
        )
    ).scalar_one()
    assert fks == 4

    assert (
        await session.execute(text("SELECT to_regclass('activity_record')"))
    ).scalar_one() is None
    assert (
        await session.execute(
            text("SELECT count(*) FROM pg_extension WHERE extname LIKE 'timescaledb%'")
        )
    ).scalar_one() == 0


def test_upgrade_keeps_wellness_rows_and_continues_ids(fresh_db_url: str) -> None:
    cfg = _alembic(fresh_db_url)
    command.upgrade(cfg, _PREVIOUS)
    user_id, metric_id = _seed_user_and_wellness(fresh_db_url, 3)
    old_max = _run(fresh_db_url, "SELECT max(id) FROM wellness_sample")[0][0]

    command.upgrade(cfg, "head")

    assert _run(fresh_db_url, "SELECT count(*) FROM wellness_sample")[0][0] == 3
    new_id = _run(
        fresh_db_url,
        "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
        "VALUES (:u, :m, TIMESTAMPTZ '2026-09-01 00:00+00', 1.0) RETURNING id",
        {"u": user_id, "m": metric_id},
    )[0][0]
    assert new_id > old_max
    assert _run(fresh_db_url, "SELECT to_regclass('activity_record')")[0][0] is None


def test_upgrade_refuses_when_records_have_no_stream(fresh_db_url: str) -> None:
    cfg = _alembic(fresh_db_url)
    command.upgrade(cfg, _PREVIOUS)
    user_id, _ = _seed_user_and_wellness(fresh_db_url, 1)
    activity_id = _run(
        fresh_db_url,
        "INSERT INTO activity (user_id, external_id) VALUES (:u, 'ext-1') RETURNING id",
        {"u": user_id},
    )[0][0]
    _run(
        fresh_db_url,
        "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
        "VALUES (:u, :a, now(), 'hr', 140)",
        {"u": user_id, "a": activity_id},
    )

    with pytest.raises(RuntimeError, match="activity_stream_axis"):
        command.upgrade(cfg, "head")

    assert _run(fresh_db_url, "SELECT count(*) FROM activity_record")[0][0] == 1


async def test_v8_script_exits_cleanly_without_activity_record(
    db_url: str, run_migrations: None, monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    del run_migrations
    spec = importlib.util.spec_from_file_location(
        "verify_activity_streams", Path("scripts/verify_activity_streams.py")
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    engine = create_async_engine(db_url)
    monkeypatch.setattr(module, "async_session_factory", async_sessionmaker(engine))
    try:
        assert await module.run(uuid.uuid4()) == 0
    finally:
        await engine.dispose()
    assert "activity_record no longer exists" in capsys.readouterr().out


def test_upgrade_refuses_role_that_does_not_bypass_rls(fresh_db_url: str) -> None:
    command.upgrade(_alembic(fresh_db_url), _PREVIOUS)
    _seed_user_and_wellness(fresh_db_url, 2)
    role = f"mig_{uuid.uuid4().hex[:12]}"
    _run(fresh_db_url, f"CREATE ROLE {role} NOSUPERUSER NOBYPASSRLS LOGIN PASSWORD 'pw'")
    _run(fresh_db_url, f"GRANT ALL ON alembic_version TO {role}")
    role_url = re.sub(r"//[^@]+@", f"//{role}:pw@", fresh_db_url)
    try:
        with pytest.raises(RuntimeError, match="bypasses RLS"):
            command.upgrade(_alembic(role_url), "head")
    finally:
        _run(fresh_db_url, f"REVOKE ALL ON alembic_version FROM {role}")
        _run(fresh_db_url, f"DROP ROLE {role}")

    assert _run(fresh_db_url, "SELECT count(*) FROM wellness_sample")[0][0] == 2
    assert _run(fresh_db_url, "SELECT version_num FROM alembic_version")[0][0] == _PREVIOUS
