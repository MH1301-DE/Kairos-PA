from __future__ import annotations

from datetime import UTC, date, datetime
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
        return datetime(d.year, d.month, d.day, tzinfo=UTC), True
    return None, False
