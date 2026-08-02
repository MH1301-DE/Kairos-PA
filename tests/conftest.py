import asyncio
import os
import re

import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from testcontainers.community.postgres import PostgresContainer

# Ryuk reaper fails on macOS/Colima — disable it
os.environ.setdefault("TESTCONTAINERS_RYUK_DISABLED", "true")

POSTGRES_IMAGE = "postgres:16"


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(
        image=POSTGRES_IMAGE,
        username="kairos",
        password="test",
        dbname="kairos_test",
    ) as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(pg_container):
    raw = pg_container.get_connection_url()
    return re.sub(r"postgresql(\+\w+)?://", "postgresql+asyncpg://", raw)


@pytest.fixture(scope="session", autouse=True)
def run_migrations(pg_container, db_url):
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")

    # Create a non-superuser role so RLS can be tested (superusers always bypass RLS)
    async def _setup_app_role() -> None:
        engine = create_async_engine(db_url)
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE ROLE kairos_app NOSUPERUSER NOINHERIT LOGIN PASSWORD 'apptest'"
            ))
            await conn.execute(text(
                "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO kairos_app"
            ))
        await engine.dispose()

    asyncio.run(_setup_app_role())


@pytest.fixture(scope="session")
def app_db_url(pg_container):
    """asyncpg URL for the non-superuser kairos_app role (RLS applies to it)."""
    host = pg_container.get_container_host_ip()
    port = pg_container.get_exposed_port(5432)
    return f"postgresql+asyncpg://kairos_app:apptest@{host}:{port}/kairos_test"


@pytest_asyncio.fixture
async def session(db_url) -> AsyncSession:
    """Superuser session — used for bypassing RLS during test setup (INSERT)."""
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def app_session(app_db_url) -> AsyncSession:
    """Non-superuser session — RLS is enforced here."""
    engine = create_async_engine(app_db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
