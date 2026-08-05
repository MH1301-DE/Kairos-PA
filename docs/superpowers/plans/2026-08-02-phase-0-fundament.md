# Phase 0 — Fundament: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein lauffähiges, getestetes Fundament auf dem Mac, das 1:1 auf Linux deploybar ist: Repo-Struktur, lokale DB via Docker, FastAPI-Skeleton mit `/healthz`, Google-OIDC-Login, RLS-Enforcement und Envelope-Verschlüsselung für Credentials.

**Architecture:** Modularer Python-Monolith (`src/kairos/`), SQLAlchemy async + Alembic, FastAPI. Alle externen Dienste laufen in Docker (Postgres+TimescaleDB+pgvector, Redis) — identische Images auf Mac und Linux. Die App selbst läuft lokal (kein App-Container in Phase 0), das spätere Produktions-Compose baut darauf auf.

**Tech Stack:** Python 3.12, uv (Package Manager), FastAPI, SQLAlchemy 2 async, Alembic, asyncpg, pydantic-settings, pytest + pytest-asyncio + testcontainers, ruff, mypy, Docker Compose v2

---

## Voraussetzungen (einmalig, manuell)

```bash
# macOS
brew install uv docker
# Docker Desktop starten (GUI) oder:
brew install --cask docker

# Google Cloud Console:
# 1. Projekt anlegen: "kairos-dev"
# 2. OAuth 2.0 Client ID erstellen (Web application)
#    Authorized redirect URI: http://localhost:8000/auth/callback
# 3. Test-Nutzer eintragen (eigene Google-E-Mail)
# → GOOGLE_CLIENT_ID und GOOGLE_CLIENT_SECRET notieren
```

---

## Dateistruktur

```
kairos/
├── src/
│   └── kairos/
│       ├── __init__.py
│       ├── api.py                  # FastAPI app factory
│       ├── config.py               # pydantic-settings
│       ├── db/
│       │   ├── __init__.py
│       │   ├── session.py          # async engine + session factory
│       │   ├── models.py           # SQLAlchemy ORM models
│       │   └── rls.py              # SET LOCAL app.current_user_id event
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── google.py           # OAuth redirect + callback
│       │   ├── session.py          # Redis session store
│       │   ├── crypto.py           # DEK/KEK envelope encryption
│       │   └── deps.py             # FastAPI dependency: current_user
│       └── routers/
│           ├── __init__.py
│           └── health.py           # GET /healthz
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
├── tests/
│   ├── conftest.py                 # DB-Fixtures via testcontainers
│   ├── test_health.py
│   ├── test_auth.py
│   └── test_rls.py
├── deploy/
│   ├── docker-compose.yml          # Produktion (bestehend)
│   └── docker-compose.dev.yml      # Lokale Dienste (nur DB + Redis)
├── .env.example
├── pyproject.toml
├── alembic.ini
└── .github/
    └── workflows/
        └── ci.yml
```

---

## Task 1: Repo-Struktur & Tooling

**Files:**
- Create: `pyproject.toml`
- Create: `alembic.ini`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`
- Create: `src/kairos/__init__.py`

- [ ] **Schritt 1.1: pyproject.toml anlegen**

```toml
[project]
name = "kairos"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic-settings>=2.3",
    "redis[asyncio]>=5.0",
    "cryptography>=42",
    "httpx>=0.27",           # für OAuth token exchange
    "itsdangerous>=2.2",     # für signierte Session-Cookies
]

[project.optional-dependencies]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.23",
    "testcontainers[postgres]>=4",
    "ruff>=0.4",
    "mypy>=1.10",
    "types-redis",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/kairos"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.12"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Schritt 1.2: .env.example anlegen**

```bash
# Kopieren nach .env (außerhalb des Repos oder lokal), NIEMALS einchecken
DATABASE_URL=postgresql+asyncpg://kairos:devpassword@localhost:5432/kairos
REDIS_URL=redis://:devredispass@localhost:6379/0
KAIROS_KEK=AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=  # 32 Byte Base64, NUR Beispiel
GOOGLE_CLIENT_ID=your-client-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
SESSION_SECRET=changeme-32-chars-minimum-here!!
POSTGRES_PASSWORD=devpassword
REDIS_PASSWORD=devredispass
DOMAIN=localhost
ENV=development
```

- [ ] **Schritt 1.3: .gitignore anlegen**

```gitignore
.env
*.env
.env.*
__pycache__/
.mypy_cache/
.ruff_cache/
.pytest_cache/
dist/
*.egg-info/
.venv/
```

- [ ] **Schritt 1.4: CI-Workflow anlegen**

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: timescale/timescaledb-ha:pg16
        env:
          POSTGRES_DB: kairos_test
          POSTGRES_USER: kairos
          POSTGRES_PASSWORD: testpass
        ports: ["5432:5432"]
        options: --health-cmd "pg_isready -U kairos" --health-interval 5s --health-retries 5
      redis:
        image: redis:7-alpine
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: uv run ruff check src tests
      - run: uv run mypy src
      - run: uv run pytest
        env:
          DATABASE_URL: postgresql+asyncpg://kairos:testpass@localhost:5432/kairos_test
          REDIS_URL: redis://localhost:6379/0
          KAIROS_KEK: AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=
          GOOGLE_CLIENT_ID: test-client-id
          GOOGLE_CLIENT_SECRET: test-secret
          SESSION_SECRET: test-session-secret-32-chars-here
          ENV: test
```

- [ ] **Schritt 1.5: Virtuelle Umgebung erstellen & Abhängigkeiten installieren**

```bash
cd /Users/mhaenel/personal/projects/Kairos-PA
uv sync --all-extras
```

Erwartete Ausgabe: `Resolved N packages` ohne Fehler.

- [ ] **Schritt 1.6: src/kairos/__init__.py anlegen**

```python
# Leer — markiert kairos als Package
```

- [ ] **Schritt 1.7: Commit**

```bash
git add pyproject.toml .env.example .gitignore alembic.ini .github/ src/
git commit -m "chore: repo structure and tooling"
```

---

## Task 2: Docker Compose für lokale Entwicklung

**Files:**
- Create: `deploy/docker-compose.dev.yml`
- Create: `Makefile`

- [ ] **Schritt 2.1: Dev-Compose anlegen**

```yaml
# deploy/docker-compose.dev.yml
# Startet nur Infrastruktur-Dienste — API läuft lokal via uvicorn
services:
  postgres:
    image: timescale/timescaledb-ha:pg16
    platform: linux/amd64   # ARM-Mac-Kompatibilität
    environment:
      POSTGRES_DB: kairos
      POSTGRES_USER: kairos
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-devpassword}
    ports: ["5432:5432"]
    volumes: [pgdata_dev:/home/postgres/pgdata]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U kairos -d kairos"]
      interval: 5s
      retries: 10

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD:-devredispass}
    ports: ["6379:6379"]
    volumes: [redisdata_dev:/data]

volumes:
  pgdata_dev:
  redisdata_dev:
```

- [ ] **Schritt 2.2: Makefile anlegen**

```makefile
.PHONY: up down logs migrate test lint

up:
	docker compose -f deploy/docker-compose.dev.yml up -d

down:
	docker compose -f deploy/docker-compose.dev.yml down

logs:
	docker compose -f deploy/docker-compose.dev.yml logs -f

migrate:
	uv run alembic upgrade head

test:
	uv run pytest

lint:
	uv run ruff check src tests
	uv run mypy src

dev:
	uv run uvicorn kairos.api:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Schritt 2.3: Dienste starten und prüfen**

```bash
cp .env.example .env   # .env lokal anlegen, Werte anpassen
make up
docker compose -f deploy/docker-compose.dev.yml ps
```

Erwartete Ausgabe: beide Services `healthy` / `running`.

- [ ] **Schritt 2.4: Commit**

```bash
git add deploy/docker-compose.dev.yml Makefile
git commit -m "chore: add dev docker compose and Makefile"
```

---

## Task 3: Config & DB-Session

**Files:**
- Create: `src/kairos/config.py`
- Create: `src/kairos/db/__init__.py`
- Create: `src/kairos/db/session.py`

- [ ] **Schritt 3.1: Fehlertest schreiben**

```python
# tests/test_config.py
from kairos.config import Settings

def test_settings_loads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+asyncpg://u:p@localhost/db")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("KAIROS_KEK", "A" * 44)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("SESSION_SECRET", "x" * 32)
    s = Settings()
    assert s.database_url.startswith("postgresql")
```

```bash
uv run pytest tests/test_config.py -v
# Erwartet: FAILED — ImportError (kairos.config existiert nicht)
```

- [ ] **Schritt 3.2: config.py implementieren**

```python
# src/kairos/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str
    kairos_kek: str          # Base64-encoded 32-Byte AES key
    google_client_id: str
    google_client_secret: str
    session_secret: str
    domain: str = "localhost"
    env: str = "development"

    @property
    def is_dev(self) -> bool:
        return self.env == "development"


settings = Settings()
```

- [ ] **Schritt 3.3: Test ausführen**

```bash
uv run pytest tests/test_config.py -v
# Erwartet: PASSED
```

- [ ] **Schritt 3.4: DB-Session implementieren**

```python
# src/kairos/db/session.py
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from kairos.config import settings

engine = create_async_engine(settings.database_url, pool_size=10, max_overflow=5)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

- [ ] **Schritt 3.5: Commit**

```bash
git add src/kairos/config.py src/kairos/db/ tests/test_config.py
git commit -m "feat: settings and db session factory"
```

---

## Task 4: ORM-Modelle + Alembic

**Files:**
- Create: `src/kairos/db/models.py`
- Create: `alembic/env.py`
- Create: `alembic/versions/0001_initial_schema.py`
- Create: `alembic.ini`

- [ ] **Schritt 4.1: alembic.ini anlegen**

```ini
[alembic]
script_location = alembic
sqlalchemy.url = postgresql+asyncpg://kairos:devpassword@localhost:5432/kairos

[loggers]
keys = root,sqlalchemy,alembic

[logger_root]
level = WARN
handlers = console

[logger_sqlalchemy]
level = WARN
handlers =

[logger_alembic]
level = INFO
handlers =

[handlers]
keys = console

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatters]
keys = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Schritt 4.2: ORM-Modelle anlegen**

```python
# src/kairos/db/models.py
import uuid
from datetime import datetime
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey,
    Integer, LargeBinary, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    google_sub: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # Google subject ID
    home_timezone: Mapped[str] = mapped_column(Text, nullable=False, default="Europe/Berlin")
    role: Mapped[str] = mapped_column(Text, nullable=False, default="user")
    dek_wrapped: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("role IN ('user', 'admin')", name="app_user_role_check"),
    )


class Connection(Base):
    __tablename__ = "connection"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    external_account: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    credentials_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    connected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_ok_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        CheckConstraint("status IN ('active','reauth_required','disabled','error')", name="connection_status_check"),
        UniqueConstraint("user_id", "connector", "external_account", name="uq_connection"),
    )


class RawPayload(Base):
    __tablename__ = "raw_payload"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False)
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    payload_gzip: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint("user_id", "connector", "kind", "window_start", "content_hash", name="uq_raw_payload"),
    )


class SyncState(Base):
    __tablename__ = "sync_state"

    user_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, primary_key=True)
    connector: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False, primary_key=True)
    synced_through: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_cursor: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backfill_complete_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_token: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
```

- [ ] **Schritt 4.3: Alembic env.py anlegen**

```python
# alembic/env.py
import asyncio
from logging.config import fileConfig
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context
from kairos.config import settings
from kairos.db.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.run_sync(
            lambda sync_conn: context.configure(connection=sync_conn, target_metadata=target_metadata)
        )
        async with engine.begin() as conn:
            await conn.run_sync(lambda sync_conn: context.run_migrations())
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Schritt 4.4: Erste Migration generieren**

```bash
make up   # Sicherstellen, dass Postgres läuft
uv run alembic revision --autogenerate -m "initial schema"
# Erzeugt alembic/versions/XXXX_initial_schema.py
```

Die generierte Datei prüfen: Tabellen `app_user`, `connection`, `raw_payload`, `sync_state` müssen darin erscheinen.

- [ ] **Schritt 4.5: Migration + RLS in der Migration ergänzen**

Am Ende der `upgrade()`-Funktion in der generierten Migrationsdatei hinzufügen:

```python
from alembic import op

def upgrade() -> None:
    # ... autogenerierter Code ...

    # RLS auf allen Tabellen mit user_id
    rls_tables = ["connection", "raw_payload", "sync_state"]
    for table in rls_tables:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (user_id = current_setting('app.current_user_id', true)::uuid)
        """)
    # app_user selbst: nur eigene Zeile lesbar (kein user_id FK, stattdessen id)
    op.execute("ALTER TABLE app_user ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY tenant_isolation ON app_user
        USING (id = current_setting('app.current_user_id', true)::uuid)
    """)
```

- [ ] **Schritt 4.6: Migration ausführen**

```bash
make migrate
```

Erwartete Ausgabe: `Running upgrade  -> XXXX, initial schema`

- [ ] **Schritt 4.7: Commit**

```bash
git add src/kairos/db/models.py alembic/ alembic.ini
git commit -m "feat: core ORM models and initial Alembic migration with RLS"
```

---

## Task 5: RLS-Enforcement im ORM + CI-Test

**Files:**
- Create: `src/kairos/db/rls.py`
- Create: `tests/conftest.py`
- Create: `tests/test_rls.py`

- [ ] **Schritt 5.1: RLS-Event-Listener implementieren**

```python
# src/kairos/db/rls.py
import uuid
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession


def install_rls_listener(session: AsyncSession, user_id: uuid.UUID) -> None:
    """Setzt app.current_user_id für alle Queries dieser Session."""

    @event.listens_for(session.sync_session, "after_transaction_create")
    def set_rls_context(session_sync, transaction):  # type: ignore[misc]
        session_sync.execute(
            text("SET LOCAL app.current_user_id = :uid"),
            {"uid": str(user_id)},
        )
```

- [ ] **Schritt 5.2: testcontainers-Fixture anlegen**

```python
# tests/conftest.py
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from testcontainers.postgres import PostgresContainer
from alembic.config import Config
from alembic import command


TIMESCALE_IMAGE = "timescale/timescaledb-ha:pg16"


@pytest.fixture(scope="session")
def pg_container():
    with PostgresContainer(image=TIMESCALE_IMAGE, username="kairos", password="test", dbname="kairos_test") as pg:
        yield pg


@pytest.fixture(scope="session")
def db_url(pg_container):
    return pg_container.get_connection_url().replace("psycopg2", "asyncpg").replace("postgresql", "postgresql+asyncpg")


@pytest.fixture(scope="session", autouse=True)
def run_migrations(db_url):
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", db_url)
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture
async def session(db_url) -> AsyncSession:
    engine = create_async_engine(db_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()
```

- [ ] **Schritt 5.3: RLS-Test schreiben**

```python
# tests/test_rls.py
import uuid
import pytest
from sqlalchemy import select, text
from kairos.db.models import AppUser
from kairos.db.rls import install_rls_listener


@pytest.mark.asyncio
async def test_rls_isolates_users(session):
    # Zwei Nutzer anlegen (RLS umgehen via SUPERUSER-Verbindung)
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    await session.execute(text("SET app.current_user_id = ''"))  # RLS deaktiviert
    await session.execute(
        text("""
            INSERT INTO app_user (id, email, display_name, google_sub)
            VALUES (:id, :email, :name, :sub)
        """),
        [
            {"id": str(user_a_id), "email": "a@test.com", "name": "A", "sub": "sub_a"},
            {"id": str(user_b_id), "email": "b@test.com", "name": "B", "sub": "sub_b"},
        ],
    )
    await session.commit()

    # Session als User A: darf nur eigene Zeile sehen
    install_rls_listener(session, user_a_id)
    result = await session.execute(select(AppUser))
    users = result.scalars().all()
    assert len(users) == 1
    assert users[0].id == user_a_id
```

- [ ] **Schritt 5.4: Test ausführen**

```bash
uv run pytest tests/test_rls.py -v
# Erwartet: PASSED
```

- [ ] **Schritt 5.5: Commit**

```bash
git add src/kairos/db/rls.py tests/conftest.py tests/test_rls.py
git commit -m "feat: RLS event listener and isolation test"
```

---

## Task 6: Envelope-Verschlüsselung (DEK/KEK)

**Files:**
- Create: `src/kairos/auth/crypto.py`
- Create: `tests/test_crypto.py`

- [ ] **Schritt 6.1: Test schreiben**

```python
# tests/test_crypto.py
import os
import base64
from kairos.auth.crypto import generate_dek, wrap_dek, unwrap_dek, encrypt, decrypt


def test_dek_roundtrip():
    kek = os.urandom(32)
    dek = generate_dek()
    wrapped = wrap_dek(dek, kek)
    assert unwrap_dek(wrapped, kek) == dek


def test_encrypt_decrypt_roundtrip():
    dek = generate_dek()
    plaintext = b"garmin-refresh-token-super-secret"
    ciphertext = encrypt(plaintext, dek)
    assert decrypt(ciphertext, dek) == plaintext


def test_ciphertext_is_not_plaintext():
    dek = generate_dek()
    plaintext = b"secret"
    assert encrypt(plaintext, dek) != plaintext
```

```bash
uv run pytest tests/test_crypto.py -v
# Erwartet: FAILED — ImportError
```

- [ ] **Schritt 6.2: crypto.py implementieren**

```python
# src/kairos/auth/crypto.py
import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_dek() -> bytes:
    return os.urandom(32)


def wrap_dek(dek: bytes, kek: bytes) -> bytes:
    """Verschlüsselt DEK mit KEK (AES-256-GCM). Gibt nonce||ciphertext zurück."""
    nonce = os.urandom(12)
    return nonce + AESGCM(kek).encrypt(nonce, dek, None)


def unwrap_dek(wrapped: bytes, kek: bytes) -> bytes:
    """Entschlüsselt mit KEK verpackten DEK."""
    return AESGCM(kek).decrypt(wrapped[:12], wrapped[12:], None)


def encrypt(plaintext: bytes, dek: bytes) -> bytes:
    """AES-256-GCM. Gibt nonce||ciphertext zurück."""
    nonce = os.urandom(12)
    return nonce + AESGCM(dek).encrypt(nonce, plaintext, None)


def decrypt(ciphertext: bytes, dek: bytes) -> bytes:
    return AESGCM(dek).decrypt(ciphertext[:12], ciphertext[12:], None)


def kek_from_settings(b64_key: str) -> bytes:
    return base64.b64decode(b64_key)
```

- [ ] **Schritt 6.3: Tests ausführen**

```bash
uv run pytest tests/test_crypto.py -v
# Erwartet: 3x PASSED
```

- [ ] **Schritt 6.4: Commit**

```bash
git add src/kairos/auth/crypto.py tests/test_crypto.py
git commit -m "feat: DEK/KEK envelope encryption"
```

---

## Task 7: FastAPI-Skeleton + /healthz

**Files:**
- Create: `src/kairos/api.py`
- Create: `src/kairos/routers/health.py`
- Create: `src/kairos/routers/__init__.py`
- Create: `tests/test_health.py`

- [ ] **Schritt 7.1: Fehlertest schreiben**

```python
# tests/test_health.py
import pytest
from httpx import AsyncClient, ASGITransport
from kairos.api import app


@pytest.mark.asyncio
async def test_healthz_returns_200():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
```

```bash
uv run pytest tests/test_health.py -v
# Erwartet: FAILED — ImportError
```

- [ ] **Schritt 7.2: health.py implementieren**

```python
# src/kairos/routers/health.py
from fastapi import APIRouter
router = APIRouter()

@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
```

- [ ] **Schritt 7.3: api.py implementieren**

```python
# src/kairos/api.py
from fastapi import FastAPI
from kairos.routers.health import router as health_router

app = FastAPI(title="Kairos", version="0.1.0")
app.include_router(health_router)
```

- [ ] **Schritt 7.4: Tests + manueller Check**

```bash
uv run pytest tests/test_health.py -v
# Erwartet: PASSED

make dev
# Dann: curl http://localhost:8000/healthz
# Erwartet: {"status":"ok"}
```

- [ ] **Schritt 7.5: Commit**

```bash
git add src/kairos/api.py src/kairos/routers/ tests/test_health.py
git commit -m "feat: FastAPI app skeleton with /healthz"
```

---

## Task 8: Google OIDC Login

**Files:**
- Create: `src/kairos/auth/google.py`
- Create: `src/kairos/auth/session.py`
- Create: `src/kairos/auth/deps.py`
- Create: `tests/test_auth.py`

- [ ] **Schritt 8.1: Session-Store (Redis) implementieren**

```python
# src/kairos/auth/session.py
import json
import secrets
import uuid
from redis.asyncio import Redis
from kairos.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def create_session(user_id: uuid.UUID, email: str) -> str:
    session_id = secrets.token_urlsafe(32)
    await get_redis().setex(
        f"session:{session_id}",
        86400 * 30,  # 30 Tage
        json.dumps({"user_id": str(user_id), "email": email}),
    )
    return session_id


async def get_session(session_id: str) -> dict | None:
    data = await get_redis().get(f"session:{session_id}")
    return json.loads(data) if data else None


async def delete_session(session_id: str) -> None:
    await get_redis().delete(f"session:{session_id}")
```

- [ ] **Schritt 8.2: Google OAuth Router implementieren**

```python
# src/kairos/auth/google.py
import secrets
from urllib.parse import urlencode
import httpx
from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound
from kairos.auth.crypto import generate_dek, kek_from_settings, wrap_dek
from kairos.auth.session import create_session, delete_session, get_redis
from kairos.config import settings
from kairos.db.models import AppUser
from kairos.db.session import async_session_factory

router = APIRouter(prefix="/auth")

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = "openid email profile https://www.googleapis.com/auth/calendar"


@router.get("/login")
async def login() -> RedirectResponse:
    state = secrets.token_urlsafe(32)
    await get_redis().setex(f"oauth_state:{state}", 600, "1")
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.redirect_uri,
        "scope": SCOPES,
        "response_type": "code",
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def callback(code: str, state: str) -> JSONResponse:
    # CSRF-Schutz: state validieren
    valid = await get_redis().getdel(f"oauth_state:{state}")
    if not valid:
        raise HTTPException(status_code=400, detail="invalid_state")

    # Code gegen Tokens tauschen
    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.redirect_uri,
            "grant_type": "authorization_code",
        })
    token_resp.raise_for_status()
    tokens = token_resp.json()

    # Nutzerinfo holen
    async with httpx.AsyncClient() as client:
        info_resp = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
    info_resp.raise_for_status()
    info = info_resp.json()

    google_sub: str = info["sub"]
    email: str = info["email"]
    name: str = info.get("name", email)

    async with async_session_factory() as db:
        result = await db.execute(select(AppUser).where(AppUser.google_sub == google_sub))
        user = result.scalar_one_or_none()

        if user is None:
            kek = kek_from_settings(settings.kairos_kek)
            dek = generate_dek()
            user = AppUser(email=email, display_name=name, google_sub=google_sub, dek_wrapped=wrap_dek(dek, kek))
            db.add(user)
            await db.commit()
            await db.refresh(user)

    session_id = await create_session(user.id, email)
    response = JSONResponse({"ok": True, "email": email})
    response.set_cookie(
        "session_id",
        session_id,
        httponly=True,
        secure=not settings.is_dev,
        samesite="lax",
        max_age=86400 * 30,
    )
    return response


@router.post("/logout")
async def logout(session_id: str | None = Cookie(default=None)) -> JSONResponse:
    if session_id:
        await delete_session(session_id)
    response = JSONResponse({"ok": True})
    response.delete_cookie("session_id")
    return response
```

- [ ] **Schritt 8.3: Auth-Dependency implementieren**

```python
# src/kairos/auth/deps.py
import uuid
from fastapi import Cookie, HTTPException
from kairos.auth.session import get_session


async def current_user(session_id: str | None = Cookie(default=None)) -> dict:
    if not session_id:
        raise HTTPException(status_code=401, detail="not_authenticated")
    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=401, detail="session_expired")
    return session
```

- [ ] **Schritt 8.4: Router in api.py einbinden**

```python
# src/kairos/api.py
from fastapi import FastAPI
from kairos.routers.health import router as health_router
from kairos.auth.google import router as auth_router

app = FastAPI(title="Kairos", version="0.1.0")
app.include_router(health_router)
app.include_router(auth_router)
```

- [ ] **Schritt 8.5: Auth-Tests schreiben**

```python
# tests/test_auth.py
import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport
from kairos.api import app


@pytest.mark.asyncio
async def test_login_redirects_to_google():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/login", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert "accounts.google.com" in response.headers["location"]


@pytest.mark.asyncio
async def test_callback_rejects_invalid_state():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/auth/callback?code=abc&state=invalid-state")
    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_state"
```

- [ ] **Schritt 8.6: Tests ausführen**

```bash
uv run pytest tests/test_auth.py -v
# Erwartet: 2x PASSED
# (Login-Test erfordert laufenden Redis)
make up  # falls Redis nicht läuft
```

- [ ] **Schritt 8.7: Manueller End-to-End-Test**

```bash
make dev
# Browser öffnen: http://localhost:8000/auth/login
# → Redirect zu Google-Login → Anmeldung → Callback
# → Browser zeigt {"ok": true, "email": "deine@email.com"}
```

- [ ] **Schritt 8.8: Commit**

```bash
git add src/kairos/auth/ tests/test_auth.py
git commit -m "feat: Google OIDC login flow with Redis session"
```

---

## Task 9: Vollständiger CI-Lauf + Phase-0-Abnahme

- [ ] **Schritt 9.1: Alle Tests lokal ausführen**

```bash
uv run pytest -v
# Erwartet: alle Tests grün
```

- [ ] **Schritt 9.2: Linting + Typen**

```bash
make lint
# Erwartet: keine Fehler
```

- [ ] **Schritt 9.3: CI pushen und grünen Build abwarten**

```bash
git push origin main
# GitHub Actions → CI workflow → alle Steps grün
```

- [ ] **Schritt 9.4: Abnahme-Checkliste**

```
□ uv run pytest → alle Tests PASSED
□ make lint → keine Fehler
□ make dev → http://localhost:8000/healthz → {"status":"ok"}
□ http://localhost:8000/auth/login → Redirect zu Google
□ Nach Login: Cookie session_id gesetzt, {"ok":true} im Browser
□ CI auf GitHub grün
```

- [ ] **Schritt 9.5: Phase-0-Tag setzen**

```bash
git tag v0.0.1-phase0
git push origin v0.0.1-phase0
```

---

## Mac → Linux: Was zu tun ist

Alle genutzten Tools sind plattformunabhängig. Beim Wechsel auf die Linux-VM:

```bash
# 1. uv installieren
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Repo klonen, .env anlegen
git clone <repo> /opt/kairos && cd /opt/kairos
cp .env.example .env && chmod 600 .env
# .env befüllen (echte Werte)

# 3. Docker starten, Migrationen laufen, App starten
make up
make migrate
make dev   # oder: uvicorn kairos.api:app in einem Screen/tmux

# 4. Für Produktion: deploy/docker-compose.yml nutzen (Dockerfile wird in Phase 0.5 ergänzt)
```

Der einzige Unterschied: `platform: linux/amd64` im Dev-Compose ist auf Linux nicht nötig (dort entfernen oder lassen — schadet nicht).
