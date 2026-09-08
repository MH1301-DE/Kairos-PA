from kairos.connectors.garmin.normalize import normalize_payload

# get_heart_rates's real shape: list of [ts_ms, value] pairs (verified against
# a real archived Garmin response), not {"timestamp", "value"} dicts.
_TS_MS = 1785657600000  # 2026-08-01T10:00:00Z


def test_hr_within_range_is_ok():
    payload = {"heartRateValues": [[_TS_MS, 65]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"


def test_hr_below_25_is_suspect():
    payload = {"heartRateValues": [[_TS_MS, 20]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_above_230_is_suspect():
    payload = {"heartRateValues": [[_TS_MS, 240]]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_exactly_at_boundaries_is_ok():
    payload = {
        "heartRateValues": [
            [_TS_MS, 25],
            [_TS_MS + 1000, 230],
        ]
    }
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"
    assert records[1].data["quality"] == "ok"
