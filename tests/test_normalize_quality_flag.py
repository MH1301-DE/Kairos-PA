from kairos.connectors.garmin.normalize import normalize_payload


def test_hr_within_range_is_ok():
    payload = {"heartRateValues": [{"timestamp": "2026-08-01T10:00:00", "value": 65}]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"


def test_hr_below_25_is_suspect():
    payload = {"heartRateValues": [{"timestamp": "2026-08-01T10:00:00", "value": 20}]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_above_230_is_suspect():
    payload = {"heartRateValues": [{"timestamp": "2026-08-01T10:00:00", "value": 240}]}
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "suspect"


def test_hr_exactly_at_boundaries_is_ok():
    payload = {
        "heartRateValues": [
            {"timestamp": "2026-08-01T10:00:00", "value": 25},
            {"timestamp": "2026-08-01T10:00:01", "value": 230},
        ]
    }
    records = normalize_payload(kind="hr_intraday", payload=payload)
    assert records[0].data["quality"] == "ok"
    assert records[1].data["quality"] == "ok"
