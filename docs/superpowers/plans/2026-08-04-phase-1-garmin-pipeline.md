# Phase 1 — Garmin Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Für 4 Garmin-Nutzer eine funktionierende, testbare Ingestion-Pipeline bereitstellen (Auth, Fetch, Raw-Store, Normalisierung, Sync-State, Backfill bis 15 Monate).

**Architecture:** In-process Connectoren unter `src/kairos/connectors/` mit einheitlichem Contract. Ein `SyncService` orchestriert Fetch/Normalize/Persist und schreibt deterministisch in `raw_payload`, Canonical-Tabellen und `sync_state`. Phase 1 liefert zunächst einen robusten Vertical Slice mit Stub/Fake-Connector + Tests, danach den realen Garmin-Connector mit MFA-Pfad.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, pytest, httpx, garth, fitdecode

---

## File Structure

- Create: `src/kairos/connectors/__init__.py`
- Create: `src/kairos/connectors/types.py`
- Create: `src/kairos/connectors/base.py`
- Create: `src/kairos/connectors/registry.py`
- Create: `src/kairos/connectors/garmin/__init__.py`
- Create: `src/kairos/connectors/garmin/client.py`
- Create: `src/kairos/connectors/garmin/normalize.py`
- Create: `src/kairos/ingestion/__init__.py`
- Create: `src/kairos/ingestion/hash.py`
- Create: `src/kairos/ingestion/service.py`
- Create: `src/kairos/repositories/raw_payload.py`
- Create: `src/kairos/repositories/sync_state.py`
- Modify: `src/kairos/db/models.py`
- Create: `alembic/versions/<rev>_phase1_garmin_tables.py`
- Create: `tests/test_connector_contract.py`
- Create: `tests/test_sync_service.py`
- Create: `tests/test_garmin_auth_flow.py`
- Create: `tests/test_raw_payload_dedupe.py`

---

### Task 1: Connector Contract + Registry + SyncService Skeleton

**Files:**
- Create: `src/kairos/connectors/types.py`
- Create: `src/kairos/connectors/base.py`
- Create: `src/kairos/connectors/registry.py`
- Create: `src/kairos/ingestion/hash.py`
- Create: `src/kairos/ingestion/service.py`
- Create: `tests/test_connector_contract.py`
- Create: `tests/test_sync_service.py`

- [x] Step 1: Write failing tests for connector registration, dispatch by connector_id, and sync flow contract (`fetch -> hash -> normalize -> persist`).
- [x] Step 2: Run tests to verify they fail.
- [x] Step 3: Implement connector Protocol + payload/canonical dataclasses.
- [x] Step 4: Implement connector registry (register/get/list) with duplicate guard.
- [x] Step 5: Implement deterministic hash utility for raw payloads.
- [x] Step 6: Implement `SyncService.run_window(...)` with dependency-injected repository interfaces.
- [x] Step 7: Re-run tests.
- [ ] Step 8: Commit.

### Task 2: DB Schema for Phase 1 Canonical + Failure Tracking

**Files:**
- Modify: `src/kairos/db/models.py`
- Create: `alembic/versions/<rev>_phase1_garmin_tables.py`
- Create: `tests/test_raw_payload_dedupe.py`

- [x] Step 1: Add failing tests for raw payload dedupe uniqueness and sync failure persistence.
- [x] Step 2: Extend ORM models with `sync_failure`, `metric_def`, `data_source`, `wellness_sample`, `sleep_session`, `activity`, `activity_record`, `daily_summary`.
- [x] Step 3: Generate migration and add RLS + FORCE RLS for all tenant tables.
- [x] Step 4: Run migration + tests.
- [ ] Step 5: Commit.

### Task 3: Garmin Auth Client with Dynamic MFA Handling

**Files:**
- Create: `src/kairos/connectors/garmin/client.py`
- Create: `tests/test_garmin_auth_flow.py`

- [x] Step 1: Write failing tests for login without MFA, login requiring MFA, and token refresh path.
- [x] Step 2: Implement `GarminClient.login(...)` with MFA callback support.
- [x] Step 3: Add typed exception mapping (`NeedsMfaToken`, `InvalidCredentials`, `UpstreamUnavailable`).
- [x] Step 4: Re-run tests.
- [ ] Step 5: Commit.

### Task 4: Garmin Normalizer + Vertical Slice Ingestion

**Files:**
- Create: `src/kairos/connectors/garmin/normalize.py`
- Modify: `src/kairos/ingestion/service.py`
- Create: `src/kairos/repositories/raw_payload.py`
- Create: `src/kairos/repositories/sync_state.py`

- [x] Step 1: Start with one metric slice (`hr_intraday`) and one daily slice (`sleep`) from stubbed Garmin JSON fixtures.
- [x] Step 2: Implement normalizer functions into canonical records.
- [x] Step 3: Wire repositories to persist raw + canonical + sync watermark.
- [x] Step 4: Add integration test with local Postgres container.
- [ ] Step 5: Commit.

### Task 5: Backfill Job (15 Months) + Progress State

**Files:**
- Modify: `src/kairos/ingestion/service.py`
- Modify: `src/kairos/db/models.py`
- Create: `tests/test_backfill_cursor.py`

- [x] Step 1: Write failing tests for cursor decrement, stop/resume, and completion marker.
- [x] Step 2: Implement `run_backfill(user_id, from_date, to_date)` with `backfill_cursor` and `backfill_complete_to` updates.
- [x] Step 3: Add conservative rate limit hook (dependency-injected sleep/throttle callable for testability).
- [x] Step 4: Re-run tests.
- [ ] Step 5: Commit.

### Task 6: Phase 1 Acceptance Checks

- [x] Step 1: `uv run pytest -v` passes.
- [x] Step 2: `uv run ruff check src tests` passes.
- [x] Step 3: `uv run mypy src` passes.
- [ ] Step 4: Manual dry-run sync for one Garmin user stores raw payload + watermark.
- [ ] Step 5: Tag `v0.1.0-phase1-skeleton`.

---

## Mac → Linux Notes

- Dev on macOS: Postgres/Redis via `deploy/docker-compose.dev.yml`; app runs local (`make dev`).
- Linux deployment keeps identical DB schemas and env vars; only `REDIRECT_URI` and `DOMAIN` differ.
- Keep connector logic free of macOS-specific APIs; all Garmin interaction is pure Python + HTTP.
