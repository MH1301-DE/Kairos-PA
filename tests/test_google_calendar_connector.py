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


def test_connector_write_back_counts_google_error_response_as_failure() -> None:
    mock_client = MagicMock()
    mock_client.create_event.return_value = {"error": {"code": 400, "message": "Invalid time"}}
    connector = GoogleCalendarConnector(mock_client)
    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="",
            data={
                "action": "create",
                "summary": "Bad Time",
                "start_at": "2026-03-01T07:00:00+00:00",
                "end_at": "2026-03-01T08:30:00+00:00",
                "description": None,
            },
        )
    ]

    result = connector.write_back(uuid4(), "events", records)

    assert result.written == 0
    assert result.failed == 1


def test_connector_write_back_update_counts_google_error_response_as_failure() -> None:
    mock_client = MagicMock()
    mock_client.update_event.return_value = {"error": {"code": 404, "message": "Not Found"}}
    connector = GoogleCalendarConnector(mock_client)
    records = [
        CanonicalRecord(
            record_type="calendar_event",
            external_id="",
            data={"action": "update", "event_id": "evt-1", "summary": "Renamed"},
        )
    ]

    result = connector.write_back(uuid4(), "events", records)

    assert result.written == 0
    assert result.failed == 1
