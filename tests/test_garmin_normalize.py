from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

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


def test_normalize_body_battery_into_canonical_records() -> None:
    # get_body_battery's real shape: list of days, each with
    # bodyBatteryValuesArray as [ts_ms, level] 2-element pairs -- verified
    # against a real archived Garmin response (the payload's own
    # bodyBatteryValueDescriptorDTOList documents indices 0/1 as
    # timestamp/bodyBatteryLevel). NOT a 5-element
    # [startGMT_ms, endGMT_ms, status, startLocal_ms, value] shape.
    payload = [
        {
            "date": "2026-09-07",
            "bodyBatteryValuesArray": [
                [1788732000000, 33],  # 2026-09-06T22:00:00Z
                [1788753240000, 100],  # 2026-09-07T03:54:00Z
            ],
        }
    ]

    records = normalize_payload(kind="body_battery", payload=payload)

    assert len(records) == 2
    assert records[0].record_type == "wellness_sample"
    assert records[0].external_id == "body_battery:2026-09-06T22:00:00+00:00"
    assert records[0].occurred_at == datetime(2026, 9, 6, 22, 0, tzinfo=UTC)
    assert records[0].data == {"metric": "body_battery", "value": 33.0}
    assert records[1].data == {"metric": "body_battery", "value": 100.0}


def test_normalize_hrv_into_canonical_records() -> None:
    # get_hrv_data's real shape: hrvReadings items use "hrvValue" and
    # "readingTimeGMT" -- verified against a real archived Garmin response.
    # The originally assumed field names ("hrv5MinAvg", "startTimeGMT") never
    # existed in the live API.
    payload = {
        "hrvReadings": [
            {"hrvValue": 77, "readingTimeGMT": "2026-09-06T20:38:15.0"},
        ]
    }

    records = normalize_payload(kind="hrv", payload=payload)

    assert len(records) == 1
    assert records[0].record_type == "wellness_sample"
    assert records[0].external_id == "hrv_5min:2026-09-06T20:38:15+00:00"
    assert records[0].occurred_at == datetime(2026, 9, 6, 20, 38, 15, tzinfo=UTC)
    assert records[0].data == {"metric": "hrv_5min", "value": 77.0}


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

def _activity_fixture() -> list[dict[str, object]]:
    path = Path(__file__).parent / "fixtures" / "garmin" / "activity_list_item.json"
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_normalize_activity_list_summer_item() -> None:
    summer, _ = _activity_fixture()

    (record,) = normalize_payload(kind="activity_list", payload=[summer])

    assert record.record_type == "activity"
    assert record.external_id == "9000000001"
    assert record.occurred_at == datetime(2025, 6, 20, 11, 50, 53, tzinfo=UTC)
    d = record.data
    assert isinstance(d, dict)
    assert d["sport"] == "running"
    assert d["sport_profile"] == "running"
    assert d["garmin_type_id"] == 1
    assert d["garmin_parent_type_id"] == 17
    assert d["start_local"] == "2025-06-20T13:50:53"
    assert d["utc_offset_min"] == 120
    assert d["description"] is None
    assert d["moving_duration_s"] == pytest.approx(3434.128, abs=1e-3)
    assert d["avg_speed_mps"] == pytest.approx(2.703, abs=1e-3)
    assert d["lap_count"] == 10
    assert d["garmin_training_load"] == pytest.approx(95.803, abs=1e-3)
    assert d["garmin_vo2max"] == 50.0
    assert d["distance_m"] == pytest.approx(9288.78, abs=1e-2)
    assert d["avg_hr"] == 155.0
    assert "activity_type" not in d


def test_normalize_activity_list_winter_offset_is_plus_60() -> None:
    _, winter = _activity_fixture()

    (record,) = normalize_payload(kind="activity_list", payload=[winter])

    assert record.occurred_at == datetime(2025, 12, 11, 7, 43, 11, tzinfo=UTC)
    assert isinstance(record.data, dict)
    assert record.data["utc_offset_min"] == 60
    assert record.data["start_local"] == "2025-12-11T08:43:11"


def test_normalize_activity_list_without_local_start_has_no_offset() -> None:
    summer, _ = _activity_fixture()
    del summer["startTimeLocal"]

    (record,) = normalize_payload(kind="activity_list", payload=[summer])

    assert isinstance(record.data, dict)
    assert record.data["start_local"] is None
    assert record.data["utc_offset_min"] is None


def test_normalize_activity_list_unknown_type_uses_parent_fallback() -> None:
    summer, _ = _activity_fixture()
    summer["activityType"] = {"typeId": 9999, "typeKey": "new_run_variant", "parentTypeId": 1}

    (record,) = normalize_payload(kind="activity_list", payload=[summer])

    assert isinstance(record.data, dict)
    assert record.data["sport"] == "new_run_variant"
    assert record.data["sport_profile"] == "running"
