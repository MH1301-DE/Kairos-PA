from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kairos.activities.streams import STREAM_CHANNELS, build_streams

T0 = datetime(2026, 5, 1, 6, 0, 0, tzinfo=UTC)


def _rec(sec: int, **fields: object) -> dict[str, object]:
    return {"timestamp": T0 + timedelta(seconds=sec), **fields}


def test_channel_registry() -> None:
    storage = {c.code: c.storage for c in STREAM_CHANNELS}
    assert set(storage) == {
        "hr", "cadence", "speed_mps", "distance_m", "altitude_m",
        "power_w", "lat_deg", "lng_deg", "temp_c",
    }
    assert {k for k, v in storage.items() if v == "v8"} == {"lat_deg", "lng_deg"}


def test_alignment_with_gaps() -> None:
    ss = build_streams(
        [_rec(0, heart_rate=140), _rec(1), _rec(2, heart_rate=150)], source="fit_zip"
    )
    assert ss is not None
    assert ss.start_at == T0
    assert ss.t_offset_s == [0, 1, 2]
    assert ss.channels["hr"] == [140.0, None, 150.0]


def test_channel_without_values_is_absent() -> None:
    ss = build_streams([_rec(0, heart_rate=140), _rec(1, heart_rate=141)], source="fit_zip")
    assert ss is not None
    assert set(ss.channels) == {"hr"}


def test_enhanced_precedence_and_fallback() -> None:
    ss = build_streams(
        [
            _rec(0, speed=2.0, enhanced_speed=2.5, altitude=10.0, enhanced_altitude=12.0),
            _rec(1, speed=3.0, altitude=11.0),
        ],
        source="fit_zip",
    )
    assert ss is not None
    assert ss.channels["speed_mps"] == [2.5, 3.0]
    assert ss.channels["altitude_m"] == [12.0, 11.0]


def test_cadence_includes_fraction() -> None:
    ss = build_streams(
        [_rec(0, cadence=82, fractional_cadence=0.5), _rec(1, cadence=80)], source="fit_zip"
    )
    assert ss is not None
    assert ss.channels["cadence"] == [82.5, 80.0]


def test_semicircle_positions() -> None:
    ss = build_streams([_rec(0, position_lat=2**30, position_long=-(2**30))], source="fit_zip")
    assert ss is not None
    assert ss.channels["lat_deg"] == [90.0]
    assert ss.channels["lng_deg"] == [-90.0]


def test_other_channels_mapped() -> None:
    ss = build_streams(
        [_rec(0, distance=5.5, power=250, temperature=18)], source="fit_zip"
    )
    assert ss is not None
    assert ss.channels == {"distance_m": [5.5], "power_w": [250.0], "temp_c": [18.0]}


def test_duplicate_second_first_wins() -> None:
    ss = build_streams(
        [_rec(0, heart_rate=140), _rec(0, heart_rate=141), _rec(1, heart_rate=142)],
        source="fit_zip",
    )
    assert ss is not None
    assert ss.t_offset_s == [0, 1]
    assert ss.channels["hr"] == [140.0, 142.0]


def test_subsecond_floored_and_deduplicated() -> None:
    recs = [
        {"timestamp": T0, "heart_rate": 140},
        {"timestamp": T0 + timedelta(milliseconds=600), "heart_rate": 141},
        {"timestamp": T0 + timedelta(milliseconds=1500), "heart_rate": 142},
    ]
    ss = build_streams(recs, source="fit_zip")
    assert ss is not None
    assert ss.t_offset_s == [0, 1]
    assert ss.channels["hr"] == [140.0, 142.0]


def test_json_and_datetime_timestamps_equal() -> None:
    dt_recs = [_rec(0, heart_rate=140), _rec(2, heart_rate=150)]
    js_recs = [
        {"timestamp": "2026-05-01T06:00:00+00:00", "heart_rate": 140},
        {"timestamp": "2026-05-01T06:00:02Z", "heart_rate": 150},
    ]
    a = build_streams(dt_recs, source="fit_zip")
    b = build_streams(js_recs, source="fit_zip")
    assert a == b


def test_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2026, 5, 1, 6, 0, 0)
    ss = build_streams([{"timestamp": naive, "heart_rate": 1}], source="fit_json")
    assert ss is not None
    assert ss.start_at == T0
    assert ss.start_at.tzinfo is not None
    assert ss.source == "fit_json"


def test_invalid_timestamp_skipped_and_empty_returns_none() -> None:
    assert build_streams([], source="fit_zip") is None
    assert build_streams([{"heart_rate": 1}, {"timestamp": "bad"}], source="fit_zip") is None
    ss = build_streams([{"heart_rate": 1}, _rec(5, heart_rate=2)], source="fit_zip")
    assert ss is not None
    assert ss.t_offset_s == [0]


def test_out_of_order_records_are_sorted() -> None:
    ss = build_streams(
        [_rec(5, heart_rate=150), _rec(2, heart_rate=140), _rec(-3, heart_rate=130)],
        source="fit_zip",
    )
    assert ss is not None
    assert ss.start_at == T0 - timedelta(seconds=3)
    assert ss.t_offset_s == [0, 5, 8]
    assert ss.channels["hr"] == [130.0, 140.0, 150.0]


def test_duplicate_second_merges_per_channel() -> None:
    ss = build_streams(
        [_rec(0, heart_rate=140), _rec(0, heart_rate=141, power=250)], source="fit_zip"
    )
    assert ss is not None
    assert ss.t_offset_s == [0]
    assert ss.channels == {"hr": [140.0], "power_w": [250.0]}
