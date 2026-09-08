from __future__ import annotations

from datetime import UTC, datetime

from kairos.connectors.garmin.normalize import normalize_payload


def test_normalize_hr_intraday_into_canonical_records() -> None:
    # get_heart_rates's real shape: list of [ts_ms, value] pairs, verified
    # against a real archived Garmin response -- NOT {"timestamp", "value"}
    # dicts (that shape never matched the live API).
    payload = {
        "heartRateValues": [
            [1785834000000, 62],  # 2026-08-04T09:00:00Z
            [1785834060000, 64],  # 2026-08-04T09:01:00Z
        ]
    }

    records = normalize_payload(kind="hr_intraday", payload=payload)

    assert len(records) == 2
    assert records[0].record_type == "wellness_sample"
    assert records[0].external_id == "hr:2026-08-04T09:00:00+00:00"
    assert records[0].occurred_at == datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    assert records[0].data == {"metric": "hr", "value": 62.0, "quality": "ok"}


def test_normalize_sleep_into_canonical_records() -> None:
    # get_sleep_data's real shape: no top-level "sleepId" -- the id lives at
    # dailySleepDTO.id (int), and the start/end timestamps are epoch-ms ints,
    # not ISO strings. Verified against a real archived Garmin response.
    payload = {
        "dailySleepDTO": {
            "id": 1785796200000,  # 2026-08-03T22:30:00Z
            "sleepStartTimestampGMT": 1785796200000,  # 2026-08-03T22:30:00Z
            "sleepEndTimestampGMT": 1785825000000,  # 2026-08-04T06:30:00Z
            "sleepTimeSeconds": 27600,
            "calendarDate": "2026-08-04",
        },
    }

    records = normalize_payload(kind="sleep", payload=payload)

    assert len(records) == 1
    assert records[0].record_type == "sleep_session"
    assert records[0].external_id == "1785796200000"
    assert records[0].occurred_at == datetime(2026, 8, 3, 22, 30, tzinfo=UTC)
    assert records[0].data == {
        "start_at": "2026-08-03T22:30:00+00:00",
        "end_at": "2026-08-04T06:30:00+00:00",
        "duration_seconds": 27600,
        "day": "2026-08-04",
    }