from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from kairos.connectors.google_calendar.client import GoogleCalendarClient
from kairos.connectors.google_calendar.normalize import normalize_events
from kairos.connectors.types import (
    CanonicalRecord,
    JSONValue,
    RawPayloadEnvelope,
    Window,
    WriteResult,
)

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
        # a 4xx from list_events (e.g. Calendar API disabled on the Google Cloud
        # project) comes back as {"error": {...}, "items": []}, not an exception --
        # unlike create_event's call site, nothing downstream checked for this, so
        # the sync silently "succeeded" with 0 events every time. Raise here so it
        # surfaces as a failed job instead.
        _raise_if_error(payload)
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
            description = data.get("description")
            result = self._client.create_event(
                _DEFAULT_CALENDAR_ID,
                summary=str(data["summary"]),
                start=datetime.fromisoformat(str(data["start_at"])),
                end=datetime.fromisoformat(str(data["end_at"])),
                description=str(description) if description is not None else None,
            )
            _raise_if_error(result)
        elif action == "update":
            fields = {k: v for k, v in data.items() if k not in ("action", "event_id")}
            result = self._client.update_event(
                _DEFAULT_CALENDAR_ID, str(data["event_id"]), **fields
            )
            _raise_if_error(result)
        elif action == "delete":
            # delete_event returns None on success; a real HTTP error surfaces via
            # UpstreamUnavailable/TokenExpired raised inside GoogleCalendarClient itself.
            self._client.delete_event(_DEFAULT_CALENDAR_ID, str(data["event_id"]))
        else:
            raise ValueError(f"Unknown write_back action: {action!r}")


def _raise_if_error(result: JSONValue) -> None:
    if isinstance(result, dict) and "error" in result:
        raise RuntimeError(f"Google Calendar API error: {result['error']!r}")
