# Phase 2 — Metrics-Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic, testable metrics layer for Phase 2 — a code-level registry of pluggable training-load formulas (Edwards-TRIMP, Banister-TRIMP), the two raw-data building-block tables they read from, and the derived metrics (CTL/ATL/TSB, ACWR, Foster Monotony/Strain, HR-Zonen-Zeitverteilung, HRV-Baseline, Schlafschuld, Ruhepuls-Trend) exposed via a `/api/metrics` router.

**Architecture:** Two plain (non-hypertable) Postgres tables hold threshold-independent raw daily building blocks (`hr_bucket_seconds_daily`, `wellness_daily_stats`), kept fresh by an explicit Python recompute function rather than a TimescaleDB Continuous Aggregate — see the Global Constraints entry below for why. All formulas — including HR-zone bucketing itself — run as pure Python functions at query time against those building blocks, so a user can switch training-load formula variants without re-migrating data. A `MetricRegistry` (same register/get pattern as the existing `ConnectorRegistry`) maps `(metric_id, variant_id)` to an async `MetricVariant.compute()`. Every result carries `confidence` + `coverage_days`, per the data-model doc's requirement that low-coverage numbers are flagged, not silently returned.

**Tech Stack:** Python 3.13, SQLAlchemy 2.0 async, plain Postgres tables (RLS-enabled), pytest (stdlib `statistics` for mean/stdev — no new dependency).

## Global Constraints

- No new third-party dependencies. `statistics.mean`/`statistics.pstdev` from stdlib cover every formula below.
- Every `MetricVariant.compute()` returns a `MetricResult` with `confidence` ∈ `{"high", "medium", "low", "insufficient_data"}` and `coverage_days` — never raises for missing data, never silently substitutes zero.
- **Canonical training load is always Edwards-TRIMP.** CTL/ATL/TSB, ACWR, and Foster Monotony/Strain read the Edwards-TRIMP daily series regardless of which TRIMP variant is currently displayed on a dashboard tile. This is a deliberate decision (confirmed with the user 2026-08-10) to keep the long-run training-load curve free of discontinuities when a user toggles the displayed formula.
- **Plain tables + explicit recompute, not TimescaleDB Continuous Aggregates.** Originally planned as CAggs; ruled out after implementation because TimescaleDB cannot create a Continuous Aggregate on a hypertable with row-level security enabled — a permanent, documented limitation (timescale/timescaledb#5787), not a version bug, and confirmed independently for the sibling compression/RLS restriction (timescale/timescaledb#6827) that forced the same call in the preceding hypertables migration. RLS is non-negotiable per `CLAUDE.md`. Decided with the user 2026-08-10: `hr_bucket_seconds_daily` and `wellness_daily_stats` are plain RLS-enabled Postgres tables, populated by an explicit `recompute_*` function (Task 2) instead of an automatic Timescale refresh policy. Wiring that function into a periodic scheduler is out of scope for this plan (no scheduler infrastructure exists yet in this codebase) — tests call it directly with an explicit date range, exactly as a future scheduler call would.
- **`metric_daily` is not a persisted table in this plan.** `02-datenmodell-und-volumen.md` describes it as a derived, fully-rebuildable cache; per that same doc the entire 5-user/5-year dataset is ~9,000 rows, so on-demand computation from the two raw-building-block tables has no realistic performance cost. Every derived-metric function recomputes from `hr_bucket_seconds_daily`/`wellness_daily_stats` on each call. A cache table can be added later without touching any formula function — none of them assume persistence.
- Day boundaries in the two raw-building-block tables are bucketed in **UTC**, not per-user local time, using the `(col AT TIME ZONE 'UTC')::date` idiom (deterministic regardless of session `TimeZone` setting — a bare `::date` cast on a `timestamptz` is not). `02-datenmodell-und-volumen.md` §2.7 calls for local-timezone day boundaries; this plan takes the UTC approximation for V1 and documents it here as a known simplification (affects users only around midnight local time, not close to launch-critical for the single current user in `Europe/Berlin`, a 1–2h offset from UTC).
- Every DB-touching test in this plan uses the existing `tests/conftest.py` `session`/`app_session` fixtures (testcontainers, skipped without Docker). Every pure-formula test is a plain, no-fixture `pytest` function — the majority of this plan's tasks need **no Docker at all** to develop and verify.
- `mypy --strict` and `ruff check` (line-length 100) must pass on every file this plan touches, per `CLAUDE.md`.
- Migrations chain off the current head `6bf30be597a0` (hypertables migration).

---

## File Structure

```
alembic/versions/
  f67b0560a2ad_user_setting.py                  new table
  339358b313ef_metrics_raw_tables.py             two raw-building-block tables (plain, RLS-enabled)

src/kairos/db/models.py                          + UserSetting model

src/kairos/metrics/
  types.py                 MetricResult, Confidence
  registry.py               MetricRegistry (mirrors ConnectorRegistry)
  hr_zones.py                pure zone-boundary functions
  bootstrap.py                build_default_registry()
  formulas/
    edwards_trimp.py         pure Edwards-TRIMP calculation
    banister_trimp.py        pure Banister-TRIMP calculation
    training_load.py         pure CTL/ATL/TSB (Banister EWMA)
    acwr.py                  pure 7:28 ACWR ratio + risk band
    monotony_strain.py       pure Foster Monotony/Strain
    hrv_baseline.py          pure 60-day HRV baseline band
    sleep_debt.py            pure rolling sleep-debt calculation
    resting_hr_trend.py      pure 7d-vs-30d resting-HR trend
  variants/
    edwards_trimp_variant.py    MetricVariant wiring formula + repo
    banister_trimp_variant.py
    hr_zone_distribution_variant.py
    training_load_variant.py    (CTL/ATL/TSB)
    acwr_variant.py
    monotony_strain_variant.py
    hrv_baseline_variant.py
    sleep_debt_variant.py
    resting_hr_trend_variant.py

src/kairos/repositories/
  user_setting.py            get_or_default(session, user_id) -> UserSettingData
  metrics_recompute.py       recompute_hr_bucket_seconds_daily(), recompute_wellness_daily_stats()
  metrics_data.py            hr_bucket_seconds(), wellness_daily_stat(), edwards_daily_load_series(), resting_hr_for_day()

src/kairos/routers/metrics.py   GET /api/metrics/{metric_id}, GET /api/metrics/{metric_id}/variants
src/kairos/api.py                + metrics_router

tests/
  test_hr_zones.py
  test_edwards_trimp_formula.py
  test_banister_trimp_formula.py
  test_training_load_formula.py
  test_acwr_formula.py
  test_monotony_strain_formula.py
  test_hrv_baseline_formula.py
  test_sleep_debt_formula.py
  test_resting_hr_trend_formula.py
  test_metric_registry.py
  test_metrics_recompute_integration.py      (Docker-gated)
  test_metrics_repositories_integration.py   (Docker-gated)
  test_metrics_router.py
```

---

### Task 1: `user_setting` table

**Files:**
- Modify: `src/kairos/db/models.py` (add `UserSetting` after `AppUser`)
- Create: `alembic/versions/f67b0560a2ad_user_setting.py`
- Test: `tests/test_garmin_repositories_integration.py` is **not** touched; new model has no dedicated unit test (it's a pure SQLAlchemy declarative mapping, exercised by Task 15's integration test)

**Interfaces:**
- Produces: `UserSetting` ORM class with columns `user_id (PK, FK app_user.id)`, `birth_date: date | None`, `sex: str | None` (`'male' | 'female'`), `resting_hr_override: int | None`, `hr_max_override: int | None`, `sleep_target_hours: float` (default `8.0`)

- [ ] **Step 1: Add the model**

```python
# src/kairos/db/models.py — append after AppUser class

class UserSetting(Base):
    __tablename__ = "user_setting"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("app_user.id", ondelete="CASCADE"),
        primary_key=True,
    )
    birth_date: Mapped[date | None] = mapped_column(Date)
    sex: Mapped[str | None] = mapped_column(Text)
    resting_hr_override: Mapped[int | None] = mapped_column(SmallInteger)
    hr_max_override: Mapped[int | None] = mapped_column(SmallInteger)
    sleep_target_hours: Mapped[float] = mapped_column(Float, nullable=False, default=8.0)

    __table_args__ = (
        CheckConstraint("sex IN ('male', 'female')", name="user_setting_sex_check"),
    )
```

- [ ] **Step 2: Write the migration**

```python
# alembic/versions/f67b0560a2ad_user_setting.py
"""user_setting

Revision ID: f67b0560a2ad
Revises: 6bf30be597a0
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f67b0560a2ad"
down_revision: str | None = "6bf30be597a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_setting",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=True),
        sa.Column("sex", sa.Text(), nullable=True),
        sa.Column("resting_hr_override", sa.SmallInteger(), nullable=True),
        sa.Column("hr_max_override", sa.SmallInteger(), nullable=True),
        sa.Column("sleep_target_hours", sa.Float(), nullable=False, server_default="8.0"),
        sa.CheckConstraint("sex IN ('male', 'female')", name="user_setting_sex_check"),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.execute("ALTER TABLE user_setting ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON user_setting "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE user_setting FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON user_setting")
    op.execute("ALTER TABLE user_setting NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_setting DISABLE ROW LEVEL SECURITY")
    op.drop_table("user_setting")
```

- [ ] **Step 3: Verify migration applies cleanly (requires Docker)**

Run: `.venv/Scripts/python -m pytest tests/test_garmin_repositories_integration.py -q`
Expected: PASS (this suite runs `alembic upgrade head` as part of its `run_migrations` fixture; if `user_setting` has a typo this fails here)

If Docker is unavailable, skip this step for now and revisit once it is — nothing later in this plan blocks on it.

- [ ] **Step 4: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/db/models.py alembic/versions/f67b0560a2ad_user_setting.py && .venv/Scripts/python -m mypy --strict src/kairos/db/models.py`
Expected: both clean

- [ ] **Step 5: Commit**

```bash
git add src/kairos/db/models.py alembic/versions/f67b0560a2ad_user_setting.py
git commit -m "feat(phase-2): add user_setting table for metric formula inputs"
```

---

### Task 2: Raw-building-block tables + recompute functions

**Files:**
- Create: `alembic/versions/339358b313ef_metrics_raw_tables.py`
- Create: `src/kairos/repositories/metrics_recompute.py`
- Test: `tests/test_metrics_recompute_integration.py` (Docker-gated)

**Interfaces:**
- Produces two plain (non-hypertable) RLS-enabled tables:
  - `hr_bucket_seconds_daily(user_id uuid, day date, bpm_bucket smallint, seconds bigint)`, PK `(user_id, day, bpm_bucket)` — one row per 5-bpm bucket per user per day
  - `wellness_daily_stats(user_id uuid, metric_id int, day date, avg_value real, min_value real, max_value real, sample_count bigint)`, PK `(user_id, metric_id, day)` — one row per metric per user per day
- Produces:
  - `async def recompute_hr_bucket_seconds_daily(session: AsyncSession, *, user_id: UUID, start: date, end: date) -> None` — recomputes from `activity_record` where `metric = 'hr'`, inclusive date range
  - `async def recompute_wellness_daily_stats(session: AsyncSession, *, user_id: UUID, start: date, end: date) -> None` — recomputes from `wellness_sample`, inclusive date range

- [ ] **Step 1: Write the migration**

```python
# alembic/versions/339358b313ef_metrics_raw_tables.py
"""metrics_raw_tables

Revision ID: 339358b313ef
Revises: f67b0560a2ad
Create Date: 2026-08-10 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "339358b313ef"
down_revision: str | None = "f67b0560a2ad"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Plain tables, not TimescaleDB Continuous Aggregates: Timescale cannot create
# a Continuous Aggregate on a hypertable with row-level security enabled
# (timescale/timescaledb#5787, a permanent limitation). Both source tables
# (activity_record, wellness_sample) have FORCE ROW LEVEL SECURITY, which is
# non-negotiable per CLAUDE.md. Kept fresh by an explicit recompute function
# (src/kairos/repositories/metrics_recompute.py) instead.

_TABLES = ("hr_bucket_seconds_daily", "wellness_daily_stats")


def upgrade() -> None:
    op.create_table(
        "hr_bucket_seconds_daily",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("bpm_bucket", sa.SmallInteger(), nullable=False),
        sa.Column("seconds", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "day", "bpm_bucket"),
    )
    op.create_table(
        "wellness_daily_stats",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("metric_id", sa.Integer(), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("avg_value", sa.Float(), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=False),
        sa.Column("max_value", sa.Float(), nullable=False),
        sa.Column("sample_count", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["metric_id"], ["metric_def.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("user_id", "metric_id", "day"),
    )

    for table in _TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {table} "
            f"USING (user_id = current_setting('app.current_user_id', true)::uuid)"
        )
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.drop_table("wellness_daily_stats")
    op.drop_table("hr_bucket_seconds_daily")
```

- [ ] **Step 2: Write the failing integration test**

```python
# tests/test_metrics_recompute_integration.py
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_wellness_daily_stats,
)


async def _insert_user(session: AsyncSession, user_id) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_recompute_hr_bucket_seconds_daily_groups_by_5bpm_bucket(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.execute(
        text(
            "INSERT INTO activity (id, user_id, external_id, start_at) "
            "VALUES (1, :uid, 'ext-1', :start_at)"
        ),
        {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
    )
    for i in range(3):
        await session.execute(
            text(
                "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
                "VALUES (:uid, 1, :ts, 'hr', 142.0)"
            ),
            {"uid": str(user_id), "ts": datetime(2026, 8, 1, 9, 0, i, tzinfo=UTC)},
        )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    rows = (
        await session.execute(
            text(
                "SELECT bpm_bucket, seconds FROM hr_bucket_seconds_daily WHERE user_id = :uid"
            ),
            {"uid": str(user_id)},
        )
    ).all()

    assert rows == [(140, 3)]


@pytest.mark.asyncio
async def test_recompute_is_idempotent_for_the_same_range(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.execute(
        text(
            "INSERT INTO activity (id, user_id, external_id, start_at) "
            "VALUES (1, :uid, 'ext-1', :start_at)"
        ),
        {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
    )
    await session.execute(
        text(
            "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
            "VALUES (:uid, 1, :ts, 'hr', 142.0)"
        ),
        {"uid": str(user_id), "ts": datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC)},
    )
    await session.commit()

    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    count = (
        await session.execute(
            text("SELECT count(*) FROM hr_bucket_seconds_daily WHERE user_id = :uid"),
            {"uid": str(user_id)},
        )
    ).scalar_one()

    assert count == 1


@pytest.mark.asyncio
async def test_recompute_wellness_daily_stats_aggregates_per_metric_per_day(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    metric_id = (
        await session.execute(text("SELECT id FROM metric_def WHERE code = 'hr'"))
    ).scalar_one()
    for value in (50.0, 60.0, 70.0):
        await session.execute(
            text(
                "INSERT INTO wellness_sample (user_id, metric_id, observed_at, value) "
                "VALUES (:uid, :mid, :ts, :val)"
            ),
            {
                "uid": str(user_id), "mid": metric_id,
                "ts": datetime(2026, 8, 1, 9, 0, 0, tzinfo=UTC), "val": value,
            },
        )
    await session.commit()

    await recompute_wellness_daily_stats(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    row = (
        await session.execute(
            text(
                "SELECT avg_value, min_value, max_value, sample_count "
                "FROM wellness_daily_stats WHERE user_id = :uid AND metric_id = :mid"
            ),
            {"uid": str(user_id), "mid": metric_id},
        )
    ).one()

    assert row == (60.0, 50.0, 70.0, 3)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_recompute_integration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.repositories.metrics_recompute'` (or skipped if Docker unavailable — in that case, proceed to Step 4 and defer verification to when Docker is up)

- [ ] **Step 4: Implement the recompute functions**

```python
# src/kairos/repositories/metrics_recompute.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def recompute_hr_bucket_seconds_daily(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    await session.execute(
        text(
            "DELETE FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    await session.execute(
        text(
            """
            INSERT INTO hr_bucket_seconds_daily (user_id, day, bpm_bucket, seconds)
            SELECT
                user_id,
                (recorded_at AT TIME ZONE 'UTC')::date AS day,
                (floor(value / 5) * 5)::smallint AS bpm_bucket,
                count(*) AS seconds
            FROM activity_record
            WHERE metric = 'hr' AND user_id = :uid
              AND (recorded_at AT TIME ZONE 'UTC')::date >= :start
              AND (recorded_at AT TIME ZONE 'UTC')::date <= :end
            GROUP BY user_id, (recorded_at AT TIME ZONE 'UTC')::date,
                     (floor(value / 5) * 5)::smallint
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )


async def recompute_wellness_daily_stats(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> None:
    await session.execute(
        text(
            "DELETE FROM wellness_daily_stats "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    await session.execute(
        text(
            """
            INSERT INTO wellness_daily_stats
                (user_id, metric_id, day, avg_value, min_value, max_value, sample_count)
            SELECT
                user_id,
                metric_id,
                (observed_at AT TIME ZONE 'UTC')::date AS day,
                avg(value), min(value), max(value), count(*)
            FROM wellness_sample
            WHERE user_id = :uid
              AND (observed_at AT TIME ZONE 'UTC')::date >= :start
              AND (observed_at AT TIME ZONE 'UTC')::date <= :end
            GROUP BY user_id, metric_id, (observed_at AT TIME ZONE 'UTC')::date
            """
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
```

- [ ] **Step 5: Run test to verify it passes (requires Docker)**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_recompute_integration.py -v`
Expected: PASS

- [ ] **Step 6: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check alembic/versions/339358b313ef_metrics_raw_tables.py src/kairos/repositories/metrics_recompute.py tests/test_metrics_recompute_integration.py && .venv/Scripts/python -m mypy --strict src/kairos/repositories/metrics_recompute.py`
Expected: clean

- [ ] **Step 7: Commit**

```bash
git add alembic/versions/339358b313ef_metrics_raw_tables.py src/kairos/repositories/metrics_recompute.py tests/test_metrics_recompute_integration.py
git commit -m "feat(phase-2): raw-building-block tables + recompute functions (RLS-compatible, not Timescale CAggs)"
```

---

### Task 3: Metrics data-access repository

**Files:**
- Create: `src/kairos/repositories/metrics_data.py`
- Create: `src/kairos/repositories/user_setting.py`
- Test: `tests/test_metrics_repositories_integration.py` (Docker-gated)

**Interfaces:**
- Consumes: `hr_bucket_seconds_daily`, `wellness_daily_stats` tables and `recompute_hr_bucket_seconds_daily()` from Task 2; `UserSetting` model from Task 1
- Produces:
  - `async def hr_bucket_seconds(session: AsyncSession, *, user_id: UUID, day: date) -> dict[int, float]` — `{bpm_bucket: seconds}`
  - `async def hr_bucket_seconds_range(session: AsyncSession, *, user_id: UUID, start: date, end: date) -> dict[date, dict[int, float]]`
  - `async def wellness_daily_stat(session: AsyncSession, *, user_id: UUID, metric_code: str, day: date) -> WellnessDayStat | None`
  - `async def wellness_daily_stat_range(session: AsyncSession, *, user_id: UUID, metric_code: str, start: date, end: date) -> dict[date, WellnessDayStat]`
  - `async def observed_max_hr_ever(session: AsyncSession, *, user_id: UUID) -> int | None` — `MAX(activity.max_hr)`
  - `@dataclass(frozen=True) class WellnessDayStat: avg: float; min: float; max: float; sample_count: int`
  - `async def get_or_default_user_setting(session: AsyncSession, *, user_id: UUID) -> UserSettingData`
  - `@dataclass(frozen=True) class UserSettingData: birth_date: date | None; sex: str | None; resting_hr_override: int | None; hr_max_override: int | None; sleep_target_hours: float`

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_metrics_repositories_integration.py
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_data import (
    hr_bucket_seconds,
    observed_max_hr_ever,
    wellness_daily_stat,
)
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily
from kairos.repositories.user_setting import get_or_default_user_setting


async def _insert_user(session: AsyncSession, user_id) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


@pytest.mark.asyncio
async def test_get_or_default_user_setting_returns_defaults_when_absent(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    await session.commit()

    setting = await get_or_default_user_setting(session, user_id=user_id)

    assert setting.sleep_target_hours == 8.0
    assert setting.birth_date is None
    assert setting.hr_max_override is None


@pytest.mark.asyncio
async def test_hr_bucket_seconds_aggregates_activity_record_by_day(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    activity_id = (
        await session.execute(
            text(
                """
                INSERT INTO activity (user_id, external_id, start_at)
                VALUES (:uid, 'ext-1', :start_at)
                RETURNING id
                """
            ),
            {"uid": str(user_id), "start_at": datetime(2026, 8, 1, 9, 0, tzinfo=UTC)},
        )
    ).scalar_one()
    rows = [
        {
            "uid": str(user_id), "aid": activity_id,
            "ts": datetime(2026, 8, 1, 9, 0, i, tzinfo=UTC), "hr": 142.0,
        }
        for i in range(3)
    ]
    for row in rows:
        await session.execute(
            text(
                """
                INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value)
                VALUES (:uid, :aid, :ts, 'hr', :hr)
                """
            ),
            row,
        )
    await session.commit()
    await recompute_hr_bucket_seconds_daily(
        session, user_id=user_id, start=date(2026, 8, 1), end=date(2026, 8, 1)
    )
    await session.commit()

    buckets = await hr_bucket_seconds(session, user_id=user_id, day=date(2026, 8, 1))

    assert buckets == {140: 3.0}
```

**Note on test data:** `activity.id` is a global `BigInteger, autoincrement=True` PK, not scoped per test or per user — the `session` fixture runs against a session-scoped, shared testcontainer, so committed rows from earlier tests in the same run persist. Never hardcode an `activity.id` literal; always let Postgres assign it and capture it via `RETURNING id`, as above. (Confirmed necessary in Task 2: a hardcoded `activity.id = 1` in that task's own test collided with another test's row in the same run.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_repositories_integration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.repositories.metrics_data'` (or skipped if Docker unavailable — in that case, proceed to Step 3 and defer verification to when Docker is up)

- [ ] **Step 3: Implement the repositories**

```python
# src/kairos/repositories/user_setting.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.db.models import UserSetting


@dataclass(frozen=True)
class UserSettingData:
    birth_date: date | None
    sex: str | None
    resting_hr_override: int | None
    hr_max_override: int | None
    sleep_target_hours: float


_DEFAULT = UserSettingData(
    birth_date=None,
    sex=None,
    resting_hr_override=None,
    hr_max_override=None,
    sleep_target_hours=8.0,
)


async def get_or_default_user_setting(session: AsyncSession, *, user_id: UUID) -> UserSettingData:
    row = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return _DEFAULT
    return UserSettingData(
        birth_date=row.birth_date,
        sex=row.sex,
        resting_hr_override=row.resting_hr_override,
        hr_max_override=row.hr_max_override,
        sleep_target_hours=row.sleep_target_hours,
    )
```

```python
# src/kairos/repositories/metrics_data.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class WellnessDayStat:
    avg: float
    min: float
    max: float
    sample_count: int


async def hr_bucket_seconds(
    session: AsyncSession, *, user_id: UUID, day: date
) -> dict[int, float]:
    result = await session.execute(
        text(
            "SELECT bpm_bucket, seconds FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day = :day"
        ),
        {"uid": str(user_id), "day": day},
    )
    return {int(bucket): float(seconds) for bucket, seconds in result.all()}


async def hr_bucket_seconds_range(
    session: AsyncSession, *, user_id: UUID, start: date, end: date
) -> dict[date, dict[int, float]]:
    result = await session.execute(
        text(
            "SELECT day, bpm_bucket, seconds FROM hr_bucket_seconds_daily "
            "WHERE user_id = :uid AND day >= :start AND day <= :end"
        ),
        {"uid": str(user_id), "start": start, "end": end},
    )
    out: dict[date, dict[int, float]] = {}
    for day, bucket, seconds in result.all():
        out.setdefault(day, {})[int(bucket)] = float(seconds)
    return out


async def wellness_daily_stat(
    session: AsyncSession, *, user_id: UUID, metric_code: str, day: date
) -> WellnessDayStat | None:
    result = await session.execute(
        text(
            """
            SELECT w.avg_value, w.min_value, w.max_value, w.sample_count
            FROM wellness_daily_stats w
            JOIN metric_def m ON m.id = w.metric_id
            WHERE w.user_id = :uid AND m.code = :code AND w.day = :day
            """
        ),
        {"uid": str(user_id), "code": metric_code, "day": day},
    )
    row = result.first()
    if row is None:
        return None
    return WellnessDayStat(avg=row[0], min=row[1], max=row[2], sample_count=row[3])


async def wellness_daily_stat_range(
    session: AsyncSession, *, user_id: UUID, metric_code: str, start: date, end: date
) -> dict[date, WellnessDayStat]:
    result = await session.execute(
        text(
            """
            SELECT w.day, w.avg_value, w.min_value, w.max_value, w.sample_count
            FROM wellness_daily_stats w
            JOIN metric_def m ON m.id = w.metric_id
            WHERE w.user_id = :uid AND m.code = :code AND w.day >= :start AND w.day <= :end
            """
        ),
        {"uid": str(user_id), "code": metric_code, "start": start, "end": end},
    )
    return {
        day: WellnessDayStat(avg=avg, min=mn, max=mx, sample_count=cnt)
        for day, avg, mn, mx, cnt in result.all()
    }


async def observed_max_hr_ever(session: AsyncSession, *, user_id: UUID) -> int | None:
    result = await session.execute(
        text("SELECT max(max_hr) FROM activity WHERE user_id = :uid"),
        {"uid": str(user_id)},
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None
```

- [ ] **Step 4: Run test to verify it passes (requires Docker)**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_repositories_integration.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/repositories/metrics_data.py src/kairos/repositories/user_setting.py tests/test_metrics_repositories_integration.py && .venv/Scripts/python -m mypy --strict src/kairos/repositories/metrics_data.py src/kairos/repositories/user_setting.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/repositories/metrics_data.py src/kairos/repositories/user_setting.py tests/test_metrics_repositories_integration.py
git commit -m "feat(phase-2): repositories for continuous-aggregate metric building blocks"
```

---

### Task 4: Metric registry core (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/types.py`
- Create: `src/kairos/metrics/registry.py`
- Test: `tests/test_metric_registry.py`

**Interfaces:**
- Produces: `Confidence` type alias, `MetricResult` dataclass, `MetricVariant` Protocol, `MetricRegistry` class — used by every task from here on

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metric_registry.py
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest

from kairos.metrics.registry import MetricRegistry
from kairos.metrics.types import MetricResult


class _StubVariant:
    def __init__(self, metric_id: str, variant_id: str) -> None:
        self.metric_id = metric_id
        self.variant_id = variant_id

    async def compute(self, session: object, *, user_id: UUID, as_of: date) -> MetricResult:
        del session, user_id, as_of
        return MetricResult(
            value=1.0, unit="pt", confidence="high", coverage_days=7,
            coverage_required_days=7, as_of="2026-08-10",
        )


def test_register_and_get_variant() -> None:
    registry = MetricRegistry()
    variant = _StubVariant("trimp", "edwards")
    registry.register(variant)

    assert registry.get("trimp", "edwards") is variant
    assert registry.variants_for("trimp") == ["edwards"]
    assert registry.metric_ids() == ["trimp"]


def test_register_duplicate_raises() -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant("trimp", "edwards"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_StubVariant("trimp", "edwards"))


@pytest.mark.asyncio
async def test_compute_returns_metric_result() -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant("trimp", "edwards"))

    result = await registry.get("trimp", "edwards").compute(
        session=None, user_id=uuid4(), as_of=date(2026, 8, 10)
    )

    assert result.confidence == "high"
    assert result.value == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_metric_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.metrics'`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/types.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium", "low", "insufficient_data"]


@dataclass(frozen=True)
class MetricResult:
    value: float | dict[str, float] | None
    unit: str
    confidence: Confidence
    coverage_days: int
    coverage_required_days: int
    as_of: str
```

```python
# src/kairos/metrics/registry.py
from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.types import MetricResult


class MetricVariant(Protocol):
    metric_id: str
    variant_id: str

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult: ...


class MetricRegistry:
    def __init__(self) -> None:
        self._variants: dict[tuple[str, str], MetricVariant] = {}

    def register(self, variant: MetricVariant) -> None:
        key = (variant.metric_id, variant.variant_id)
        if key in self._variants:
            raise ValueError(f"Metric variant already registered: {key}")
        self._variants[key] = variant

    def get(self, metric_id: str, variant_id: str) -> MetricVariant:
        return self._variants[(metric_id, variant_id)]

    def variants_for(self, metric_id: str) -> list[str]:
        return sorted(v for (m, v) in self._variants if m == metric_id)

    def metric_ids(self) -> list[str]:
        return sorted({m for (m, _v) in self._variants})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_metric_registry.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/ tests/test_metric_registry.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/types.py src/kairos/metrics/registry.py tests/test_metric_registry.py
git commit -m "feat(phase-2): metric registry core (MetricResult, MetricVariant, MetricRegistry)"
```

---

### Task 5: HR zone boundary functions (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/hr_zones.py`
- Test: `tests/test_hr_zones.py`

**Interfaces:**
- Produces: `HrZoneBounds` dataclass (`name`, `low_bpm`, `high_bpm`, `multiplier`), `percent_max_zones(hr_max: float) -> list[HrZoneBounds]`, `karvonen_zones(hr_max: float, resting_hr: float) -> list[HrZoneBounds]`, `estimate_hr_max(birth_date: date | None, hr_max_override: int | None, observed_max_hr: int | None, *, as_of: date) -> int | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hr_zones.py
from __future__ import annotations

from datetime import date

from kairos.metrics.hr_zones import estimate_hr_max, karvonen_zones, percent_max_zones


def test_percent_max_zones_covers_50_to_100_percent() -> None:
    zones = percent_max_zones(hr_max=190.0)

    assert [z.name for z in zones] == ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5"]
    assert zones[0].low_bpm == 95.0  # 50% of 190
    assert zones[4].high_bpm == 190.0  # 100% of 190
    assert [z.multiplier for z in zones] == [1, 2, 3, 4, 5]


def test_karvonen_zones_use_heart_rate_reserve() -> None:
    zones = karvonen_zones(hr_max=190.0, resting_hr=50.0)
    # reserve = 140; zone_1 low = 50 + 140*0.50 = 120
    assert zones[0].low_bpm == 120.0
    assert zones[4].high_bpm == 190.0


def test_estimate_hr_max_prefers_override() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 1, 1), hr_max_override=200, observed_max_hr=180,
        as_of=date(2026, 8, 10),
    )
    assert result == 200


def test_estimate_hr_max_uses_age_formula_when_no_override() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 8, 10), hr_max_override=None, observed_max_hr=None,
        as_of=date(2026, 8, 10),
    )
    assert result == 184  # 220 - 36


def test_estimate_hr_max_raises_estimate_to_observed_max_if_higher() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 8, 10), hr_max_override=None, observed_max_hr=195,
        as_of=date(2026, 8, 10),
    )
    assert result == 195  # observed effort exceeded the age-based estimate


def test_estimate_hr_max_returns_none_without_any_input() -> None:
    result = estimate_hr_max(
        birth_date=None, hr_max_override=None, observed_max_hr=None, as_of=date(2026, 8, 10)
    )
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_hr_zones.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.metrics.hr_zones'`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/hr_zones.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

_ZONE_FRACTIONS: tuple[tuple[float, float, int], ...] = (
    (0.50, 0.60, 1),
    (0.60, 0.70, 2),
    (0.70, 0.80, 3),
    (0.80, 0.90, 4),
    (0.90, 1.00, 5),
)


@dataclass(frozen=True)
class HrZoneBounds:
    name: str
    low_bpm: float
    high_bpm: float
    multiplier: int


def percent_max_zones(hr_max: float) -> list[HrZoneBounds]:
    return [
        HrZoneBounds(f"zone_{i + 1}", hr_max * lo, hr_max * hi, mult)
        for i, (lo, hi, mult) in enumerate(_ZONE_FRACTIONS)
    ]


def karvonen_zones(hr_max: float, resting_hr: float) -> list[HrZoneBounds]:
    reserve = hr_max - resting_hr
    return [
        HrZoneBounds(f"zone_{i + 1}", resting_hr + reserve * lo, resting_hr + reserve * hi, mult)
        for i, (lo, hi, mult) in enumerate(_ZONE_FRACTIONS)
    ]


def estimate_hr_max(
    birth_date: date | None,
    hr_max_override: int | None,
    observed_max_hr: int | None,
    *,
    as_of: date,
) -> int | None:
    if hr_max_override is not None:
        return hr_max_override
    age_estimate: int | None = None
    if birth_date is not None:
        age = as_of.year - birth_date.year - (
            (as_of.month, as_of.day) < (birth_date.month, birth_date.day)
        )
        age_estimate = 220 - age
    candidates = [v for v in (age_estimate, observed_max_hr) if v is not None]
    return max(candidates) if candidates else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_hr_zones.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/hr_zones.py tests/test_hr_zones.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/hr_zones.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/hr_zones.py tests/test_hr_zones.py
git commit -m "feat(phase-2): HR zone boundary formulas (%HRmax and Karvonen/HRR)"
```

---

### Task 6: Edwards-TRIMP formula (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/edwards_trimp.py`
- Test: `tests/test_edwards_trimp_formula.py`

**Interfaces:**
- Consumes: `HrZoneBounds` from Task 5
- Produces: `def edwards_trimp(bucket_seconds: dict[int, float], zones: list[HrZoneBounds]) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_edwards_trimp_formula.py
from __future__ import annotations

from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import percent_max_zones


def test_edwards_trimp_weights_each_zone_by_its_multiplier() -> None:
    zones = percent_max_zones(hr_max=190.0)  # zone_1: 95-114, zone_2: 114-133, ...
    # 600s (10 min) at 100 bpm (zone_1, mult=1) + 600s at 120 bpm (zone_2, mult=2)
    buckets = {100: 600.0, 120: 600.0}

    result = edwards_trimp(buckets, zones)

    assert result == 30.0  # 10min*1 + 10min*2


def test_edwards_trimp_ignores_seconds_below_zone_1() -> None:
    zones = percent_max_zones(hr_max=190.0)
    buckets = {60: 3600.0}  # resting HR, below zone_1 (95 bpm)

    result = edwards_trimp(buckets, zones)

    assert result == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_edwards_trimp_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/edwards_trimp.py
from __future__ import annotations

from kairos.metrics.hr_zones import HrZoneBounds


def edwards_trimp(bucket_seconds: dict[int, float], zones: list[HrZoneBounds]) -> float:
    total_minutes_weighted = 0.0
    for bpm_bucket, seconds in bucket_seconds.items():
        zone = _zone_for_bucket(float(bpm_bucket), zones)
        if zone is None:
            continue
        total_minutes_weighted += (seconds / 60.0) * zone.multiplier
    return total_minutes_weighted


def _zone_for_bucket(bpm: float, zones: list[HrZoneBounds]) -> HrZoneBounds | None:
    for zone in zones:
        if zone.low_bpm <= bpm < zone.high_bpm:
            return zone
    if zones and bpm >= zones[-1].high_bpm:
        return zones[-1]
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_edwards_trimp_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/edwards_trimp.py tests/test_edwards_trimp_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/edwards_trimp.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/edwards_trimp.py tests/test_edwards_trimp_formula.py
git commit -m "feat(phase-2): Edwards-TRIMP formula"
```

---

### Task 7: Banister-TRIMP formula (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/banister_trimp.py`
- Test: `tests/test_banister_trimp_formula.py`

**Interfaces:**
- Produces: `def banister_trimp(bucket_seconds: dict[int, float], *, resting_hr: float, hr_max: float, sex: str) -> float | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_banister_trimp_formula.py
from __future__ import annotations

import math

from kairos.metrics.formulas.banister_trimp import banister_trimp


def test_banister_trimp_male_formula() -> None:
    # 30 min at a constant 140 bpm; resting=50, max=190 -> delta_ratio=(140-50)/(190-50)=0.6429
    buckets = {140: 1800.0}

    result = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="male")

    delta = (140 - 50) / (190 - 50)
    expected = 30.0 * delta * 0.64 * math.exp(1.92 * delta)
    assert result is not None
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_banister_trimp_female_uses_different_coefficients() -> None:
    buckets = {140: 1800.0}

    male = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="male")
    female = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="female")

    assert male != female


def test_banister_trimp_returns_none_when_hr_max_equals_resting_hr() -> None:
    result = banister_trimp({140: 600.0}, resting_hr=190.0, hr_max=190.0, sex="male")
    assert result is None


def test_banister_trimp_returns_zero_for_no_data() -> None:
    result = banister_trimp({}, resting_hr=50.0, hr_max=190.0, sex="male")
    assert result == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_banister_trimp_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/banister_trimp.py
from __future__ import annotations

import math

_COEFFICIENTS = {"male": 0.64, "female": 0.86}
_EXPONENTS = {"male": 1.92, "female": 1.67}


def banister_trimp(
    bucket_seconds: dict[int, float], *, resting_hr: float, hr_max: float, sex: str
) -> float | None:
    if hr_max <= resting_hr:
        return None
    if not bucket_seconds:
        return 0.0

    total_seconds = sum(bucket_seconds.values())
    weighted_bpm = sum(bpm * secs for bpm, secs in bucket_seconds.items()) / total_seconds
    duration_min = total_seconds / 60.0
    delta_ratio = (weighted_bpm - resting_hr) / (hr_max - resting_hr)
    coefficient = _COEFFICIENTS[sex]
    exponent = _EXPONENTS[sex]
    return duration_min * delta_ratio * coefficient * math.exp(exponent * delta_ratio)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_banister_trimp_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/banister_trimp.py tests/test_banister_trimp_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/banister_trimp.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/banister_trimp.py tests/test_banister_trimp_formula.py
git commit -m "feat(phase-2): Banister-TRIMP formula"
```

---

### Task 8: CTL/ATL/TSB (Banister training load, no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/training_load.py`
- Test: `tests/test_training_load_formula.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class LoadState: day: date; ctl: float; atl: float; tsb: float` and `def training_load(daily_load: dict[date, float], *, tau_ctl: int = 42, tau_atl: int = 7) -> list[LoadState]` (input ordered by date ascending; missing days count as `0.0` load)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_training_load_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.training_load import training_load


def test_training_load_ewma_converges_toward_constant_load() -> None:
    start = date(2026, 1, 1)
    daily_load = {start + timedelta(days=i): 50.0 for i in range(100)}

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    assert len(states) == 100
    # after 100 days of constant load, CTL/ATL should have converged near 50
    assert abs(states[-1].ctl - 50.0) < 1.0
    assert abs(states[-1].atl - 50.0) < 0.1
    assert abs(states[-1].tsb) < 1.0


def test_training_load_tsb_is_ctl_minus_atl_same_day() -> None:
    start = date(2026, 1, 1)
    daily_load = {start: 100.0, start + timedelta(days=1): 0.0}

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    for state in states:
        assert state.tsb == state.ctl - state.atl


def test_training_load_fills_gaps_with_zero() -> None:
    start = date(2026, 1, 1)
    daily_load = {start: 100.0, start + timedelta(days=2): 100.0}  # day+1 missing

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    assert [s.day for s in states] == [start, start + timedelta(days=1), start + timedelta(days=2)]
    # day+1 had zero load, so ATL should dip between day 0 and day 2
    assert states[1].atl < states[0].atl
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_training_load_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/training_load.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class LoadState:
    day: date
    ctl: float
    atl: float
    tsb: float


def training_load(
    daily_load: dict[date, float], *, tau_ctl: int = 42, tau_atl: int = 7
) -> list[LoadState]:
    if not daily_load:
        return []

    start = min(daily_load)
    end = max(daily_load)

    states: list[LoadState] = []
    ctl = 0.0
    atl = 0.0
    day = start
    while day <= end:
        load = daily_load.get(day, 0.0)
        ctl += (load - ctl) / tau_ctl
        atl += (load - atl) / tau_atl
        states.append(LoadState(day=day, ctl=ctl, atl=atl, tsb=ctl - atl))
        day += timedelta(days=1)
    return states
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_training_load_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/training_load.py tests/test_training_load_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/training_load.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/training_load.py tests/test_training_load_formula.py
git commit -m "feat(phase-2): CTL/ATL/TSB Banister training-load formula"
```

---

### Task 9: ACWR (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/acwr.py`
- Test: `tests/test_acwr_formula.py`

**Interfaces:**
- Produces: `RiskBand = Literal["undertraining", "sweet_spot", "caution", "high_risk"]`, `@dataclass(frozen=True) class AcwrResult: ratio: float; risk_band: RiskBand`, `def acwr(daily_load: dict[date, float], *, as_of: date, acute_days: int = 7, chronic_days: int = 28) -> AcwrResult | None` (returns `None` if fewer than `acute_days` chronic-window days have any recorded load)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_acwr_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.acwr import acwr


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_acwr_sweet_spot_when_acute_matches_chronic() -> None:
    start = date(2026, 1, 1)
    load = _series(start, [50.0] * 28)

    result = acwr(load, as_of=start + timedelta(days=27), acute_days=7, chronic_days=28)

    assert result is not None
    assert 0.9 <= result.ratio <= 1.1
    assert result.risk_band == "sweet_spot"


def test_acwr_high_risk_on_load_spike() -> None:
    start = date(2026, 1, 1)
    load = _series(start, [20.0] * 21 + [80.0] * 7)  # 28 days, last 7 spiked

    result = acwr(load, as_of=start + timedelta(days=27), acute_days=7, chronic_days=28)

    assert result is not None
    assert result.ratio > 1.5
    assert result.risk_band == "high_risk"


def test_acwr_returns_none_with_insufficient_history() -> None:
    load = {date(2026, 1, 1): 50.0, date(2026, 1, 2): 50.0}

    result = acwr(load, as_of=date(2026, 1, 2), acute_days=7, chronic_days=28)

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_acwr_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/acwr.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

RiskBand = Literal["undertraining", "sweet_spot", "caution", "high_risk"]


@dataclass(frozen=True)
class AcwrResult:
    ratio: float
    risk_band: RiskBand


def acwr(
    daily_load: dict[date, float],
    *,
    as_of: date,
    acute_days: int = 7,
    chronic_days: int = 28,
) -> AcwrResult | None:
    chronic_start = as_of - timedelta(days=chronic_days - 1)
    chronic_window_days = [chronic_start + timedelta(days=i) for i in range(chronic_days)]
    covered = sum(1 for d in chronic_window_days if d in daily_load)
    if covered < acute_days:
        return None

    acute_start = as_of - timedelta(days=acute_days - 1)
    acute_values = [daily_load.get(acute_start + timedelta(days=i), 0.0) for i in range(acute_days)]
    chronic_values = [daily_load.get(d, 0.0) for d in chronic_window_days]

    acute_mean = sum(acute_values) / acute_days
    chronic_mean = sum(chronic_values) / chronic_days
    if chronic_mean == 0.0:
        return None

    ratio = acute_mean / chronic_mean
    return AcwrResult(ratio=ratio, risk_band=_risk_band(ratio))


def _risk_band(ratio: float) -> RiskBand:
    if ratio < 0.8:
        return "undertraining"
    if ratio <= 1.3:
        return "sweet_spot"
    if ratio <= 1.5:
        return "caution"
    return "high_risk"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_acwr_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/acwr.py tests/test_acwr_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/acwr.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/acwr.py tests/test_acwr_formula.py
git commit -m "feat(phase-2): ACWR 7:28 formula with risk banding"
```

---

### Task 10: Foster Monotony/Strain (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/monotony_strain.py`
- Test: `tests/test_monotony_strain_formula.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class MonotonyStrainResult: monotony: float; strain: float` and `def monotony_strain(daily_load: dict[date, float], *, as_of: date, window_days: int = 7) -> MonotonyStrainResult | None` (returns `None` if fewer than `window_days` of the window have a recorded value, or if the load is constant — population stddev of `0` makes monotony undefined)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_monotony_strain_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.monotony_strain import monotony_strain


def test_monotony_strain_varied_week() -> None:
    start = date(2026, 1, 1)
    values = [10.0, 20.0, 0.0, 30.0, 10.0, 0.0, 40.0]
    load = {start + timedelta(days=i): v for i, v in enumerate(values)}

    result = monotony_strain(load, as_of=start + timedelta(days=6))

    assert result is not None
    mean = sum(values) / 7
    variance = sum((v - mean) ** 2 for v in values) / 7
    stddev = variance**0.5
    assert result.monotony == mean / stddev
    assert result.strain == sum(values) * result.monotony


def test_monotony_strain_returns_none_for_constant_load() -> None:
    start = date(2026, 1, 1)
    load = {start + timedelta(days=i): 25.0 for i in range(7)}

    result = monotony_strain(load, as_of=start + timedelta(days=6))

    assert result is None


def test_monotony_strain_returns_none_with_insufficient_coverage() -> None:
    load = {date(2026, 1, 1): 10.0, date(2026, 1, 2): 20.0}

    result = monotony_strain(load, as_of=date(2026, 1, 2))

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_monotony_strain_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/monotony_strain.py
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MonotonyStrainResult:
    monotony: float
    strain: float


def monotony_strain(
    daily_load: dict[date, float], *, as_of: date, window_days: int = 7
) -> MonotonyStrainResult | None:
    start = as_of - timedelta(days=window_days - 1)
    window = [start + timedelta(days=i) for i in range(window_days)]
    if any(d not in daily_load for d in window):
        return None

    values = [daily_load[d] for d in window]
    stddev = statistics.pstdev(values)
    if stddev == 0.0:
        return None

    monotony = statistics.mean(values) / stddev
    strain = sum(values) * monotony
    return MonotonyStrainResult(monotony=monotony, strain=strain)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_monotony_strain_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/monotony_strain.py tests/test_monotony_strain_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/monotony_strain.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/monotony_strain.py tests/test_monotony_strain_formula.py
git commit -m "feat(phase-2): Foster Monotony/Strain formula"
```

---

### Task 11: HRV-Baseline band (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/hrv_baseline.py`
- Test: `tests/test_hrv_baseline_formula.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class HrvBaselineResult: today: float; baseline_mean: float; baseline_low: float; baseline_high: float; band: Literal["low", "normal", "high"]` and `def hrv_baseline(nightly_hrv: dict[date, float], *, as_of: date, window_days: int = 60, min_coverage_days: int = 20) -> HrvBaselineResult | None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hrv_baseline_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.hrv_baseline import hrv_baseline


def test_hrv_baseline_flags_today_within_normal_band() -> None:
    start = date(2026, 1, 1)
    series = {start + timedelta(days=i): 60.0 for i in range(59)}
    series[start + timedelta(days=59)] = 61.0  # today, close to baseline mean

    result = hrv_baseline(series, as_of=start + timedelta(days=59))

    assert result is not None
    assert result.band == "normal"


def test_hrv_baseline_flags_today_low() -> None:
    start = date(2026, 1, 1)
    series = {start + timedelta(days=i): 60.0 for i in range(59)}
    series[start + timedelta(days=59)] = 30.0  # sharp drop

    result = hrv_baseline(series, as_of=start + timedelta(days=59))

    assert result is not None
    assert result.band == "low"


def test_hrv_baseline_returns_none_with_insufficient_coverage() -> None:
    start = date(2026, 1, 1)
    series = {start + timedelta(days=i): 60.0 for i in range(10)}

    result = hrv_baseline(series, as_of=start + timedelta(days=9), min_coverage_days=20)

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_hrv_baseline_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/hrv_baseline.py
from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Band = Literal["low", "normal", "high"]


@dataclass(frozen=True)
class HrvBaselineResult:
    today: float
    baseline_mean: float
    baseline_low: float
    baseline_high: float
    band: Band


def hrv_baseline(
    nightly_hrv: dict[date, float],
    *,
    as_of: date,
    window_days: int = 60,
    min_coverage_days: int = 20,
) -> HrvBaselineResult | None:
    if as_of not in nightly_hrv:
        return None

    window_start = as_of - timedelta(days=window_days - 1)
    window_values = [v for d, v in nightly_hrv.items() if window_start <= d <= as_of]
    if len(window_values) < min_coverage_days:
        return None

    mean = statistics.mean(window_values)
    stddev = statistics.pstdev(window_values)
    low, high = mean - stddev, mean + stddev
    today = nightly_hrv[as_of]

    if today < low:
        band: Band = "low"
    elif today > high:
        band = "high"
    else:
        band = "normal"

    return HrvBaselineResult(
        today=today, baseline_mean=mean, baseline_low=low, baseline_high=high, band=band
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_hrv_baseline_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/hrv_baseline.py tests/test_hrv_baseline_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/hrv_baseline.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/hrv_baseline.py tests/test_hrv_baseline_formula.py
git commit -m "feat(phase-2): HRV 60-day baseline band formula"
```

---

### Task 12: Schlafschuld / sleep debt (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/sleep_debt.py`
- Test: `tests/test_sleep_debt_formula.py`

**Interfaces:**
- Produces: `def sleep_debt(nightly_hours: dict[date, float], *, as_of: date, target_hours: float, window_days: int = 7) -> float | None` (net cumulative deficit in hours; a surplus night reduces debt; `None` if the window has zero coverage)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sleep_debt_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.sleep_debt import sleep_debt


def test_sleep_debt_accumulates_shortfall() -> None:
    start = date(2026, 1, 1)
    nightly = {start + timedelta(days=i): 6.0 for i in range(7)}  # 2h short every night

    result = sleep_debt(nightly, as_of=start + timedelta(days=6), target_hours=8.0)

    assert result == 14.0  # 7 nights * 2h


def test_sleep_debt_surplus_offsets_deficit() -> None:
    start = date(2026, 1, 1)
    nightly = {start + timedelta(days=i): 6.0 for i in range(6)}
    nightly[start + timedelta(days=6)] = 12.0  # one long recovery night

    result = sleep_debt(nightly, as_of=start + timedelta(days=6), target_hours=8.0)

    assert result == 8.0  # 6*2h deficit - 4h surplus


def test_sleep_debt_returns_none_with_no_data_in_window() -> None:
    result = sleep_debt({}, as_of=date(2026, 1, 7), target_hours=8.0)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sleep_debt_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/sleep_debt.py
from __future__ import annotations

from datetime import date, timedelta


def sleep_debt(
    nightly_hours: dict[date, float], *, as_of: date, target_hours: float, window_days: int = 7
) -> float | None:
    start = as_of - timedelta(days=window_days - 1)
    window = [start + timedelta(days=i) for i in range(window_days)]
    covered = [d for d in window if d in nightly_hours]
    if not covered:
        return None

    return sum(target_hours - nightly_hours[d] for d in covered)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_sleep_debt_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/sleep_debt.py tests/test_sleep_debt_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/sleep_debt.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/sleep_debt.py tests/test_sleep_debt_formula.py
git commit -m "feat(phase-2): rolling sleep-debt formula"
```

---

### Task 13: Ruhepuls-Trend / resting-HR trend (no Docker needed)

**Files:**
- Create: `src/kairos/metrics/formulas/resting_hr_trend.py`
- Test: `tests/test_resting_hr_trend_formula.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) class RestingHrTrendResult: recent_avg: float; prior_avg: float; delta_bpm: float` and `def resting_hr_trend(daily_resting_hr: dict[date, float], *, as_of: date, recent_days: int = 7, prior_days: int = 30, min_recent_coverage: int = 4, min_prior_coverage: int = 15) -> RestingHrTrendResult | None` (prior window is the `prior_days` immediately preceding the recent window — no overlap)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_resting_hr_trend_formula.py
from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.resting_hr_trend import resting_hr_trend


def test_resting_hr_trend_detects_improvement() -> None:
    start = date(2026, 1, 1)
    daily = {}
    for i in range(30):  # prior window: days 0-29, all 55 bpm
        daily[start + timedelta(days=i)] = 55.0
    for i in range(30, 37):  # recent window: days 30-36, all 50 bpm
        daily[start + timedelta(days=i)] = 50.0

    result = resting_hr_trend(daily, as_of=start + timedelta(days=36))

    assert result is not None
    assert result.recent_avg == 50.0
    assert result.prior_avg == 55.0
    assert result.delta_bpm == -5.0


def test_resting_hr_trend_returns_none_with_insufficient_recent_coverage() -> None:
    start = date(2026, 1, 1)
    daily = {start + timedelta(days=i): 55.0 for i in range(30)}
    daily[start + timedelta(days=30)] = 50.0  # only 1 of 7 recent days present

    result = resting_hr_trend(daily, as_of=start + timedelta(days=36))

    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_resting_hr_trend_formula.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# src/kairos/metrics/formulas/resting_hr_trend.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RestingHrTrendResult:
    recent_avg: float
    prior_avg: float
    delta_bpm: float


def resting_hr_trend(
    daily_resting_hr: dict[date, float],
    *,
    as_of: date,
    recent_days: int = 7,
    prior_days: int = 30,
    min_recent_coverage: int = 4,
    min_prior_coverage: int = 15,
) -> RestingHrTrendResult | None:
    recent_start = as_of - timedelta(days=recent_days - 1)
    recent_window = [recent_start + timedelta(days=i) for i in range(recent_days)]
    recent_values = [daily_resting_hr[d] for d in recent_window if d in daily_resting_hr]
    if len(recent_values) < min_recent_coverage:
        return None

    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=prior_days - 1)
    prior_window = [prior_start + timedelta(days=i) for i in range(prior_days)]
    prior_values = [daily_resting_hr[d] for d in prior_window if d in daily_resting_hr]
    if len(prior_values) < min_prior_coverage:
        return None

    recent_avg = sum(recent_values) / len(recent_values)
    prior_avg = sum(prior_values) / len(prior_values)
    return RestingHrTrendResult(
        recent_avg=recent_avg, prior_avg=prior_avg, delta_bpm=recent_avg - prior_avg
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_resting_hr_trend_formula.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/formulas/resting_hr_trend.py tests/test_resting_hr_trend_formula.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/formulas/resting_hr_trend.py`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/formulas/resting_hr_trend.py tests/test_resting_hr_trend_formula.py
git commit -m "feat(phase-2): resting-HR 7d-vs-30d trend formula"
```

---

### Task 14: Wire variants into the registry (requires Docker for its test)

**Files:**
- Create: `src/kairos/metrics/variants/edwards_trimp_variant.py`
- Create: `src/kairos/metrics/variants/banister_trimp_variant.py`
- Create: `src/kairos/metrics/variants/hr_zone_distribution_variant.py`
- Create: `src/kairos/metrics/variants/training_load_variant.py`
- Create: `src/kairos/metrics/variants/acwr_variant.py`
- Create: `src/kairos/metrics/variants/monotony_strain_variant.py`
- Create: `src/kairos/metrics/variants/hrv_baseline_variant.py`
- Create: `src/kairos/metrics/variants/sleep_debt_variant.py`
- Create: `src/kairos/metrics/variants/resting_hr_trend_variant.py`
- Create: `src/kairos/metrics/bootstrap.py`
- Test: `tests/test_metrics_variants_integration.py` (Docker-gated)

**Interfaces:**
- Consumes: every formula from Tasks 6–13, repositories from Task 3, registry from Task 4
- Produces: `def build_default_registry() -> MetricRegistry` — registers all 9 variants under metric_ids `trimp` (variants `edwards`, `banister`), `hr_zone_distribution` (variants `percent_max`, `karvonen`), `training_load`, `acwr`, `monotony_strain`, `hrv_baseline`, `sleep_debt`, `resting_hr_trend` (one variant each, `default`)

- [ ] **Step 1: Write the failing integration test**

```python
# tests/test_metrics_variants_integration.py
from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.bootstrap import build_default_registry
from kairos.repositories.metrics_recompute import recompute_hr_bucket_seconds_daily


async def _insert_user(session: AsyncSession, user_id) -> None:
    await session.execute(
        text(
            """
            INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role)
            VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')
            """
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )


async def _insert_workout(session: AsyncSession, user_id, day: date) -> None:
    activity_id = (
        await session.execute(
            text(
                "INSERT INTO activity (user_id, external_id, start_at) "
                "VALUES (:uid, 'ext-1', :start_at) RETURNING id"
            ),
            {"uid": str(user_id), "start_at": datetime(day.year, day.month, day.day, 9, tzinfo=UTC)},
        )
    ).scalar_one()
    for i in range(600):  # 10 minutes at 150 bpm
        await session.execute(
            text(
                "INSERT INTO activity_record (user_id, activity_id, recorded_at, metric, value) "
                "VALUES (:uid, :aid, :ts, 'hr', 150.0)"
            ),
            {
                "uid": str(user_id), "aid": activity_id,
                "ts": datetime(day.year, day.month, day.day, 9, 0, i % 60, tzinfo=UTC) + __import__("datetime").timedelta(minutes=i // 60),
            },
        )
    await session.commit()
    await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=day, end=day)
    await session.commit()


@pytest.mark.asyncio
async def test_edwards_trimp_variant_computes_from_real_data(session: AsyncSession) -> None:
    user_id = uuid4()
    today = date(2026, 8, 1)
    await _insert_user(session, user_id)
    await _insert_workout(session, user_id, today)

    registry = build_default_registry()
    result = await registry.get("trimp", "edwards").compute(session, user_id=user_id, as_of=today)

    assert result.confidence in ("high", "medium", "low")
    assert isinstance(result.value, float)
    assert result.value > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_variants_integration.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.metrics.bootstrap'` (or skipped if Docker unavailable)

- [ ] **Step 3: Implement the variants**

```python
# src/kairos/metrics/variants/edwards_trimp_variant.py
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import estimate_hr_max, percent_max_zones
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


class EdwardsTrimpVariant:
    metric_id = "trimp"
    variant_id = "edwards"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = percent_max_zones(hr_max)
        value = edwards_trimp(buckets, zones)
        confidence = "high" if buckets else "low"
        return MetricResult(
            value=value, unit="trimp_pt", confidence=confidence,
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )


async def edwards_daily_load_series(
    session: AsyncSession, *, user_id: UUID, end_day: date, days: int
) -> dict[date, float]:
    """Canonical training-load series consumed by CTL/ATL/TSB, ACWR, Monotony/Strain."""
    setting = await get_or_default_user_setting(session, user_id=user_id)
    observed_max = await observed_max_hr_ever(session, user_id=user_id)
    hr_max = estimate_hr_max(
        setting.birth_date, setting.hr_max_override, observed_max, as_of=end_day
    )
    if hr_max is None:
        return {}

    zones = percent_max_zones(hr_max)
    start = end_day - timedelta(days=days - 1)
    from kairos.repositories.metrics_data import hr_bucket_seconds_range

    ranged = await hr_bucket_seconds_range(session, user_id=user_id, start=start, end=end_day)
    return {day: edwards_trimp(buckets, zones) for day, buckets in ranged.items()}
```

```python
# src/kairos/metrics/variants/banister_trimp_variant.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.banister_trimp import banister_trimp
from kairos.metrics.hr_zones import estimate_hr_max
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


class BanisterTrimpVariant:
    metric_id = "trimp"
    variant_id = "banister"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None or setting.sex is None or setting.resting_hr_override is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        value = banister_trimp(
            buckets, resting_hr=float(setting.resting_hr_override), hr_max=float(hr_max),
            sex=setting.sex,
        )
        if value is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        confidence = "high" if buckets else "low"
        return MetricResult(
            value=value, unit="trimp_pt", confidence=confidence,
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/hr_zone_distribution_variant.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.hr_zones import estimate_hr_max, karvonen_zones, percent_max_zones
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


def _zone_seconds(buckets: dict[int, float], zones: list) -> dict[str, float]:  # type: ignore[type-arg]
    out = {zone.name: 0.0 for zone in zones}
    for bpm_bucket, seconds in buckets.items():
        for zone in zones:
            if zone.low_bpm <= bpm_bucket < zone.high_bpm or (
                zone is zones[-1] and bpm_bucket >= zone.high_bpm
            ):
                out[zone.name] += seconds
                break
    return out


class HrZoneDistributionPercentMaxVariant:
    metric_id = "hr_zone_distribution"
    variant_id = "percent_max"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None:
            return MetricResult(
                value=None, unit="seconds", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = percent_max_zones(hr_max)
        return MetricResult(
            value=_zone_seconds(buckets, zones), unit="seconds",
            confidence="high" if buckets else "low",
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )


class HrZoneDistributionKarvonenVariant:
    metric_id = "hr_zone_distribution"
    variant_id = "karvonen"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None or setting.resting_hr_override is None:
            return MetricResult(
                value=None, unit="seconds", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = karvonen_zones(float(hr_max), float(setting.resting_hr_override))
        return MetricResult(
            value=_zone_seconds(buckets, zones), unit="seconds",
            confidence="high" if buckets else "low",
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/training_load_variant.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.training_load import training_load
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series

_LOOKBACK_DAYS = 90


class TrainingLoadVariant:
    metric_id = "training_load"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        series = await edwards_daily_load_series(
            session, user_id=user_id, end_day=as_of, days=_LOOKBACK_DAYS
        )
        coverage = sum(1 for v in series.values() if v > 0)
        if not series:
            return MetricResult(
                value=None, unit="ctl_atl_tsb", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=_LOOKBACK_DAYS, as_of=as_of.isoformat(),
            )
        states = training_load(series)
        today_state = states[-1]
        confidence = "high" if coverage >= 28 else "medium" if coverage >= 7 else "low"
        return MetricResult(
            value={"ctl": today_state.ctl, "atl": today_state.atl, "tsb": today_state.tsb},
            unit="ctl_atl_tsb", confidence=confidence,
            coverage_days=coverage, coverage_required_days=_LOOKBACK_DAYS, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/acwr_variant.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.acwr import acwr
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series


class AcwrVariant:
    metric_id = "acwr"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        series = await edwards_daily_load_series(session, user_id=user_id, end_day=as_of, days=28)
        result = acwr(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="ratio", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={"ratio": result.ratio}, unit="ratio", confidence="high",
            coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/monotony_strain_variant.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.monotony_strain import monotony_strain
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series


class MonotonyStrainVariant:
    metric_id = "monotony_strain"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        series = await edwards_daily_load_series(session, user_id=user_id, end_day=as_of, days=7)
        result = monotony_strain(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="monotony_strain", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={"monotony": result.monotony, "strain": result.strain},
            unit="monotony_strain", confidence="high",
            coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/hrv_baseline_variant.py
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.hrv_baseline import hrv_baseline
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import wellness_daily_stat_range


class HrvBaselineVariant:
    metric_id = "hrv_baseline"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        start = as_of - timedelta(days=59)
        stats = await wellness_daily_stat_range(
            session, user_id=user_id, metric_code="hrv_5min", start=start, end=as_of
        )
        series = {day: stat.avg for day, stat in stats.items()}
        result = hrv_baseline(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="ms", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=20, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={
                "today": result.today, "baseline_mean": result.baseline_mean,
                "baseline_low": result.baseline_low, "baseline_high": result.baseline_high,
            },
            unit="ms", confidence="high",
            coverage_days=len(series), coverage_required_days=20, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/sleep_debt_variant.py
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.sleep_debt import sleep_debt
from kairos.metrics.types import MetricResult
from kairos.repositories.user_setting import get_or_default_user_setting


class SleepDebtVariant:
    metric_id = "sleep_debt"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        start = as_of - timedelta(days=6)
        rows = (
            await session.execute(
                text(
                    "SELECT start_at::date, duration_seconds FROM sleep_session "
                    "WHERE user_id = :uid AND start_at::date >= :start AND start_at::date <= :end "
                    "AND duration_seconds IS NOT NULL"
                ),
                {"uid": str(user_id), "start": start, "end": as_of},
            )
        ).all()
        nightly = {day: seconds / 3600.0 for day, seconds in rows}

        value = sleep_debt(nightly, as_of=as_of, target_hours=setting.sleep_target_hours)
        if value is None:
            return MetricResult(
                value=None, unit="hours", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        confidence = "high" if len(nightly) >= 5 else "medium" if len(nightly) >= 3 else "low"
        return MetricResult(
            value=value, unit="hours", confidence=confidence,
            coverage_days=len(nightly), coverage_required_days=7, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/variants/resting_hr_trend_variant.py
from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.resting_hr_trend import resting_hr_trend
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import wellness_daily_stat_range


class RestingHrTrendVariant:
    metric_id = "resting_hr_trend"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        start = as_of - timedelta(days=36)
        stats = await wellness_daily_stat_range(
            session, user_id=user_id, metric_code="hr", start=start, end=as_of
        )
        series = {day: stat.min for day, stat in stats.items()}  # daily min HR as resting-HR proxy
        result = resting_hr_trend(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="bpm", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=19, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={
                "recent_avg": result.recent_avg, "prior_avg": result.prior_avg,
                "delta_bpm": result.delta_bpm,
            },
            unit="bpm", confidence="high",
            coverage_days=len(series), coverage_required_days=19, as_of=as_of.isoformat(),
        )
```

```python
# src/kairos/metrics/bootstrap.py
from __future__ import annotations

from kairos.metrics.registry import MetricRegistry
from kairos.metrics.variants.acwr_variant import AcwrVariant
from kairos.metrics.variants.banister_trimp_variant import BanisterTrimpVariant
from kairos.metrics.variants.edwards_trimp_variant import EdwardsTrimpVariant
from kairos.metrics.variants.hr_zone_distribution_variant import (
    HrZoneDistributionKarvonenVariant,
    HrZoneDistributionPercentMaxVariant,
)
from kairos.metrics.variants.hrv_baseline_variant import HrvBaselineVariant
from kairos.metrics.variants.monotony_strain_variant import MonotonyStrainVariant
from kairos.metrics.variants.resting_hr_trend_variant import RestingHrTrendVariant
from kairos.metrics.variants.sleep_debt_variant import SleepDebtVariant
from kairos.metrics.variants.training_load_variant import TrainingLoadVariant


def build_default_registry() -> MetricRegistry:
    registry = MetricRegistry()
    registry.register(EdwardsTrimpVariant())
    registry.register(BanisterTrimpVariant())
    registry.register(HrZoneDistributionPercentMaxVariant())
    registry.register(HrZoneDistributionKarvonenVariant())
    registry.register(TrainingLoadVariant())
    registry.register(AcwrVariant())
    registry.register(MonotonyStrainVariant())
    registry.register(HrvBaselineVariant())
    registry.register(SleepDebtVariant())
    registry.register(RestingHrTrendVariant())
    return registry
```

- [ ] **Step 4: Run test to verify it passes (requires Docker)**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_variants_integration.py -v`
Expected: PASS

- [ ] **Step 5: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/metrics/ tests/test_metrics_variants_integration.py && .venv/Scripts/python -m mypy --strict src/kairos/metrics/`
Expected: clean

- [ ] **Step 6: Commit**

```bash
git add src/kairos/metrics/variants/ src/kairos/metrics/bootstrap.py tests/test_metrics_variants_integration.py
git commit -m "feat(phase-2): wire all metric formulas into the default registry"
```

---

### Task 15: `/api/metrics` router

**Files:**
- Create: `src/kairos/routers/metrics.py`
- Modify: `src/kairos/api.py`
- Test: `tests/test_metrics_router.py`

**Interfaces:**
- Consumes: `build_default_registry()` from Task 14, `current_user` from `kairos.auth.deps`
- Produces: `GET /api/metrics` (list of `metric_id`s), `GET /api/metrics/{metric_id}/variants` (list of `variant_id`s), `GET /api/metrics/{metric_id}?variant=...&as_of=YYYY-MM-DD` (defaults: first registered variant, today)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_router.py
from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

import kairos.auth.session as _sess
from kairos.api import app
from kairos.metrics.registry import MetricRegistry
from kairos.metrics.types import MetricResult
from kairos.routers import metrics as metrics_router_module


class _StubVariant:
    metric_id = "trimp"
    variant_id = "edwards"

    async def compute(self, session: object, *, user_id: UUID, as_of: date) -> MetricResult:
        del session, user_id
        return MetricResult(
            value=42.0, unit="trimp_pt", confidence="high",
            coverage_days=1, coverage_required_days=1, as_of=as_of.isoformat(),
        )


@pytest.fixture(autouse=True)
def _stub_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant())
    monkeypatch.setattr(metrics_router_module, "_registry", registry)


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_get_session(session_id: str) -> dict[str, str] | None:
        if session_id == "valid":
            return {"user_id": str(uuid4())}
        return None

    monkeypatch.setattr(_sess, "get_session", _fake_get_session)


@pytest.mark.asyncio
async def test_get_metric_returns_computed_value() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics/trimp", params={"variant": "edwards", "as_of": "2026-08-01"},
            cookies={"session_id": "valid"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["value"] == 42.0
    assert body["confidence"] == "high"


@pytest.mark.asyncio
async def test_get_metric_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/metrics/trimp")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_metric_unknown_variant_returns_404() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/metrics/trimp", params={"variant": "nonexistent"},
            cookies={"session_id": "valid"},
        )

    assert resp.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_router.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'kairos.routers.metrics'`

- [ ] **Step 3: Implement**

```python
# src/kairos/routers/metrics.py
from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.metrics.bootstrap import build_default_registry
from kairos.metrics.registry import MetricRegistry

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

_registry: MetricRegistry = build_default_registry()


@router.get("")
async def list_metrics(user: dict = Depends(current_user)) -> dict:
    del user
    return {"metric_ids": _registry.metric_ids()}


@router.get("/{metric_id}/variants")
async def list_variants(metric_id: str, user: dict = Depends(current_user)) -> dict:
    del user
    variants = _registry.variants_for(metric_id)
    if not variants:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric_id}")
    return {"variants": variants}


@router.get("/{metric_id}")
async def get_metric(
    metric_id: str,
    variant: str | None = None,
    as_of: date | None = None,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    variants = _registry.variants_for(metric_id)
    if not variants:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric_id}")
    chosen_variant = variant or variants[0]
    if chosen_variant not in variants:
        raise HTTPException(status_code=404, detail=f"Unknown variant: {chosen_variant}")

    result = await _registry.get(metric_id, chosen_variant).compute(
        session, user_id=user_id, as_of=as_of or date.today()
    )
    return {
        "metric_id": metric_id,
        "variant": chosen_variant,
        "value": result.value,
        "unit": result.unit,
        "confidence": result.confidence,
        "coverage_days": result.coverage_days,
        "coverage_required_days": result.coverage_required_days,
        "as_of": result.as_of,
    }
```

- [ ] **Step 4: Register the router**

```python
# src/kairos/api.py — add import and include_router call
from kairos.routers.metrics import router as metrics_router
# ...
app.include_router(metrics_router)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_metrics_router.py -v`
Expected: PASS

- [ ] **Step 6: Lint and type-check**

Run: `.venv/Scripts/python -m ruff check src/kairos/routers/metrics.py src/kairos/api.py tests/test_metrics_router.py && .venv/Scripts/python -m mypy --strict src/kairos/routers/metrics.py`
Expected: clean

- [ ] **Step 7: Run full suite to check for regressions**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all previously-passing tests still pass, plus every new test from this plan

- [ ] **Step 8: Commit**

```bash
git add src/kairos/routers/metrics.py src/kairos/api.py tests/test_metrics_router.py
git commit -m "feat(phase-2): /api/metrics router exposing the metric registry"
```

---

## Self-Review

**Spec coverage** — every `08-roadmap.md` Phase-2 "Metrics-Layer" bullet has a task: TRIMP (Tasks 6–7, 14), CTL/ATL/TSB (Task 8), HR-Zonen (Tasks 5, 14), ACWR (Task 9), HRV-Baseline (Task 11), Schlafschuld (Task 12), Ruhepuls-Trend (Task 13), plus the `01-architektur.md`-only Foster-Monotonie/-Strain (Task 10). `coverage`/`confidence` per Kennzahl is enforced structurally via `MetricResult` (Task 4) and populated by every variant (Task 14). The "Modul-Registry" roadmap bullet's server-side half is the `/api/metrics` router (Task 15); the frontend-facing generic components are out of scope for this plan per the agreed plan split.

**Placeholder scan** — no `TBD`/`later`/`similar to Task N` found; every formula step contains the real calculation and every test asserts a concrete expected value.

**Type consistency** — checked `MetricResult`, `MetricVariant`, `HrZoneBounds`, `WellnessDayStat`, `UserSettingData`, `LoadState`, `AcwrResult` field names across every task that constructs or consumes them; consistent throughout.

---

**Plan complete and saved to `docs/superpowers/plans/2026-08-10-phase-2-metrics-backend.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
