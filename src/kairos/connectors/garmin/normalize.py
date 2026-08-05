from __future__ import annotations

from datetime import UTC, datetime

from kairos.connectors.types import CanonicalRecord, JSONValue


def normalize_payload(*, kind: str, payload: JSONValue) -> list[CanonicalRecord]:
    if kind == "hr_intraday":
        return _normalize_hr_intraday(payload)
    if kind == "sleep":
        return _normalize_sleep(payload)
    return []


def _normalize_hr_intraday(payload: JSONValue) -> list[CanonicalRecord]:
    if not isinstance(payload, dict):
        return []

    heart_rate_values = payload.get("heartRateValues")
    if not isinstance(heart_rate_values, list):
        return []

    records: list[CanonicalRecord] = []
    for item in heart_rate_values:
        if not isinstance(item, dict):
            continue

        timestamp_raw = item.get("timestamp")
        value_raw = item.get("value")
        if not isinstance(timestamp_raw, str):
            continue
        if not isinstance(value_raw, int | float):
            continue

        occurred_at = _parse_datetime_utc(timestamp_raw)
        if occurred_at is None:
            continue

        records.append(
            CanonicalRecord(
                record_type="wellness_sample",
                external_id=f"hr:{occurred_at.isoformat()}",
                occurred_at=occurred_at,
                data={"metric": "heart_rate", "value": float(value_raw)},
            )
        )

    return records


def _normalize_sleep(payload: JSONValue) -> list[CanonicalRecord]:
    if not isinstance(payload, dict):
        return []

    daily_sleep = payload.get("dailySleepDTO")
    if not isinstance(daily_sleep, dict):
        return []

    sleep_id_raw = payload.get("sleepId")
    start_raw = daily_sleep.get("sleepStartTimestampGMT")
    end_raw = daily_sleep.get("sleepEndTimestampGMT")
    duration_raw = daily_sleep.get("sleepTimeSeconds")
    day_raw = daily_sleep.get("calendarDate")

    if not isinstance(sleep_id_raw, str):
        return []
    if not isinstance(start_raw, str) or not isinstance(end_raw, str):
        return []
    if not isinstance(duration_raw, int):
        return []
    if not isinstance(day_raw, str):
        return []

    start_at = _parse_datetime_utc(start_raw)
    end_at = _parse_datetime_utc(end_raw)
    if start_at is None or end_at is None:
        return []

    return [
        CanonicalRecord(
            record_type="sleep_session",
            external_id=sleep_id_raw,
            occurred_at=start_at,
            data={
                "start_at": start_at.isoformat(),
                "end_at": end_at.isoformat(),
                "duration_seconds": duration_raw,
                "day": day_raw,
            },
        )
    ]


def _parse_datetime_utc(value: str) -> datetime | None:
    normalized = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)