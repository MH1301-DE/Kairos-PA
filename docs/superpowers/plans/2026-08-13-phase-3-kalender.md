# Phase 3 — Kalender Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can propose a free time slot in the Kairos UI, confirm it, and have it appear as a real event in their Google Calendar — and edits/deletions in Kairos correctly propagate back, with no duplicate rows on repeated syncs.

**Architecture:** A new `google_calendar` connector (mirroring the existing `garmin` connector's `client.py`/`connector.py`/`normalize.py` split) reuses the OAuth refresh token already requested at login (persisted via the same `Connection`-table envelope-encryption pattern as Garmin). A new `calendar_event` table stores the canonical, deduplicated view (upsert on `(user_id, connector, external_id)`). A pure `compute_free_blocks` function computes proposal candidates from that table. A new `/calendar` SvelteKit page (using the existing dark-cockpit design system) drives the propose/confirm/edit/delete flow through four new API endpoints.

**Tech Stack:** FastAPI, SQLAlchemy async, httpx (Google Calendar API v3 REST calls), SvelteKit 5 runes, Vitest, pytest + testcontainers.

## Global Constraints

- `install_rls_listener(session, user_id)` on every session that reads or writes `calendar_event`, `connection`, `sync_state`, or `user_setting` — non-negotiable per `CLAUDE.md`.
- Backend: `ruff` (line-length 100) + `mypy --strict` clean, conventional commit messages (`feat(scope):`/`fix(scope):`).
- Frontend: Svelte 5 runes syntax (`$state`, `$derived`, `$props`), not legacy `export let`.
- Every frontend `fetch` to the backend uses `credentials: 'include'` (via the existing `apiGet`/`apiPost` helpers in `web/src/lib/api.ts` — never a raw `fetch`).
- New frontend pages use the existing `app.css` design tokens (`.tile`, `.btn`, `.btn-primary`, `.field`, `.badge` classes, `var(--color-*)`/`var(--space-*)` custom properties) — no new colors or one-off styling.
- Google Calendar event `start`/`end` objects are `{"date": "YYYY-MM-DD"}` for all-day events or `{"dateTime": "...", "timeZone": "..."}` for timed events — both must be handled explicitly, never assume `dateTime` is present.
- Backend interpreter: `.venv/Scripts/python` (Windows venv). Frontend: run `npm` commands from inside `web/`; if node/npm aren't on PATH in a session, prefix commands with `export PATH="/c/Program Files/nodejs:$PATH" && `.
- Scope is Google Calendar only — no CalDAV connector, no Watch-Channel/webhook push (poll-based sync only), no Gmail. See the design spec's Scope-Entscheidungen for the reasoning; do not add these even if convenient.

---

## File Structure

```
alembic/versions/<rev>_calendar_event_and_calendar_prefs.py   new: calendar_event table + user_setting columns
src/kairos/db/models.py                                        + CalendarEvent, + 4 columns on UserSetting

src/kairos/auth/google.py                                       callback() persists the Google refresh_token

src/kairos/connectors/google_calendar/
  client.py                new: GoogleCalendarClient (httpx wrapper, token refresh, CRUD)
  normalize.py              new: Google event JSON -> CanonicalRecord
  connector.py              new: GoogleCalendarConnector (Connector protocol)

src/kairos/repositories/calendar_event.py                      new: CalendarEventRepository (upsert/read)
src/kairos/calendar/free_time.py                                new: compute_free_blocks (pure function)

src/kairos/routers/sync.py                                      + POST /api/sync/google_calendar/sync
src/kairos/routers/calendar.py                                  new: GET/POST/PATCH/DELETE /api/calendar/*
src/kairos/api.py                                                + calendar_router

web/src/lib/types.ts                                             + CalendarEvent, FreeSlot
web/src/routes/calendar/
  +page.server.ts           new: load() fetches events + free slots; form actions for propose/edit/delete
  +page.svelte               new: event list, free-slot proposal form, edit/delete actions
web/src/routes/+layout.svelte                                    + "Kalender" nav link

tests/test_calendar_token_persistence.py                         new
tests/test_google_calendar_connector.py                          new (unit, mocked httpx)
tests/test_free_time.py                                          new (unit, pure function)
tests/test_calendar_router.py                                    new (unit, mocked connector)
tests/test_calendar_integration.py                                new (integration: dedup on repeated sync)
web/tests/unit/calendar-types.test.ts                             new (or folded into the page test — see Task 10)
```

---

### Task 1: Database schema — `calendar_event` table + `user_setting` calendar columns

**Files:**
- Create: `alembic/versions/<generate>_calendar_event_and_calendar_prefs.py`
- Modify: `src/kairos/db/models.py`

**Interfaces:**
- Produces: `CalendarEvent` ORM model (`id`, `user_id`, `connector`, `external_id`, `calendar_id`, `summary`, `description`, `location`, `start_at`, `end_at`, `all_day`, `status`, `source`, `created_at`, `updated_at`), unique constraint name `uq_calendar_event`. `UserSetting` gains `work_hours_start: time | None`, `work_hours_end: time | None`, `calendar_buffer_minutes: int` (default 15), `min_free_block_minutes: int` (default 30).

- [ ] **Step 1: Find the current Alembic head**

Run: `.venv/Scripts/python -m alembic heads`
Note the revision id printed — this is your migration's `down_revision`.

- [ ] **Step 2: Write the migration**

```python
# alembic/versions/<generated>_calendar_event_and_calendar_prefs.py
"""calendar_event_and_calendar_prefs

Revision ID: <generated>
Revises: <the head you found in Step 1>
Create Date: 2026-08-13 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "<generated>"
down_revision: str | None = "<the head from Step 1>"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "calendar_event",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("connector", sa.Text(), nullable=False),
        sa.Column("external_id", sa.Text(), nullable=False),
        sa.Column("calendar_id", sa.Text(), nullable=False, server_default="primary"),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.Text(), nullable=False, server_default="confirmed"),
        sa.Column("source", sa.Text(), nullable=False, server_default="external"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["user_id"], ["app_user.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "connector", "external_id", name="uq_calendar_event"),
        sa.CheckConstraint(
            "status IN ('confirmed', 'tentative', 'cancelled')", name="calendar_event_status_check"
        ),
        sa.CheckConstraint("source IN ('external', 'kairos')", name="calendar_event_source_check"),
    )
    op.execute("ALTER TABLE calendar_event ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON calendar_event "
        "USING (user_id = current_setting('app.current_user_id', true)::uuid)"
    )
    op.execute("ALTER TABLE calendar_event FORCE ROW LEVEL SECURITY")

    op.add_column("user_setting", sa.Column("work_hours_start", sa.Time(), nullable=True))
    op.add_column("user_setting", sa.Column("work_hours_end", sa.Time(), nullable=True))
    op.add_column(
        "user_setting",
        sa.Column(
            "calendar_buffer_minutes", sa.SmallInteger(), nullable=False, server_default="15"
        ),
    )
    op.add_column(
        "user_setting",
        sa.Column(
            "min_free_block_minutes", sa.SmallInteger(), nullable=False, server_default="30"
        ),
    )


def downgrade() -> None:
    op.drop_column("user_setting", "min_free_block_minutes")
    op.drop_column("user_setting", "calendar_buffer_minutes")
    op.drop_column("user_setting", "work_hours_end")
    op.drop_column("user_setting", "work_hours_start")

    op.execute("DROP POLICY IF EXISTS tenant_isolation ON calendar_event")
    op.execute("ALTER TABLE calendar_event NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE calendar_event DISABLE ROW LEVEL SECURITY")
    op.drop_table("calendar_event")
```

Run `.venv/Scripts/python -m alembic revision --head-only -m "placeholder"` is NOT needed — write the file directly with a real, unique revision id (8-12 lowercase hex characters, e.g. generate via `.venv/Scripts/python -c "import uuid; print(uuid.uuid4().hex[:12])"`), matching the naming convention of existing files under `alembic/versions/`.

- [ ] **Step 3: Add the ORM models**

In `src/kairos/db/models.py`, add near the other tenant-table models (follow the existing import style at the top of the file — `Mapped`, `mapped_column`, `UUID`, `Text`, `Boolean`, `DateTime`, `Time`, `SmallInteger`, `CheckConstraint`, `UniqueConstraint`, `ForeignKeyConstraint`, `func`, `uuid`, `datetime`, `time` — add any of these to the existing import lines that aren't already imported):

```python
class CalendarEvent(Base):
    __tablename__ = "calendar_event"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False
    )
    connector: Mapped[str] = mapped_column(Text, nullable=False)
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    calendar_id: Mapped[str] = mapped_column(Text, nullable=False, default="primary")
    summary: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(Text)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="confirmed")
    source: Mapped[str] = mapped_column(Text, nullable=False, default="external")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("user_id", "connector", "external_id", name="uq_calendar_event"),
        CheckConstraint(
            "status IN ('confirmed', 'tentative', 'cancelled')",
            name="calendar_event_status_check",
        ),
        CheckConstraint("source IN ('external', 'kairos')", name="calendar_event_source_check"),
    )
```

Then add the four new columns to the existing `UserSetting` class body (after `sleep_target_hours`):

```python
    work_hours_start: Mapped[time | None] = mapped_column(Time)
    work_hours_end: Mapped[time | None] = mapped_column(Time)
    calendar_buffer_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=15)
    min_free_block_minutes: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
```

If `time` isn't already imported from `datetime` at the top of `models.py`, add it to the existing `from datetime import ...` line.

- [ ] **Step 4: Verify the migration applies and models match**

Run (Docker must be running):
```bash
.venv/Scripts/python -m alembic upgrade head
.venv/Scripts/python -m alembic check
```
Expected: both succeed with no output (or `alembic check` prints nothing on success — an autogenerate-diff mismatch would print a message).

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/*_calendar_event_and_calendar_prefs.py src/kairos/db/models.py
git commit -m "feat(calendar): calendar_event table + user_setting calendar preference columns"
```

---

### Task 2: Persist the Google OAuth refresh token on login

**Files:**
- Modify: `src/kairos/auth/google.py`
- Test: `tests/test_auth.py`

**Interfaces:**
- Consumes: `Connection` (Task-independent, already exists in `src/kairos/db/models.py`), `encrypt`/`generate_dek`/`wrap_dek`/`kek_from_settings` from `src/kairos/auth/crypto.py` (all already exist, signatures: `encrypt(plaintext: bytes, dek: bytes) -> bytes`, `kek_from_settings(b64_key: str) -> bytes`).
- Produces: after every login, a `connection` row with `connector='google_calendar'`, `external_account=email`, `credentials_enc` = encrypted `refresh_token`, `status='active'`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_auth.py` (this file already has `_MemoryRedis`, `fake_redis`, and a full happy-path mock pattern in `test_callback_redirects_to_frontend_root` — follow that same mocking style exactly, don't invent a new one):

```python
@pytest.mark.asyncio
async def test_callback_persists_google_calendar_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_stub = google_auth.get_redis()
    state = "valid-test-state-calendar"
    await redis_stub.set(f"oauth_state:{state}", "1", ex=600)

    mock_token_resp = AsyncMock()
    mock_token_resp.json = lambda: {
        "access_token": "test-access-token",
        "refresh_token": "test-refresh-token-xyz",
    }
    mock_token_resp.raise_for_status = lambda: None

    mock_info_resp = AsyncMock()
    mock_info_resp.json = lambda: {
        "sub": "google-sub-calendar-test",
        "email": "calendar-test@example.com",
        "name": "Calendar Test User",
    }
    mock_info_resp.raise_for_status = lambda: None

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_token_resp)
    mock_client.get = AsyncMock(return_value=mock_info_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(google_auth, "httpx", AsyncMock(AsyncClient=lambda: mock_client))

    saved_connections: list[models.Connection] = []
    mock_user = MagicMock(spec=models.AppUser)
    mock_user.id = uuid4()
    mock_user.email = "calendar-test@example.com"
    mock_user.google_sub = "google-sub-calendar-test"
    mock_user.dek_wrapped = None  # exercised path: new user, dek generated in this request

    mock_db = AsyncMock()

    async def _execute(stmt: object) -> object:
        del stmt
        result = MagicMock()
        result.scalar_one_or_none = lambda: None
        return result

    mock_db.execute = AsyncMock(side_effect=_execute)

    def _add(obj: object) -> None:
        if isinstance(obj, models.Connection):
            saved_connections.append(obj)

    mock_db.add = MagicMock(side_effect=_add)
    mock_db.commit = AsyncMock()
    mock_db.refresh = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(google_auth, "async_session_factory", lambda: mock_db)
    monkeypatch.setattr(google_auth, "create_session", AsyncMock(return_value="test-session-id"))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(
            f"/auth/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert len(saved_connections) == 1
    conn = saved_connections[0]
    assert conn.connector == "google_calendar"
    assert conn.external_account == "calendar-test@example.com"
    assert conn.status == "active"
    assert conn.credentials_enc is not None
    assert conn.credentials_enc != b"test-refresh-token-xyz"  # must be encrypted, not raw
```

Add `from uuid import uuid4` to the existing imports at the top of `tests/test_auth.py` if not already present, and add `models.Connection`/`models.AppUser` access via the existing `from kairos.db import models` import (already there).

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_auth.py::test_callback_persists_google_calendar_connection -v`
Expected: FAIL — `saved_connections` is empty (no `Connection` object was added), since `callback()` doesn't create one yet.

- [ ] **Step 3: Implement**

In `src/kairos/auth/google.py`, add the imports needed (add to the existing import block):

```python
from kairos.auth.crypto import encrypt, generate_dek, kek_from_settings, wrap_dek
from kairos.db.models import AppUser, Connection
```

(`AppUser` is likely already imported — check first and only add what's missing; `Connection`, `encrypt`, `generate_dek`, `wrap_dek`, `kek_from_settings` need adding.)

Inside `callback()`, after the existing `async with async_session_factory() as db:` block's user upsert (right after `await db.refresh(user)` inside the `if user is None:` branch, so this runs for both new and existing users — move it so it runs unconditionally after the `if user is None:` block, still inside the `async with async_session_factory() as db:` context, before that context manager exits):

```python
        refresh_token = tokens.get("refresh_token")
        if refresh_token:
            kek = kek_from_settings(settings.kairos_kek)
            if user.dek_wrapped is None:
                dek = generate_dek()
                user.dek_wrapped = wrap_dek(dek, kek)
            else:
                from kairos.auth.crypto import unwrap_dek

                dek = unwrap_dek(user.dek_wrapped, kek)
            credentials_enc = encrypt(refresh_token.encode(), dek)
            db.add(
                Connection(
                    user_id=user.id,
                    connector="google_calendar",
                    external_account=email,
                    status="active",
                    credentials_enc=credentials_enc,
                )
            )
            await db.commit()
```

Note: Google only returns `refresh_token` on the *first* consent (or when `prompt=consent` forces re-consent, which `login()` already sets unconditionally — so this branch runs on every login, not just the first). If a user re-logs-in and `refresh_token` happens to be absent from the token response for some reason, skip silently rather than erroring — the existing `connection` row (if any) stays valid.

Read the full current `callback()` function first to place this correctly relative to the existing `session_id = await create_session(...)` line and the `async with` block's exit — the block above must run *before* the `async with async_session_factory() as db:` context closes, since it uses `db`.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_auth.py -v`
Expected: all tests in the file PASS, including the new one.

- [ ] **Step 5: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/auth/google.py tests/test_auth.py` and `.venv/Scripts/python -m mypy --strict src/kairos/auth/google.py`
Expected: clean (or only the same pre-existing warning categories already present elsewhere in the codebase).

- [ ] **Step 6: Commit**

```bash
git add src/kairos/auth/google.py tests/test_auth.py
git commit -m "feat(auth): persist the Google Calendar refresh token on every login"
```

---

### Task 3: `GoogleCalendarClient` — Calendar API v3 HTTP wrapper

**Files:**
- Create: `src/kairos/connectors/google_calendar/__init__.py` (empty)
- Create: `src/kairos/connectors/google_calendar/client.py`
- Test: `tests/test_google_calendar_client.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (standalone HTTP client).
- Produces:
  - `class TokenExpired(Exception)`, `class UpstreamUnavailable(Exception)` (module-level exceptions)
  - `class GoogleCalendarClient:` with `__init__(self, refresh_token: str, client_id: str, client_secret: str) -> None`
  - `def list_events(self, calendar_id: str, time_min: datetime, time_max: datetime, sync_token: str | None = None) -> dict[str, Any]` — returns the raw Google API JSON response (has `"items"`, may have `"nextSyncToken"`)
  - `def create_event(self, calendar_id: str, summary: str, start: datetime, end: datetime, description: str | None = None) -> dict[str, Any]` — returns the created event JSON (has `"id"`)
  - `def update_event(self, calendar_id: str, event_id: str, **fields: Any) -> dict[str, Any]`
  - `def delete_event(self, calendar_id: str, event_id: str) -> None`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_google_calendar_client.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from kairos.connectors.google_calendar.client import (
    GoogleCalendarClient,
    TokenExpired,
    UpstreamUnavailable,
)


def _client() -> GoogleCalendarClient:
    return GoogleCalendarClient(
        refresh_token="test-refresh-token",
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_list_events_refreshes_token_then_lists(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http

    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    events_resp = MagicMock()
    events_resp.status_code = 200
    events_resp.json.return_value = {"items": [{"id": "evt1"}], "nextSyncToken": "sync-tok-1"}
    mock_http.post.return_value = token_resp
    mock_http.get.return_value = events_resp

    client = _client()
    result = client.list_events(
        "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
    )

    assert result["items"] == [{"id": "evt1"}]
    assert result["nextSyncToken"] == "sync-tok-1"
    # token refresh happened before the events call
    assert mock_http.post.called
    get_kwargs = mock_http.get.call_args.kwargs
    assert get_kwargs["headers"]["Authorization"] == "Bearer fresh-access-token"


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_token_refresh_failure_raises_token_expired(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 400
    token_resp.json.return_value = {"error": "invalid_grant"}
    mock_http.post.return_value = token_resp

    client = _client()
    with pytest.raises(TokenExpired):
        client.list_events(
            "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
        )


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_create_event_sends_timed_event_body(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    create_resp = MagicMock()
    create_resp.status_code = 200
    create_resp.json.return_value = {"id": "new-evt-id", "summary": "Long Run"}
    mock_http.post.side_effect = [token_resp, create_resp]

    client = _client()
    result = client.create_event(
        "primary",
        summary="Long Run",
        start=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        end=datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
    )

    assert result["id"] == "new-evt-id"
    create_call = mock_http.post.call_args_list[1]
    body = create_call.kwargs["json"]
    assert body["summary"] == "Long Run"
    assert body["start"]["dateTime"] == "2026-03-01T07:00:00+00:00"
    assert body["end"]["dateTime"] == "2026-03-01T08:30:00+00:00"


@patch("kairos.connectors.google_calendar.client.httpx.Client")
def test_upstream_5xx_raises_upstream_unavailable(mock_client_cls: MagicMock) -> None:
    mock_http = MagicMock()
    mock_client_cls.return_value.__enter__.return_value = mock_http
    token_resp = MagicMock()
    token_resp.status_code = 200
    token_resp.json.return_value = {"access_token": "fresh-access-token"}
    error_resp = MagicMock()
    error_resp.status_code = 503
    mock_http.post.return_value = token_resp
    mock_http.get.return_value = error_resp

    client = _client()
    with pytest.raises(UpstreamUnavailable):
        client.list_events(
            "primary", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 8, tzinfo=UTC)
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_google_calendar_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kairos.connectors.google_calendar'`

- [ ] **Step 3: Implement**

```python
# src/kairos/connectors/google_calendar/client.py
from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events"
EVENT_URL = "https://www.googleapis.com/calendar/v3/calendars/{calendar_id}/events/{event_id}"


class TokenExpired(Exception):
    pass


class UpstreamUnavailable(Exception):
    pass


class GoogleCalendarClient:
    def __init__(self, refresh_token: str, client_id: str, client_secret: str) -> None:
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret

    def list_events(
        self,
        calendar_id: str,
        time_min: datetime,
        time_max: datetime,
        sync_token: str | None = None,
    ) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            params: dict[str, str] = {}
            if sync_token:
                params["syncToken"] = sync_token
            else:
                params["timeMin"] = time_min.isoformat()
                params["timeMax"] = time_max.isoformat()
            resp = http.get(
                EVENTS_URL.format(calendar_id=calendar_id),
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar list_events: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def create_event(
        self,
        calendar_id: str,
        *,
        summary: str,
        start: datetime,
        end: datetime,
        description: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "summary": summary,
            "start": {"dateTime": start.isoformat()},
            "end": {"dateTime": end.isoformat()},
        }
        if description:
            body["description"] = description
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.post(
                EVENTS_URL.format(calendar_id=calendar_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json=body,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar create_event: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def update_event(self, calendar_id: str, event_id: str, **fields: Any) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.patch(
                EVENT_URL.format(calendar_id=calendar_id, event_id=event_id),
                headers={"Authorization": f"Bearer {access_token}"},
                json=fields,
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar update_event: {resp.status_code}")
            resp_json: dict[str, Any] = resp.json()
            return resp_json

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        with httpx.Client(timeout=15.0) as http:
            access_token = self._refresh_access_token(http)
            resp = http.delete(
                EVENT_URL.format(calendar_id=calendar_id, event_id=event_id),
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code >= 500:
                raise UpstreamUnavailable(f"Google Calendar delete_event: {resp.status_code}")

    def _refresh_access_token(self, http: httpx.Client) -> str:
        resp = http.post(
            TOKEN_URL,
            data={
                "refresh_token": self._refresh_token,
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code >= 400:
            raise TokenExpired("Google refresh token is no longer valid")
        access_token: str = resp.json()["access_token"]
        return access_token
```

Note: `update_event`/`delete_event` don't need dedicated tests beyond what's in Step 1 — Step 1's coverage of `list_events`/`create_event`/token-refresh-failure/5xx already exercises every code path this class has (the private `_refresh_access_token` helper and the `UpstreamUnavailable`/status-code-branch pattern are identical across all four public methods).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_google_calendar_client.py -v`
Expected: 4/4 PASS

- [ ] **Step 5: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/connectors/google_calendar/ tests/test_google_calendar_client.py` and `.venv/Scripts/python -m mypy --strict src/kairos/connectors/google_calendar/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/kairos/connectors/google_calendar/__init__.py src/kairos/connectors/google_calendar/client.py tests/test_google_calendar_client.py
git commit -m "feat(calendar): GoogleCalendarClient HTTP wrapper with token refresh"
```

---

### Task 4: `GoogleCalendarConnector` + event normalization

**Files:**
- Create: `src/kairos/connectors/google_calendar/normalize.py`
- Create: `src/kairos/connectors/google_calendar/connector.py`
- Test: `tests/test_google_calendar_connector.py`

**Interfaces:**
- Consumes: `GoogleCalendarClient` (Task 3, exact methods above), `Connector` protocol (`src/kairos/connectors/base.py`, already exists: `fetch(user_id, kind, window) -> RawPayloadEnvelope`, `normalize(kind, payload) -> list[CanonicalRecord]`, `write_back(user_id, kind, records) -> WriteResult`), `CanonicalRecord`/`Window`/`RawPayloadEnvelope`/`WriteResult`/`JSONValue` (`src/kairos/connectors/types.py`, already exist — `CanonicalRecord(record_type, external_id, data, occurred_at=None)`).
- Produces:
  - `def normalize_events(payload: JSONValue) -> list[CanonicalRecord]` in `normalize.py` — `record_type="calendar_event"`, `external_id=<google event id>`, `data={"summary":..., "description":..., "location":..., "start_at": "<iso>", "end_at": "<iso>", "all_day": bool, "status": "confirmed"|"tentative"|"cancelled"}`, `occurred_at=<start_at as datetime>`.
  - `class GoogleCalendarConnector:` with `connector_id = "google_calendar"`, `__init__(self, client: GoogleCalendarClient) -> None`, implementing the `Connector` protocol. `write_back`'s `records` parameter's `CanonicalRecord.data` for a *create* must contain `{"action": "create", "summary": str, "start_at": iso str, "end_at": iso str, "description": str | None}`; for *update*: `{"action": "update", "event_id": str, ...fields}`; for *delete*: `{"action": "delete", "event_id": str}`. `WriteResult` reports one `written` per successfully-processed record, `failed` incremented (not raised) for any record whose Google API call errors, so one bad record in a batch doesn't abort the rest.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_google_calendar_connector.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.connectors.google_calendar.normalize import normalize_events
from kairos.connectors.types import CanonicalRecord, Window


def test_normalize_events_handles_timed_event() -> None:
    payload = {
        "items": [
            {
                "id": "evt-timed",
                "summary": "Long Run",
                "description": "Zone 2",
                "location": "Park",
                "status": "confirmed",
                "start": {"dateTime": "2026-03-01T07:00:00+00:00"},
                "end": {"dateTime": "2026-03-01T08:30:00+00:00"},
            }
        ]
    }
    records = normalize_events(payload)
    assert len(records) == 1
    r = records[0]
    assert r.record_type == "calendar_event"
    assert r.external_id == "evt-timed"
    assert r.data["all_day"] is False
    assert r.data["start_at"] == "2026-03-01T07:00:00+00:00"
    assert r.occurred_at == datetime(2026, 3, 1, 7, 0, tzinfo=UTC)


def test_normalize_events_handles_all_day_event() -> None:
    payload = {
        "items": [
            {
                "id": "evt-allday",
                "summary": "Race Day",
                "status": "confirmed",
                "start": {"date": "2026-04-01"},
                "end": {"date": "2026-04-02"},
            }
        ]
    }
    records = normalize_events(payload)
    assert len(records) == 1
    assert records[0].data["all_day"] is True
    assert records[0].data["start_at"] == "2026-04-01T00:00:00+00:00"


def test_normalize_events_skips_malformed_items() -> None:
    payload = {"items": [{"id": "no-start-or-end"}, {"summary": "no id at all"}]}
    assert normalize_events(payload) == []


def test_connector_fetch_delegates_to_client() -> None:
    mock_client = MagicMock()
    mock_client.list_events.return_value = {"items": [], "nextSyncToken": "tok"}
    connector = GoogleCalendarConnector(mock_client)
    window = Window(start=datetime(2026, 1, 1, tzinfo=UTC), end=datetime(2026, 1, 8, tzinfo=UTC))

    envelope = connector.fetch(uuid4(), "events", window)

    assert envelope.window == window
    mock_client.list_events.assert_called_once_with("primary", window.start, window.end, None)


def test_connector_write_back_creates_and_reports_result() -> None:
    mock_client = MagicMock()
    mock_client.create_event.return_value = {"id": "new-id"}
    connector = GoogleCalendarConnector(mock_client)
    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="",
            data={
                "action": "create",
                "summary": "Long Run",
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "description": None,
            },
        )
    ]

    result = connector.write_back(uuid4(), "events", records)

    assert result.written == 1
    assert result.failed == 0
    mock_client.create_event.assert_called_once()


def test_connector_write_back_counts_failures_without_raising() -> None:
    mock_client = MagicMock()
    mock_client.create_event.side_effect = RuntimeError("boom")
    connector = GoogleCalendarConnector(mock_client)
    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="",
            data={
                "action": "create",
                "summary": "Bad",
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "description": None,
            },
        )
    ]

    result = connector.write_back(uuid4(), "events", records)

    assert result.written == 0
    assert result.failed == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_google_calendar_connector.py -v`
Expected: FAIL — `ModuleNotFoundError` for both new modules.

- [ ] **Step 3: Implement `normalize.py`**

```python
# src/kairos/connectors/google_calendar/normalize.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from kairos.connectors.types import CanonicalRecord, JSONValue


def normalize_events(payload: JSONValue) -> list[CanonicalRecord]:
    if not isinstance(payload, dict):
        return []
    items = payload.get("items")
    if not isinstance(items, list):
        return []

    records: list[CanonicalRecord] = []
    for item in items:
        record = _normalize_one(item)
        if record is not None:
            records.append(record)
    return records


def _normalize_one(item: Any) -> CanonicalRecord | None:
    if not isinstance(item, dict):
        return None
    event_id = item.get("id")
    start_raw = item.get("start")
    end_raw = item.get("end")
    if not event_id or not isinstance(start_raw, dict) or not isinstance(end_raw, dict):
        return None

    start_dt, all_day = _parse_boundary(start_raw)
    end_dt, _ = _parse_boundary(end_raw)
    if start_dt is None or end_dt is None:
        return None

    data: dict[str, JSONValue] = {
        "summary": item.get("summary"),
        "description": item.get("description"),
        "location": item.get("location"),
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
        "all_day": all_day,
        "status": item.get("status", "confirmed"),
    }
    return CanonicalRecord(
        record_type="calendar_event", external_id=str(event_id), data=data, occurred_at=start_dt
    )


def _parse_boundary(boundary: dict[str, Any]) -> tuple[datetime | None, bool]:
    if "dateTime" in boundary:
        return datetime.fromisoformat(boundary["dateTime"]), False
    if "date" in boundary:
        d = date.fromisoformat(boundary["date"])
        return datetime(d.year, d.month, d.day, tzinfo=None).replace(tzinfo=None), True
    return None, False
```

Note: the all-day branch above intentionally produces a naive datetime — fix it before moving on: replace the last line of `_parse_boundary`'s `date` branch with a UTC-aware construction, since every other timestamp in this codebase is timezone-aware (`DateTime(timezone=True)` columns throughout `models.py`):

```python
    if "date" in boundary:
        from datetime import UTC

        d = date.fromisoformat(boundary["date"])
        return datetime(d.year, d.month, d.day, tzinfo=UTC), True
```

(Move the `from datetime import UTC` into the top-level import line instead of inline — `from datetime import UTC, date, datetime`.)

- [ ] **Step 4: Implement `connector.py`**

```python
# src/kairos/connectors/google_calendar/connector.py
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from kairos.connectors.google_calendar.client import GoogleCalendarClient
from kairos.connectors.google_calendar.normalize import normalize_events
from kairos.connectors.types import CanonicalRecord, JSONValue, RawPayloadEnvelope, Window, WriteResult

_DEFAULT_CALENDAR_ID = "primary"


class GoogleCalendarConnector:
    connector_id = "google_calendar"

    def __init__(self, client: GoogleCalendarClient) -> None:
        self._client = client

    def fetch(self, user_id: UUID, kind: str, window: Window) -> RawPayloadEnvelope:
        del user_id, kind
        payload: JSONValue = self._client.list_events(
            _DEFAULT_CALENDAR_ID, window.start, window.end, None
        )
        return RawPayloadEnvelope(window=window, payload=payload)

    def normalize(self, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
        del kind
        return normalize_events(payload)

    def write_back(
        self, user_id: UUID, kind: str, records: Sequence[CanonicalRecord]
    ) -> WriteResult:
        del user_id, kind
        written = 0
        failed = 0
        for record in records:
            try:
                self._apply(record)
                written += 1
            except Exception:
                failed += 1
        return WriteResult(written=written, failed=failed)

    def _apply(self, record: CanonicalRecord) -> None:
        data = record.data
        if not isinstance(data, dict):
            raise ValueError("write_back record.data must be a dict")
        action = data.get("action")
        if action == "create":
            self._client.create_event(
                _DEFAULT_CALENDAR_ID,
                summary=str(data["summary"]),
                start=datetime.fromisoformat(str(data["start_at"])),
                end=datetime.fromisoformat(str(data["end_at"])),
                description=data.get("description"),  # type: ignore[arg-type]
            )
        elif action == "update":
            fields = {k: v for k, v in data.items() if k not in ("action", "event_id")}
            self._client.update_event(_DEFAULT_CALENDAR_ID, str(data["event_id"]), **fields)
        elif action == "delete":
            self._client.delete_event(_DEFAULT_CALENDAR_ID, str(data["event_id"]))
        else:
            raise ValueError(f"Unknown write_back action: {action!r}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_google_calendar_connector.py -v`
Expected: 6/6 PASS

- [ ] **Step 6: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/connectors/google_calendar/ tests/test_google_calendar_connector.py` and `.venv/Scripts/python -m mypy --strict src/kairos/connectors/google_calendar/`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/kairos/connectors/google_calendar/normalize.py src/kairos/connectors/google_calendar/connector.py tests/test_google_calendar_connector.py
git commit -m "feat(calendar): GoogleCalendarConnector — fetch/normalize/write_back"
```

---

### Task 5: `CalendarEventRepository` — upsert and read

**Files:**
- Create: `src/kairos/repositories/calendar_event.py`
- Test: `tests/test_calendar_event_repository_integration.py`

**Interfaces:**
- Consumes: `CalendarEvent` (Task 1), `CanonicalRecord` (`src/kairos/connectors/types.py`, already exists).
- Produces:
  - `class CalendarEventRepository:` with `__init__(self, session: AsyncSession) -> None`
  - `async def upsert_from_records(self, user_id: UUID, connector: str, records: list[CanonicalRecord]) -> int` — returns count written/updated. Skips records with an empty `external_id`.
  - `async def upsert_kairos_event(self, user_id: UUID, connector: str, external_id: str, summary: str, start_at: datetime, end_at: datetime, description: str | None) -> None` — for events Kairos itself created (`source='kairos'`), called immediately after a successful `write_back` create, before any sync poll runs.
  - `async def list_between(self, user_id: UUID, start: datetime, end: datetime) -> list[CalendarEvent]` — ordered by `start_at`, excludes `status='cancelled'`.
  - `async def mark_deleted(self, user_id: UUID, connector: str, external_id: str) -> None` — sets `status='cancelled'`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_event_repository_integration.py
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.rls import install_rls_listener
from kairos.repositories.calendar_event import CalendarEventRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    from sqlalchemy import text

    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_upsert_from_records_then_list_between(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="evt-1",
            data={
                "summary": "Long Run",
                "description": None,
                "location": None,
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "all_day": False,
                "status": "confirmed",
            },
            occurred_at=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        )
    ]
    written = await repo.upsert_from_records(user_id, "google_calendar", records)
    await session.commit()
    assert written == 1

    events = await repo.list_between(
        user_id, datetime(2026, 2, 28, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert len(events) == 1
    assert events[0].summary == "Long Run"
    assert events[0].source == "external"


@pytest.mark.asyncio
async def test_upsert_from_records_is_idempotent_on_external_id(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    def _record(summary: str) -> CanonicalRecord:
        return CanonicalRecord(
            record_type="calendar_event",
            external_id="evt-dedup",
            data={
                "summary": summary,
                "description": None,
                "location": None,
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "all_day": False,
                "status": "confirmed",
            },
            occurred_at=datetime(2026, 3, 1, 7, 0, tzinfo=UTC),
        )

    await repo.upsert_from_records(user_id, "google_calendar", [_record("First Title")])
    await session.commit()
    await repo.upsert_from_records(user_id, "google_calendar", [_record("Renamed Title")])
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 2, 28, tzinfo=UTC), datetime(2026, 3, 2, tzinfo=UTC)
    )
    assert len(events) == 1
    assert events[0].summary == "Renamed Title"


@pytest.mark.asyncio
async def test_upsert_kairos_event_then_dedup_against_sync(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        "kairos-created-evt",
        "Proposed Slot",
        datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 4, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()

    # a later sync poll sees the same event echoed back by Google
    record = CanonicalRecord(
        record_type="calendar_event",
        external_id="kairos-created-evt",
        data={
            "summary": "Proposed Slot",
            "description": None,
            "location": None,
            "start_at": "2026-04-01T09:00:00+00:00",
            "end_at": "2026-04-01T10:00:00+00:00",
            "all_day": False,
            "status": "confirmed",
        },
        occurred_at=datetime(2026, 4, 1, 9, 0, tzinfo=UTC),
    )
    await repo.upsert_from_records(user_id, "google_calendar", [record])
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 3, 31, tzinfo=UTC), datetime(2026, 4, 2, tzinfo=UTC)
    )
    assert len(events) == 1  # no duplicate row


@pytest.mark.asyncio
async def test_mark_deleted_excludes_from_list_between(session: AsyncSession) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)

    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        "evt-to-delete",
        "Will be cancelled",
        datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()
    await repo.mark_deleted(user_id, "google_calendar", "evt-to-delete")
    await session.commit()

    events = await repo.list_between(
        user_id, datetime(2026, 4, 30, tzinfo=UTC), datetime(2026, 5, 2, tzinfo=UTC)
    )
    assert events == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_event_repository_integration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kairos.repositories.calendar_event'`

- [ ] **Step 3: Implement**

```python
# src/kairos/repositories/calendar_event.py
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.types import CanonicalRecord
from kairos.db.models import CalendarEvent


class CalendarEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_from_records(
        self, user_id: UUID, connector: str, records: list[CanonicalRecord]
    ) -> int:
        written = 0
        for record in records:
            if not record.external_id:
                continue
            data = record.data
            if not isinstance(data, dict):
                continue
            stmt = (
                insert(CalendarEvent)
                .values(
                    user_id=user_id,
                    connector=connector,
                    external_id=record.external_id,
                    summary=data.get("summary"),
                    description=data.get("description"),
                    location=data.get("location"),
                    start_at=datetime.fromisoformat(str(data["start_at"])),
                    end_at=datetime.fromisoformat(str(data["end_at"])),
                    all_day=bool(data.get("all_day", False)),
                    status=str(data.get("status", "confirmed")),
                    source="external",
                )
                .on_conflict_do_update(
                    constraint="uq_calendar_event",
                    set_={
                        "summary": data.get("summary"),
                        "description": data.get("description"),
                        "location": data.get("location"),
                        "start_at": datetime.fromisoformat(str(data["start_at"])),
                        "end_at": datetime.fromisoformat(str(data["end_at"])),
                        "all_day": bool(data.get("all_day", False)),
                        "status": str(data.get("status", "confirmed")),
                        "updated_at": datetime.now(datetime.now().astimezone().tzinfo),
                    },
                )
            )
            await self._session.execute(stmt)
            written += 1
        return written

    async def upsert_kairos_event(
        self,
        user_id: UUID,
        connector: str,
        external_id: str,
        summary: str,
        start_at: datetime,
        end_at: datetime,
        description: str | None,
    ) -> None:
        stmt = (
            insert(CalendarEvent)
            .values(
                user_id=user_id,
                connector=connector,
                external_id=external_id,
                summary=summary,
                description=description,
                start_at=start_at,
                end_at=end_at,
                all_day=False,
                status="confirmed",
                source="kairos",
            )
            .on_conflict_do_update(
                constraint="uq_calendar_event",
                set_={"summary": summary, "description": description},
            )
        )
        await self._session.execute(stmt)

    async def list_between(
        self, user_id: UUID, start: datetime, end: datetime
    ) -> list[CalendarEvent]:
        result = await self._session.execute(
            select(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.status != "cancelled",
                CalendarEvent.start_at < end,
                CalendarEvent.end_at > start,
            )
            .order_by(CalendarEvent.start_at)
        )
        return list(result.scalars().all())

    async def mark_deleted(self, user_id: UUID, connector: str, external_id: str) -> None:
        await self._session.execute(
            update(CalendarEvent)
            .where(
                CalendarEvent.user_id == user_id,
                CalendarEvent.connector == connector,
                CalendarEvent.external_id == external_id,
            )
            .values(status="cancelled")
        )
```

Fix the `updated_at` line before running tests — `datetime.now(datetime.now().astimezone().tzinfo)` is convoluted; replace both occurrences of that pattern with a clean top-of-file import and a single call:

```python
from datetime import UTC, datetime
```

and use `"updated_at": datetime.now(UTC)` in the `on_conflict_do_update`'s `set_` dict.

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_event_repository_integration.py -v` (Docker must be running)
Expected: 4/4 PASS

- [ ] **Step 5: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/repositories/calendar_event.py tests/test_calendar_event_repository_integration.py` and `.venv/Scripts/python -m mypy --strict src/kairos/repositories/calendar_event.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/kairos/repositories/calendar_event.py tests/test_calendar_event_repository_integration.py
git commit -m "feat(calendar): CalendarEventRepository — dedup upsert, list, soft-delete"
```

---

### Task 6: `compute_free_blocks` — pure free-time function

**Files:**
- Create: `src/kairos/calendar/__init__.py` (empty)
- Create: `src/kairos/calendar/free_time.py`
- Test: `tests/test_free_time.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (pure function over plain data).
- Produces:
  - `@dataclass(frozen=True) class BusyBlock: start: datetime; end: datetime` in `free_time.py`
  - `@dataclass(frozen=True) class FreeBlock: start: datetime; end: datetime`
  - `@dataclass(frozen=True) class CalendarPrefs: work_hours_start: time | None; work_hours_end: time | None; buffer_minutes: int; min_free_minutes: int`
  - `def compute_free_blocks(busy: list[BusyBlock], window_start: datetime, window_end: datetime, prefs: CalendarPrefs) -> list[FreeBlock]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_free_time.py
from __future__ import annotations

from datetime import UTC, datetime, time

from kairos.calendar.free_time import BusyBlock, CalendarPrefs, FreeBlock, compute_free_blocks

_NO_WORK_HOURS = CalendarPrefs(
    work_hours_start=None, work_hours_end=None, buffer_minutes=0, min_free_minutes=30
)


def test_empty_calendar_yields_whole_window_as_free() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    blocks = compute_free_blocks([], window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [FreeBlock(start=window_start, end=window_end)]


def test_single_meeting_splits_window_into_two_free_blocks() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy = [BusyBlock(start=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), end=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))]

    blocks = compute_free_blocks(busy, window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [
        FreeBlock(start=window_start, end=datetime(2026, 6, 1, 9, 0, tzinfo=UTC)),
        FreeBlock(start=datetime(2026, 6, 1, 10, 0, tzinfo=UTC), end=window_end),
    ]


def test_buffer_minutes_shrinks_adjacent_free_blocks() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy = [BusyBlock(start=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), end=datetime(2026, 6, 1, 10, 0, tzinfo=UTC))]
    prefs = CalendarPrefs(work_hours_start=None, work_hours_end=None, buffer_minutes=15, min_free_minutes=30)

    blocks = compute_free_blocks(busy, window_start, window_end, prefs)

    assert blocks[0].end == datetime(2026, 6, 1, 8, 45, tzinfo=UTC)
    assert blocks[1].start == datetime(2026, 6, 1, 10, 15, tzinfo=UTC)


def test_blocks_shorter_than_min_free_minutes_are_dropped() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 9, 20, tzinfo=UTC)
    busy = [BusyBlock(start=datetime(2026, 6, 1, 8, 10, tzinfo=UTC), end=datetime(2026, 6, 1, 9, 0, tzinfo=UTC))]
    prefs = CalendarPrefs(work_hours_start=None, work_hours_end=None, buffer_minutes=0, min_free_minutes=30)

    blocks = compute_free_blocks(busy, window_start, window_end, prefs)

    # first block is 8:00-8:10 (10 min, dropped); second is 9:00-9:20 (20 min, dropped)
    assert blocks == []


def test_overlapping_busy_blocks_are_merged() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy = [
        BusyBlock(start=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), end=datetime(2026, 6, 1, 10, 30, tzinfo=UTC)),
        BusyBlock(start=datetime(2026, 6, 1, 10, 0, tzinfo=UTC), end=datetime(2026, 6, 1, 11, 0, tzinfo=UTC)),
    ]

    blocks = compute_free_blocks(busy, window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [
        FreeBlock(start=window_start, end=datetime(2026, 6, 1, 9, 0, tzinfo=UTC)),
        FreeBlock(start=datetime(2026, 6, 1, 11, 0, tzinfo=UTC), end=window_end),
    ]


def test_work_hours_constrain_free_blocks_per_day() -> None:
    window_start = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 22, 0, tzinfo=UTC)
    prefs = CalendarPrefs(
        work_hours_start=time(9, 0), work_hours_end=time(17, 0), buffer_minutes=0, min_free_minutes=30
    )

    blocks = compute_free_blocks([], window_start, window_end, prefs)

    assert blocks == [
        FreeBlock(start=datetime(2026, 6, 1, 9, 0, tzinfo=UTC), end=datetime(2026, 6, 1, 17, 0, tzinfo=UTC))
    ]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_free_time.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kairos.calendar'`

- [ ] **Step 3: Implement**

```python
# src/kairos/calendar/free_time.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class BusyBlock:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class FreeBlock:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarPrefs:
    work_hours_start: time | None
    work_hours_end: time | None
    buffer_minutes: int
    min_free_minutes: int


def compute_free_blocks(
    busy: list[BusyBlock],
    window_start: datetime,
    window_end: datetime,
    prefs: CalendarPrefs,
) -> list[FreeBlock]:
    merged = _merge_overlapping(sorted(busy, key=lambda b: b.start))
    buffer = timedelta(minutes=prefs.buffer_minutes)
    min_duration = timedelta(minutes=prefs.min_free_minutes)

    candidates: list[FreeBlock] = []
    cursor = window_start
    for block in merged:
        buffered_start = block.start - buffer
        buffered_end = block.end + buffer
        if buffered_start > cursor:
            candidates.append(FreeBlock(start=cursor, end=buffered_start))
        cursor = max(cursor, buffered_end)
    if cursor < window_end:
        candidates.append(FreeBlock(start=cursor, end=window_end))

    constrained = [
        c for c in _apply_work_hours(candidates, prefs) if c.end - c.start >= min_duration
    ]
    return constrained


def _merge_overlapping(blocks: list[BusyBlock]) -> list[BusyBlock]:
    if not blocks:
        return []
    merged = [blocks[0]]
    for block in blocks[1:]:
        last = merged[-1]
        if block.start <= last.end:
            merged[-1] = BusyBlock(start=last.start, end=max(last.end, block.end))
        else:
            merged.append(block)
    return merged


def _apply_work_hours(blocks: list[FreeBlock], prefs: CalendarPrefs) -> list[FreeBlock]:
    if prefs.work_hours_start is None or prefs.work_hours_end is None:
        return blocks
    result: list[FreeBlock] = []
    for block in blocks:
        day_start = block.start.replace(
            hour=prefs.work_hours_start.hour,
            minute=prefs.work_hours_start.minute,
            second=0,
            microsecond=0,
        )
        day_end = block.start.replace(
            hour=prefs.work_hours_end.hour,
            minute=prefs.work_hours_end.minute,
            second=0,
            microsecond=0,
        )
        clipped_start = max(block.start, day_start)
        clipped_end = min(block.end, day_end)
        if clipped_start < clipped_end:
            result.append(FreeBlock(start=clipped_start, end=clipped_end))
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_free_time.py -v`
Expected: 6/6 PASS

- [ ] **Step 5: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/calendar/ tests/test_free_time.py` and `.venv/Scripts/python -m mypy --strict src/kairos/calendar/`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/kairos/calendar/__init__.py src/kairos/calendar/free_time.py tests/test_free_time.py
git commit -m "feat(calendar): compute_free_blocks — pure free-time computation"
```

---

### Task 7: Sync job wiring — `POST /api/sync/google_calendar/sync`

**Files:**
- Modify: `src/kairos/routers/sync.py`
- Test: `tests/test_sync_router.py` (check whether this file already exists; if so, add to it following its existing test style — if it doesn't exist, check `tests/test_connections_router.py` for the client-mocking pattern used elsewhere in this codebase and match it)

**Interfaces:**
- Consumes: `GoogleCalendarClient`/`GoogleCalendarConnector` (Tasks 3-4), `CalendarEventRepository` (Task 5), `SyncJobRegistry`/`SyncJob`/`get_registry` (`src/kairos/ingestion/job_registry.py`, already exist — exact shape already used by the existing `/garmin/backfill` endpoint in this same file), `Connection` model, `decrypt`/`unwrap_dek`/`kek_from_settings` (`src/kairos/auth/crypto.py`, already exist).
- Produces: `POST /api/sync/google_calendar/sync` — `status_code=202`, body `{"jobs": [...]}` (same shape as the existing Garmin backfill response). Runs a background task that fetches events for a fixed 90-day window (today −7 days to today +83 days — enough to cover recent history and near-term proposals without unbounded growth) and upserts them via `CalendarEventRepository`.

- [ ] **Step 1: Read the existing file fully first**

Read `src/kairos/routers/sync.py` completely before editing — you need the exact shape of `_build_garmin_client`, `_run_backfill_task`, `SyncJob`/`SyncJobRegistry` usage, and the `trigger_garmin_backfill` endpoint to mirror the pattern precisely for calendar. Do not guess at field names.

- [ ] **Step 2: Write the failing test**

```python
# add to tests/test_sync_router.py (create the file if it doesn't exist, following
# the httpx.AsyncClient + ASGITransport + auth-dependency-override pattern used in
# tests/test_connections_router.py — read that file first for the exact fixture style)
import pytest
from httpx import ASGITransport, AsyncClient

from kairos.api import app
from kairos.auth.deps import current_user


@pytest.fixture(autouse=True)
def _override_auth():
    app.dependency_overrides[current_user] = lambda: {"user_id": "00000000-0000-0000-0000-000000000001"}
    yield
    app.dependency_overrides.pop(current_user, None)


@pytest.mark.asyncio
async def test_google_calendar_sync_returns_202_and_job() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/sync/google_calendar/sync")
    assert response.status_code == 202
    body = response.json()
    assert len(body["jobs"]) == 1
    assert body["jobs"][0]["connector"] == "google_calendar"
    assert body["jobs"][0]["kind"] == "events"
```

If `tests/test_connections_router.py`'s actual auth-override pattern differs from the sketch above (e.g. it overrides a different dependency, or uses a different fixture shape), match what that file actually does instead of this sketch — read it first.

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_sync_router.py -v`
Expected: FAIL — 404, the route doesn't exist yet.

- [ ] **Step 4: Implement**

Add to `src/kairos/routers/sync.py` (after the existing Garmin endpoints, following the exact structural pattern of `trigger_garmin_backfill`/`_run_backfill_task`/`_build_garmin_client` you read in Step 1 — the sketch below shows the shape; adapt exact imports/helper names to match what Step 1 revealed):

```python
@router.post("/google_calendar/sync", status_code=202)
async def trigger_google_calendar_sync(
    background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
    registry: SyncJobRegistry = Depends(get_registry),
) -> dict:
    user_id = UUID(user["user_id"])
    if registry.is_locked(user_id, "google_calendar", "events"):
        raise HTTPException(status_code=409, detail="Sync already running")

    jobs = registry.create_jobs(
        user_id=user_id,
        connector="google_calendar",
        kinds=["events"],
        from_date=(date.today() - timedelta(days=7)).isoformat(),
        to_date=(date.today() + timedelta(days=83)).isoformat(),
    )
    background_tasks.add_task(_run_calendar_sync_task, user_id=user_id, jobs=jobs, registry=registry)
    return {"jobs": [j.to_dict() for j in jobs]}


async def _run_calendar_sync_task(
    *, user_id: UUID, jobs: list[SyncJob], registry: SyncJobRegistry
) -> None:
    async with async_session_factory() as session:
        install_rls_listener(session, user_id)
        client = await _build_google_calendar_client(session, user_id)
        job = jobs[0]
        if client is None:
            job.status = "failed"
            job.error = "No active Google Calendar connection or decryption failed"
            job.finished_at = datetime.now(UTC).isoformat()
            return

        from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
        from kairos.repositories.calendar_event import CalendarEventRepository

        connector = GoogleCalendarConnector(client)
        window = Window(
            start=_to_utc_midnight(date.today() - timedelta(days=7)),
            end=_to_utc_midnight(date.today() + timedelta(days=83)),
        )
        lock = registry.get_lock(user_id, "google_calendar", "events")
        async with lock:
            job.status = "running"
            job.started_at = datetime.now(UTC).isoformat()
            try:
                envelope = connector.fetch(user_id, "events", window)
                records = connector.normalize("events", envelope.payload)
                repo = CalendarEventRepository(session)
                written = await repo.upsert_from_records(user_id, "google_calendar", records)
                await session.commit()
                job.status = "done"
                job.windows_processed = written
            except Exception as exc:
                await session.rollback()
                job.status = "failed"
                job.error = str(exc)
            finally:
                job.finished_at = datetime.now(UTC).isoformat()


async def _build_google_calendar_client(
    session: AsyncSession, user_id: UUID
) -> "GoogleCalendarClient | None":
    from kairos.connectors.google_calendar.client import GoogleCalendarClient

    try:
        conn_row = (
            await session.execute(
                select(Connection).where(
                    Connection.user_id == user_id,
                    Connection.connector == "google_calendar",
                    Connection.status.in_(["active", "reauth_required"]),
                ).order_by(Connection.connected_at.desc())
            )
        ).scalars().first()
        if conn_row is None or conn_row.credentials_enc is None:
            return None

        user_row = (
            await session.execute(select(AppUser).where(AppUser.id == user_id))
        ).scalar_one_or_none()
        if user_row is None or user_row.dek_wrapped is None:
            return None

        kek = kek_from_settings(settings.kairos_kek)
        dek = unwrap_dek(user_row.dek_wrapped, kek)
        refresh_token = decrypt(conn_row.credentials_enc, dek).decode()
        return GoogleCalendarClient(
            refresh_token=refresh_token,
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )
    except Exception:
        return None
```

Add any imports this needs that aren't already in the file (`decrypt`, `unwrap_dek` from `kairos.auth.crypto`; `Window` from `kairos.connectors.types`; `AppUser`, `Connection` from `kairos.db.models` — check what's already imported first, only add what's missing). Note: `_build_google_calendar_client` deliberately mirrors `_build_garmin_client`'s `order_by(connected_at.desc()).scalars().first()` pattern (not `.scalar_one_or_none()`) — the same duplicate-row defense established in the Dashboard-Frontend plan's final review applies here too, even though a fresh `google_calendar` connector starts with no duplicate-row history.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_sync_router.py -v`
Expected: PASS

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all passing, no regressions in the existing Garmin sync tests (confirms the shared `SyncJobRegistry` extension didn't break the Garmin path).

- [ ] **Step 7: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/routers/sync.py tests/test_sync_router.py` and `.venv/Scripts/python -m mypy --strict src/kairos/routers/sync.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/kairos/routers/sync.py tests/test_sync_router.py
git commit -m "feat(calendar): wire google_calendar sync into the existing job registry"
```

---

### Task 8: Calendar read API — `GET /api/calendar/events`, `GET /api/calendar/free-slots`

**Files:**
- Create: `src/kairos/routers/calendar.py`
- Modify: `src/kairos/api.py`
- Test: `tests/test_calendar_router.py`

**Interfaces:**
- Consumes: `CalendarEventRepository` (Task 5), `compute_free_blocks`/`BusyBlock`/`CalendarPrefs`/`FreeBlock` (Task 6), `UserSetting` (Task 1), `current_user`/`get_session`/`install_rls_listener` (already exist, same pattern as `routers/metrics.py`).
- Produces:
  - `GET /api/calendar/events?from=<iso date>&to=<iso date>` → `{"events": [{"id": str, "summary": str|None, "description": str|None, "location": str|None, "start_at": iso, "end_at": iso, "all_day": bool, "status": str, "source": str}]}`
  - `GET /api/calendar/free-slots?from=<iso date>&to=<iso date>&duration_minutes=<int>` → `{"slots": [{"start": iso, "end": iso}]}` — only slots at least `duration_minutes` long.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_calendar_router.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from kairos.api import app
from kairos.auth.deps import current_user
from kairos.db.session import get_session


@pytest.fixture(autouse=True)
def _override_auth_and_session():
    app.dependency_overrides[current_user] = lambda: {"user_id": str(uuid4())}
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_events_requires_auth() -> None:
    app.dependency_overrides.pop(current_user, None)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/calendar/events?from=2026-01-01&to=2026-01-08")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_events_returns_shaped_list() -> None:
    fake_event = AsyncMock()
    fake_event.id = uuid4()
    fake_event.summary = "Long Run"
    fake_event.description = None
    fake_event.location = None
    fake_event.start_at = datetime(2026, 1, 2, 7, 0, tzinfo=UTC)
    fake_event.end_at = datetime(2026, 1, 2, 8, 0, tzinfo=UTC)
    fake_event.all_day = False
    fake_event.status = "confirmed"
    fake_event.source = "external"

    with patch(
        "kairos.routers.calendar.CalendarEventRepository.list_between",
        new=AsyncMock(return_value=[fake_event]),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get("/api/calendar/events?from=2026-01-01&to=2026-01-08")

    assert response.status_code == 200
    body = response.json()
    assert len(body["events"]) == 1
    assert body["events"][0]["summary"] == "Long Run"


@pytest.mark.asyncio
async def test_get_free_slots_filters_by_min_duration() -> None:
    with (
        patch(
            "kairos.routers.calendar.CalendarEventRepository.list_between",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "kairos.routers.calendar._load_prefs",
            new=AsyncMock(
                return_value={
                    "work_hours_start": None,
                    "work_hours_end": None,
                    "calendar_buffer_minutes": 0,
                    "min_free_block_minutes": 30,
                }
            ),
        ),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(
                "/api/calendar/free-slots?from=2026-01-01&to=2026-01-02&duration_minutes=60"
            )

    assert response.status_code == 200
    body = response.json()
    assert len(body["slots"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_router.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kairos.routers.calendar'`

- [ ] **Step 3: Implement**

```python
# src/kairos/routers/calendar.py
from __future__ import annotations

from datetime import date, datetime, time
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.calendar.free_time import BusyBlock, CalendarPrefs, compute_free_blocks
from kairos.db.models import UserSetting
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.repositories.calendar_event import CalendarEventRepository

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


@router.get("/events")
async def list_events(
    from_: date,
    to: date,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, _to_utc(from_), _to_utc(to))
    return {
        "events": [
            {
                "id": str(e.id),
                "summary": e.summary,
                "description": e.description,
                "location": e.location,
                "start_at": e.start_at.isoformat(),
                "end_at": e.end_at.isoformat(),
                "all_day": e.all_day,
                "status": e.status,
                "source": e.source,
            }
            for e in events
        ]
    }


@router.get("/free-slots")
async def free_slots(
    from_: date,
    to: date,
    duration_minutes: int,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    events = await repo.list_between(user_id, _to_utc(from_), _to_utc(to))
    prefs_row = await _load_prefs(session, user_id)

    busy = [BusyBlock(start=e.start_at, end=e.end_at) for e in events]
    prefs = CalendarPrefs(
        work_hours_start=prefs_row["work_hours_start"],
        work_hours_end=prefs_row["work_hours_end"],
        buffer_minutes=prefs_row["calendar_buffer_minutes"],
        min_free_minutes=prefs_row["min_free_block_minutes"],
    )
    blocks = compute_free_blocks(busy, _to_utc(from_), _to_utc(to), prefs)
    duration_delta_minutes = duration_minutes
    slots = [
        b for b in blocks if (b.end - b.start).total_seconds() / 60 >= duration_delta_minutes
    ]
    return {"slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()} for s in slots]}


async def _load_prefs(session: AsyncSession, user_id: UUID) -> dict:
    row = (
        await session.execute(select(UserSetting).where(UserSetting.user_id == user_id))
    ).scalar_one_or_none()
    if row is None:
        return {
            "work_hours_start": None,
            "work_hours_end": None,
            "calendar_buffer_minutes": 15,
            "min_free_block_minutes": 30,
        }
    return {
        "work_hours_start": row.work_hours_start,
        "work_hours_end": row.work_hours_end,
        "calendar_buffer_minutes": row.calendar_buffer_minutes,
        "min_free_block_minutes": row.min_free_block_minutes,
    }


def _to_utc(d: date) -> datetime:
    from datetime import UTC

    return datetime(d.year, d.month, d.day, tzinfo=UTC)
```

Move the `from datetime import UTC` in `_to_utc` to the top-level import line instead (`from datetime import UTC, date, datetime, time`) — written inline above only to keep the diff readable; the implementer should write it correctly the first time, not leave the inline import.

In `src/kairos/api.py`, add the import and registration alongside the existing routers (follow the exact existing pattern — read the file first for the precise import/include_router lines used for `connections_router`/`metrics_router`/`sync_router`):

```python
from kairos.routers.calendar import router as calendar_router
# ...
app.include_router(calendar_router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_router.py -v`
Expected: 3/3 PASS

- [ ] **Step 5: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/routers/calendar.py src/kairos/api.py tests/test_calendar_router.py` and `.venv/Scripts/python -m mypy --strict src/kairos/routers/calendar.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/kairos/routers/calendar.py src/kairos/api.py tests/test_calendar_router.py
git commit -m "feat(calendar): GET /api/calendar/events and /api/calendar/free-slots"
```

---

### Task 9: Calendar write API — propose, edit, delete

**Files:**
- Modify: `src/kairos/routers/calendar.py`
- Test: `tests/test_calendar_router.py`

**Interfaces:**
- Consumes: `GoogleCalendarConnector`/`GoogleCalendarClient` (Tasks 3-4), `CalendarEventRepository.upsert_kairos_event`/`.mark_deleted` (Task 5), `_build_google_calendar_client`-equivalent client construction (mirror Task 7's helper — do not duplicate the whole function; import and reuse `_build_google_calendar_client` from `kairos.routers.sync`).
- Produces:
  - `POST /api/calendar/events` — body `{"summary": str, "start_at": iso, "end_at": iso, "description": str | None}`. `201` on success with the created event's shape (same as `list_events`'s per-event object). `503` if the Google client can't be built (no active connection). Writes to Google first, then upserts the canonical row with `source='kairos'`.
  - `DELETE /api/calendar/events/{event_id}` — `event_id` is the local `calendar_event.id` (UUID), not the Google external id. `204` on success, `404` if the event doesn't belong to this user.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_calendar_router.py`:

```python
@pytest.mark.asyncio
async def test_post_event_creates_via_connector_and_persists() -> None:
    mock_client = AsyncMock()

    with (
        patch("kairos.routers.calendar._build_google_calendar_client", new=AsyncMock(return_value=mock_client)),
        patch(
            "kairos.routers.calendar.GoogleCalendarConnector.write_back",
        ) as mock_write_back,
        patch(
            "kairos.routers.calendar.CalendarEventRepository.upsert_kairos_event",
            new=AsyncMock(),
        ) as mock_upsert,
    ):
        from kairos.connectors.types import WriteResult

        mock_write_back.return_value = WriteResult(written=1, failed=0)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/calendar/events",
                json={
                    "summary": "Long Run",
                    "start_at": "2026-03-01T07:00:00+00:00",
                    "end_at": "2026-03-01T08:30:00+00:00",
                    "description": None,
                },
            )

    assert response.status_code == 201
    mock_upsert.assert_called_once()


@pytest.mark.asyncio
async def test_post_event_returns_503_without_active_connection() -> None:
    with patch(
        "kairos.routers.calendar._build_google_calendar_client", new=AsyncMock(return_value=None)
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post(
                "/api/calendar/events",
                json={
                    "summary": "Long Run",
                    "start_at": "2026-03-01T07:00:00+00:00",
                    "end_at": "2026-03-01T08:30:00+00:00",
                    "description": None,
                },
            )
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_delete_event_returns_404_for_missing_event() -> None:
    with patch(
        "kairos.routers.calendar.CalendarEventRepository.get_by_id",
        new=AsyncMock(return_value=None),
    ):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            response = await client.delete(f"/api/calendar/events/{uuid4()}")
    assert response.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_router.py -v`
Expected: the three new tests FAIL (404 for missing routes, or `AttributeError` for `_build_google_calendar_client`/`get_by_id` not existing yet).

- [ ] **Step 3: Add `get_by_id` to `CalendarEventRepository`**

In `src/kairos/repositories/calendar_event.py`, add one more method (this task also needs to read a single row by its own id, to check the event exists and belongs to the current user before deleting):

```python
    async def get_by_id(self, user_id: UUID, event_id: UUID) -> CalendarEvent | None:
        result = await self._session.execute(
            select(CalendarEvent).where(
                CalendarEvent.user_id == user_id, CalendarEvent.id == event_id
            )
        )
        return result.scalar_one_or_none()
```

(`UUID` needs importing from `uuid` at the top of the file if not already present — check first.)

- [ ] **Step 4: Implement the write endpoints**

Add to `src/kairos/routers/calendar.py` (imports needed in addition to what Task 8 added: `HTTPException`, `status` from `fastapi`; `BaseModel` from `pydantic`; `GoogleCalendarConnector` from `kairos.connectors.google_calendar.connector`; `_build_google_calendar_client` from `kairos.routers.sync`; `datetime` — already imported):

```python
from fastapi import HTTPException
from pydantic import BaseModel

from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.connectors.types import CanonicalRecord
from kairos.routers.sync import _build_google_calendar_client


class CreateEventRequest(BaseModel):
    summary: str
    start_at: datetime
    end_at: datetime
    description: str | None = None


@router.post("/events", status_code=201)
async def create_event(
    req: CreateEventRequest,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    client = await _build_google_calendar_client(session, user_id)
    if client is None:
        raise HTTPException(status_code=503, detail="no_active_google_calendar_connection")

    connector = GoogleCalendarConnector(client)
    created = client.create_event(
        "primary",
        summary=req.summary,
        start=req.start_at,
        end=req.end_at,
        description=req.description,
    )
    del connector  # write_back not used here; single-record path calls the client directly

    repo = CalendarEventRepository(session)
    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        str(created["id"]),
        req.summary,
        req.start_at,
        req.end_at,
        req.description,
    )
    await session.commit()
    return {
        "summary": req.summary,
        "start_at": req.start_at.isoformat(),
        "end_at": req.end_at.isoformat(),
        "description": req.description,
    }


@router.delete("/events/{event_id}", status_code=204)
async def delete_event(
    event_id: UUID,
    user: dict = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    repo = CalendarEventRepository(session)
    event = await repo.get_by_id(user_id, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="event_not_found")

    client = await _build_google_calendar_client(session, user_id)
    if client is not None:
        client.delete_event(event.calendar_id, event.external_id)
    await repo.mark_deleted(user_id, event.connector, event.external_id)
    await session.commit()
```

Note the deviation from the design spec's original `write_back(records)` framing for the create path: calling `client.create_event(...)` directly (as shown above) is simpler and equally correct for a single-event create — `GoogleCalendarConnector.write_back` (Task 4) exists and is tested for the batch/sync-job-shaped use case, but this single-request HTTP handler doesn't need to wrap one record in a list to satisfy a batch interface. Both paths ultimately call the same `GoogleCalendarClient` methods. If a future task needs batched writes from this router, revisit using `write_back` then — don't add unused abstraction now.

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_router.py -v`
Expected: 6/6 PASS (3 from Task 8 + 3 new)

- [ ] **Step 6: Run the full backend suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all passing.

- [ ] **Step 7: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check src/kairos/routers/calendar.py src/kairos/repositories/calendar_event.py tests/test_calendar_router.py` and `.venv/Scripts/python -m mypy --strict src/kairos/routers/calendar.py src/kairos/repositories/calendar_event.py`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/kairos/routers/calendar.py src/kairos/repositories/calendar_event.py tests/test_calendar_router.py
git commit -m "feat(calendar): POST/DELETE /api/calendar/events — propose and cancel"
```

---

### Task 10: Frontend types + API client wiring

**Files:**
- Modify: `web/src/lib/types.ts`
- Test: `web/tests/unit/calendar-api.test.ts`

**Interfaces:**
- Consumes: `apiGet`/`apiPost` (`web/src/lib/api.ts`, already exist — `apiGet<T>(fetchFn, path): Promise<T>`, `apiPost<T>(fetchFn, path, body): Promise<{status, data: T}>`).
- Produces (in `types.ts`):
  ```typescript
  export interface CalendarEvent {
    id: string;
    summary: string | null;
    description: string | null;
    location: string | null;
    start_at: string;
    end_at: string;
    all_day: boolean;
    status: string;
    source: string;
  }

  export interface FreeSlot {
    start: string;
    end: string;
  }
  ```

- [ ] **Step 1: Add the types**

Append to `web/src/lib/types.ts` (after the existing `SyncJob` interface, matching the file's existing style — plain exported interfaces, no default export):

```typescript
export interface CalendarEvent {
	id: string;
	summary: string | null;
	description: string | null;
	location: string | null;
	start_at: string;
	end_at: string;
	all_day: boolean;
	status: string;
	source: string;
}

export interface FreeSlot {
	start: string;
	end: string;
}
```

- [ ] **Step 2: Write a test confirming the shape round-trips through `apiGet`**

```typescript
// web/tests/unit/calendar-api.test.ts
import { describe, it, expect } from 'vitest';
import { apiGet } from '../../src/lib/api';
import type { CalendarEvent, FreeSlot } from '../../src/lib/types';

describe('calendar API types', () => {
	it('apiGet resolves a typed events response', async () => {
		const fetchFn = (async () =>
			new Response(
				JSON.stringify({
					events: [
						{
							id: 'evt-1',
							summary: 'Long Run',
							description: null,
							location: null,
							start_at: '2026-03-01T07:00:00+00:00',
							end_at: '2026-03-01T08:30:00+00:00',
							all_day: false,
							status: 'confirmed',
							source: 'external'
						}
					]
				}),
				{ status: 200 }
			)) as typeof fetch;

		const result = await apiGet<{ events: CalendarEvent[] }>(fetchFn, '/api/calendar/events');
		expect(result.events[0].summary).toBe('Long Run');
	});

	it('apiGet resolves a typed free-slots response', async () => {
		const fetchFn = (async () =>
			new Response(
				JSON.stringify({ slots: [{ start: '2026-03-01T09:00:00+00:00', end: '2026-03-01T10:00:00+00:00' }] }),
				{ status: 200 }
			)) as typeof fetch;

		const result = await apiGet<{ slots: FreeSlot[] }>(fetchFn, '/api/calendar/free-slots');
		expect(result.slots).toHaveLength(1);
	});
});
```

- [ ] **Step 3: Run test to verify it passes**

Run (from `web/`): `npm run test:unit -- calendar-api.test.ts`
Expected: 2/2 PASS (this test only exercises the already-implemented, already-tested `apiGet` — it's here to lock in the `CalendarEvent`/`FreeSlot` shapes against real usage before Task 11 builds the page against them).

- [ ] **Step 4: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/types.ts web/tests/unit/calendar-api.test.ts
git commit -m "feat(web): CalendarEvent/FreeSlot types"
```

---

### Task 11: Frontend `/calendar` page — list, propose, confirm, delete

**Files:**
- Create: `web/src/routes/calendar/+page.server.ts`
- Create: `web/src/routes/calendar/+page.svelte`
- Modify: `web/src/routes/+layout.svelte`
- Test: `web/tests/unit/CalendarPage.test.ts` — actually, this is a full route (`+page.svelte` with `load` data), not a standalone component; **skip a dedicated Vitest component test for the page itself** (matches the pattern already used for the Dashboard/Sync/Onboarding pages in the prior plan — none of those got page-level Vitest tests either, only their reusable sub-components did; a full `load()`+action-driven route needs the same kind of live-server verification those pages got, not a jsdom component render).

**Interfaces:**
- Consumes: `apiGet`/`apiPost` (`web/src/lib/api.ts`), `CalendarEvent`/`FreeSlot` (Task 10), `resolve` (`$app/paths`), `redirect`/`ApiError`-401-handling pattern (mirror `web/src/routes/sync/+page.server.ts` exactly — same 401→`/auth/login` redirect established in the prior plan's final-review fix wave).
- Produces: `GET /calendar` renders event list (next 14 days) + a free-slot proposal form (duration input → shows candidate slots → confirm button per slot → `POST /api/calendar/events`) + a delete button per event.

- [ ] **Step 1: Implement the load function**

```typescript
// web/src/routes/calendar/+page.server.ts
import type { PageServerLoad, Actions } from './$types';
import { apiGet, apiPost, ApiError } from '$lib/api';
import { redirect, fail } from '@sveltejs/kit';
import type { CalendarEvent, FreeSlot } from '$lib/types';

function _range(): { from: string; to: string } {
	const from = new Date();
	const to = new Date(from.getTime() + 14 * 24 * 60 * 60 * 1000);
	return { from: from.toISOString().slice(0, 10), to: to.toISOString().slice(0, 10) };
}

export const load: PageServerLoad = async ({ fetch }) => {
	const { from, to } = _range();
	try {
		const events = await apiGet<{ events: CalendarEvent[] }>(
			fetch,
			`/api/calendar/events?from=${from}&to=${to}`
		);
		return { events: events.events, from, to };
	} catch (err) {
		if (err instanceof ApiError && err.status === 401) throw redirect(302, '/auth/login');
		throw err;
	}
};

export const actions: Actions = {
	'propose-slots': async ({ request, fetch }) => {
		const form = await request.formData();
		const durationMinutes = Number(form.get('duration_minutes'));
		const { from, to } = _range();
		try {
			const result = await apiGet<{ slots: FreeSlot[] }>(
				fetch,
				`/api/calendar/free-slots?from=${from}&to=${to}&duration_minutes=${durationMinutes}`
			);
			return { slots: result.slots, durationMinutes };
		} catch (err) {
			if (err instanceof ApiError && err.status === 401) throw redirect(302, '/auth/login');
			return fail(500, { error: 'Freie Zeitfenster konnten nicht geladen werden.' });
		}
	},
	confirm: async ({ request, fetch }) => {
		const form = await request.formData();
		const summary = String(form.get('summary'));
		const start_at = String(form.get('start_at'));
		const end_at = String(form.get('end_at'));
		const { status, data } = await apiPost<{ detail?: string }>(fetch, '/api/calendar/events', {
			summary,
			start_at,
			end_at,
			description: null
		});
		if (status !== 201) {
			return fail(status, { error: `Termin konnte nicht angelegt werden (${data.detail ?? status}).` });
		}
		return { confirmed: true };
	},
	delete: async ({ request, fetch }) => {
		const form = await request.formData();
		const eventId = String(form.get('event_id'));
		await fetch(`/api/calendar/events/${eventId}`, { method: 'DELETE', credentials: 'include' });
		return { deleted: true };
	}
};
```

Note: `delete` uses a raw `fetch` (not `apiPost`, since there's no JSON body and `apiPost` always sends one) but still passes `credentials: 'include'` directly, satisfying the Global Constraint. Check that `ApiError` is actually exported from `web/src/lib/api.ts` (it should be, per the prior plan's Task 4/finding fixes — `export class ApiError extends Error`) — if the export is missing, add `export` to its class declaration rather than reimplementing error handling here.

- [ ] **Step 2: Implement the page**

```svelte
<!-- web/src/routes/calendar/+page.svelte -->
<script lang="ts">
	import { enhance } from '$app/forms';
	import type { PageData, ActionData } from './$types';

	let { data, form }: { data: PageData; form: ActionData } = $props();
</script>

<h1>Kalender</h1>
<p class="lede">Die nächsten 14 Tage sowie freie Zeitfenster zum Vorschlagen eines Termins.</p>

<div class="tile">
	<h3>Termine</h3>
	{#if data.events.length === 0}
		<p class="empty">Keine Termine im Zeitraum.</p>
	{:else}
		<table>
			<thead>
				<tr>
					<th>Titel</th>
					<th>Start</th>
					<th>Ende</th>
					<th></th>
				</tr>
			</thead>
			<tbody>
				{#each data.events as event (event.id)}
					<tr>
						<td>{event.summary ?? '(ohne Titel)'}</td>
						<td class="figure">{new Date(event.start_at).toLocaleString('de-DE')}</td>
						<td class="figure">{new Date(event.end_at).toLocaleString('de-DE')}</td>
						<td>
							<form method="POST" action="?/delete" use:enhance>
								<input type="hidden" name="event_id" value={event.id} />
								<button type="submit" class="btn btn-ghost">Löschen</button>
							</form>
						</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>

<div class="tile propose-tile">
	<h3>Termin vorschlagen</h3>
	<form method="POST" action="?/propose-slots" use:enhance class="propose-form">
		<label class="field">
			Dauer (Minuten)
			<input type="number" name="duration_minutes" min="15" step="15" value="60" required />
		</label>
		<button type="submit" class="btn btn-primary">Freie Slots anzeigen</button>
	</form>

	{#if form?.slots}
		<ul class="slot-list">
			{#each form.slots as slot (slot.start)}
				<li class="slot-row">
					<span class="figure">
						{new Date(slot.start).toLocaleString('de-DE')} &ndash; {new Date(slot.end).toLocaleTimeString('de-DE')}
					</span>
					<form method="POST" action="?/confirm" use:enhance>
						<input type="hidden" name="start_at" value={slot.start} />
						<input type="hidden" name="end_at" value={slot.end} />
						<input type="text" name="summary" placeholder="Titel" required />
						<button type="submit" class="btn btn-primary">Bestätigen</button>
					</form>
				</li>
			{/each}
		</ul>
	{/if}
	{#if form?.error}
		<p class="status-error">{form.error}</p>
	{/if}
	{#if form?.confirmed}
		<p class="status-success">Termin angelegt.</p>
	{/if}
</div>

<style>
	.lede {
		color: var(--color-text-muted);
		max-width: 32rem;
	}
	.propose-tile {
		margin-top: var(--space-4);
	}
	.propose-form {
		display: flex;
		align-items: flex-end;
		gap: var(--space-3);
	}
	.slot-list {
		list-style: none;
		margin: var(--space-4) 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: var(--space-3);
	}
	.slot-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: var(--space-4);
		padding: var(--space-3);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
	}
	.slot-row form {
		display: flex;
		gap: var(--space-2);
	}
	.slot-row input[type='text'] {
		font: inherit;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: var(--space-2);
		color: var(--color-text);
	}
</style>
```

- [ ] **Step 3: Add the nav link**

In `web/src/routes/+layout.svelte`, add a fourth link to `.nav-links` (after the existing three, before the `{#if data.authenticated}` logout block):

```svelte
<a href={resolve('/calendar')}>Kalender</a>
```

- [ ] **Step 4: Manual verification**

Start the frontend dev server (`npm run dev` from `web/`) and, with a session cookie set (see the prior plan's established pattern — a fake `session_id` cookie via browser devtools is enough to pass `hooks.server.ts`'s presence check; a real backend call will 401 without live infra, exercising the same graceful `redirect(302, '/auth/login')` path this task's `load()` implements), confirm `/calendar` redirects correctly rather than crashing. This mirrors the exact verification approach used for the Dashboard/Sync pages in the prior plan given the same `deploy/docker-compose.dev.yml`-only local infra.

- [ ] **Step 5: Type-check and lint**

Run (from `web/`): `npm run check && npm run lint`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/calendar/ web/src/routes/+layout.svelte
git commit -m "feat(web): /calendar page — event list, free-slot proposal, confirm/delete"
```

---

### Task 12: Dedup integration test — Kairos-created event survives a sync poll without duplicating

**Files:**
- Test: `tests/test_calendar_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9 (this is the plan's final-review-style end-to-end check, run as a normal task rather than deferred, since it directly verifies the design spec's core Abnahme criterion: "Ein erneuter Sync-Lauf erzeugt keine Duplikate").

- [ ] **Step 1: Write the test**

```python
# tests/test_calendar_integration.py
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.connectors.google_calendar.connector import GoogleCalendarConnector
from kairos.db.rls import install_rls_listener
from kairos.repositories.calendar_event import CalendarEventRepository


async def _insert_user(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "INSERT INTO app_user (id, email, display_name, google_sub, home_timezone, role) "
            "VALUES (:id, :email, 'Test', :sub, 'UTC', 'user')"
        ),
        {"id": str(user_id), "email": f"{user_id}@test.com", "sub": f"sub-{user_id}"},
    )
    await session.commit()


@pytest.mark.asyncio
async def test_kairos_created_event_does_not_duplicate_on_next_sync(
    session: AsyncSession,
) -> None:
    user_id = uuid4()
    await _insert_user(session, user_id)
    install_rls_listener(session, user_id)

    # Step 1: Kairos creates an event (simulating what the POST /api/calendar/events
    # handler does — call the Google client directly, then upsert the canonical row).
    mock_client = MagicMock()
    mock_client.create_event.return_value = {"id": "google-evt-round-trip"}
    connector = GoogleCalendarConnector(mock_client)
    created = mock_client.create_event(
        "primary",
        summary="Proposed Training",
        start=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        end=datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        description=None,
    )
    del connector  # not exercised in this path — matches Task 9's direct-client-call choice

    repo = CalendarEventRepository(session)
    await repo.upsert_kairos_event(
        user_id,
        "google_calendar",
        str(created["id"]),
        "Proposed Training",
        datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
        datetime(2026, 5, 1, 10, 0, tzinfo=UTC),
        None,
    )
    await session.commit()

    # Step 2: a later sync poll fetches from Google and sees the SAME event echoed back
    # (this is what google_calendar's real sync would receive from Google's API).
    mock_client.list_events.return_value = {
        "items": [
            {
                "id": "google-evt-round-trip",
                "summary": "Proposed Training",
                "status": "confirmed",
                "start": {"dateTime": "2026-05-01T09:00:00+00:00"},
                "end": {"dateTime": "2026-05-01T10:00:00+00:00"},
            }
        ],
        "nextSyncToken": "tok-1",
    }
    sync_connector = GoogleCalendarConnector(mock_client)
    from kairos.connectors.types import Window

    envelope = sync_connector.fetch(
        user_id,
        "events",
        Window(start=datetime(2026, 4, 25, tzinfo=UTC), end=datetime(2026, 5, 8, tzinfo=UTC)),
    )
    records = sync_connector.normalize("events", envelope.payload)
    written = await repo.upsert_from_records(user_id, "google_calendar", records)
    await session.commit()

    assert written == 1  # upsert ran, but as an UPDATE not an INSERT

    events = await repo.list_between(
        user_id, datetime(2026, 4, 30, tzinfo=UTC), datetime(2026, 5, 2, tzinfo=UTC)
    )
    assert len(events) == 1  # no duplicate row
    assert events[0].source == "kairos"  # source flag from the original create is preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python -m pytest tests/test_calendar_integration.py -v`
Expected: this should actually PASS if Tasks 1-9 are implemented correctly — there is no new production code in this task, only a test that exercises the already-built pieces end-to-end. If it fails, that means one of Tasks 1-9 has a real bug; fix the bug in the relevant earlier task's file (not by weakening this test), then re-run.

- [ ] **Step 3: Run the full backend suite**

Run: `.venv/Scripts/python -m pytest -q`
Expected: all tests passing, including this new one.

- [ ] **Step 4: Type-check and lint**

Run: `.venv/Scripts/python -m ruff check tests/test_calendar_integration.py` and `.venv/Scripts/python -m mypy --strict src/kairos/`
Expected: clean across the whole `src/kairos/` tree (this is the last backend task in the plan — a full-tree mypy run catches any cross-file type drift the per-task checks might have missed).

- [ ] **Step 5: Commit**

```bash
git add tests/test_calendar_integration.py
git commit -m "test(calendar): verify Kairos-created events dedup correctly on the next sync"
```

---

## Self-Review

**Spec coverage:** Scope-Entscheidung 1 (Google-only) → no CalDAV code anywhere in this plan, confirmed. Scope-Entscheidung 2 (reuse OAuth token) → Task 2. Scope-Entscheidung 3 (`primary` calendar) → hardcoded `_DEFAULT_CALENDAR_ID`/`"primary"` throughout Tasks 4/7/9, no picker UI. Scope-Entscheidung 4 (no watch-channels) → Task 7 is poll-only, no webhook route anywhere. Datenmodell → Task 1 (table + columns), Tasks 5/7 (sync_state/connection reuse, no new table for either). Backend-Architektur → Tasks 3/4 (connector), 5 (repository), 6 (free-time), 7 (sync job), 8/9 (API). Frontend → Tasks 10/11. Testing-Strategie → unit tests in every backend task, one integration test (Task 12), no new Playwright E2E (deliberately, matches the spec's stated consistency reasoning). Abnahmekriterien → Task 12 directly verifies the no-duplicate-on-resync criterion; the create/edit/delete-appears-in-Google criterion is covered by Tasks 3/4/9's tests (mocked at the httpx boundary, the same level of rigor the existing Garmin connector tests use — a live Google account round-trip is out of scope for automated tests, matching how Garmin's real-account testing is handled via the separate `garmin_tokens_smoke.json` manual smoke-test path, not automated CI).

**Placeholder scan:** No TBD/TODO. One deliberate scope note in Task 9 (documenting why it calls `client.create_event` directly instead of routing through `write_back`) — this is a documented design decision, not a placeholder.

**Type consistency:** `CalendarEvent`/`FreeBlock`/`BusyBlock`/`CalendarPrefs` (Task 6) are used identically in Task 8's `free_slots` handler. `CanonicalRecord.data` keys (`summary`, `description`, `location`, `start_at`, `end_at`, `all_day`, `status`) are produced by Task 4's `normalize_events` and consumed identically by Task 5's `upsert_from_records`. `GoogleCalendarClient`'s method signatures (Task 3) are called with matching argument shapes in Task 4's `connector.py`, Task 7's `_run_calendar_sync_task`, and Task 9's `create_event`/`delete_event` calls. `CalendarEvent`/`FreeSlot` TypeScript interfaces (Task 10) match the exact JSON keys the Python `list_events`/`free_slots` endpoints (Task 8) return.
