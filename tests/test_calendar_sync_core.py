from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from kairos.calendar import sync as calendar_sync
from kairos.calendar.sync import CalendarNotConnected, sync_google_calendar
from kairos.connectors.google_calendar.client import TokenExpired
from kairos.connectors.types import CanonicalRecord, RawPayloadEnvelope
from kairos.ingestion.job_registry import SyncBusy, get_registry


def _record(external_id: str, status: str) -> CanonicalRecord:
    return CanonicalRecord(
        record_type="calendar_event",
        external_id=external_id,
        occurred_at=None,
        data={"status": status},
    )


@pytest.fixture
def harness() -> Iterator[SimpleNamespace]:
    session = MagicMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    conn = SimpleNamespace(status="active", last_error=None, reauth_since=None, last_ok_at=None)
    connector = MagicMock()
    connector.fetch.return_value = RawPayloadEnvelope(
        window=calendar_sync.default_window(), payload={}
    )
    connector.normalize.return_value = [_record("a", "confirmed"), _record("b", "cancelled")]
    repo = MagicMock()
    repo.upsert_from_records = AsyncMock(return_value=2)
    with (
        patch.object(calendar_sync, "_active_connection", AsyncMock(return_value=conn)),
        patch.object(
            calendar_sync, "build_google_calendar_client", AsyncMock(return_value=object())
        ),
        patch.object(calendar_sync, "GoogleCalendarConnector", return_value=connector),
        patch.object(calendar_sync, "CalendarEventRepository", return_value=repo),
    ):
        yield SimpleNamespace(session=session, conn=conn, connector=connector)


@pytest.mark.asyncio
async def test_success_counts_and_marks_connection_healthy(harness: SimpleNamespace) -> None:
    result = await sync_google_calendar(harness.session, uuid4())

    assert result == {
        "fetched": 2,
        "upserted": 2,
        "cancelled": 1,
        "failed_calendars": [],
        "error_code": None,
    }
    assert harness.conn.last_ok_at is not None
    harness.session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_expired_token_reports_reauth_required(harness: SimpleNamespace) -> None:
    harness.connector.fetch.side_effect = TokenExpired("no longer valid")

    result = await sync_google_calendar(harness.session, uuid4())

    assert result["error_code"] == "reauth_required"
    assert harness.conn.status == "reauth_required"
    assert harness.conn.reauth_since is not None


@pytest.mark.asyncio
async def test_upstream_error_keeps_a_fixed_text(harness: SimpleNamespace) -> None:
    harness.connector.fetch.side_effect = RuntimeError("https://upstream/secret 500 body")

    result = await sync_google_calendar(harness.session, uuid4())

    assert result["error_code"] == "unavailable"
    assert "secret" not in str(harness.conn.last_error)


@pytest.mark.asyncio
async def test_not_connected_raises(harness: SimpleNamespace) -> None:
    with (
        patch.object(calendar_sync, "build_google_calendar_client", AsyncMock(return_value=None)),
        pytest.raises(CalendarNotConnected),
    ):
        await sync_google_calendar(harness.session, uuid4())


@pytest.mark.asyncio
async def test_lock_shared_with_the_button_raises_busy(harness: SimpleNamespace) -> None:
    user_id = uuid4()
    lock: Any = get_registry().get_lock(user_id, "google_calendar", "events")
    async with lock:
        with pytest.raises(SyncBusy):
            await sync_google_calendar(harness.session, user_id)
