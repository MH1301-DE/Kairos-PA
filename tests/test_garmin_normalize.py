from __future__ import annotations

from datetime import UTC, datetime

from kairos.connectors.garmin.normalize import normalize_payload


def test_normalize_hr_intraday_into_canonical_records() -> None:
    payload = {
        "heartRateValues": [
            {"timestamp": "2026-08-04T09:00:00Z", "value": 62},
            {"timestamp": "2026-08-04T09:01:00Z", "value": 64},
        ]
    }

    records = normalize_payload(kind="hr_intraday", payload=payload)

    assert len(records) == 2
    assert records[0].record_type == "wellness_sample"
    assert records[0].external_id == "hr:2026-08-04T09:00:00+00:00"
    assert records[0].occurred_at == datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    assert records[0].data == {"metric": "heart_rate", "value": 62.0}


def test_normalize_sleep_into_canonical_records() -> None:
    payload = {
        "dailySleepDTO": {
            "sleepStartTimestampGMT": "2026-08-03T22:30:00Z",
            "sleepEndTimestampGMT": "2026-08-04T06:45:00Z",
            "sleepTimeSeconds": 29700,
            "calendarDate": "2026-08-04",
        },
        "sleepId": "sleep-123",
    }

    records = normalize_payload(kind="sleep", payload=payload)

    assert len(records) == 1
    assert records[0].record_type == "sleep_session"
    assert records[0].external_id == "sleep-123"
    assert records[0].occurred_at == datetime(2026, 8, 3, 22, 30, tzinfo=UTC)
    assert records[0].data == {
        "start_at": "2026-08-03T22:30:00+00:00",
        "end_at": "2026-08-04T06:45:00+00:00",
        "duration_seconds": 29700,
        "day": "2026-08-04",
    }