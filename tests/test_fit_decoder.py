from __future__ import annotations

from datetime import UTC, datetime

from kairos.connectors.garmin.fit_decoder import records_to_json
from kairos.ingestion.hash import payload_sha256


def test_records_to_json_stringifies_undecoded_numeric_field_ids() -> None:
    # garmin_fit_sdk uses the raw numeric field id (int) as the dict key when it
    # can't resolve a developer field to a name -- real activity FIT files hit
    # this constantly (e.g. field 140, 107). A mixed int/str-keyed dict crashes
    # json.dumps(sort_keys=True) later (payload_sha256) with
    # "'<' not supported between instances of 'int' and 'str'" when it tries to
    # sort keys -- found against a real backfill, not a synthetic fixture.
    records = [{"timestamp": datetime(2026, 9, 8, tzinfo=UTC), 140: 0, "heart_rate": 88}]

    result = records_to_json(records)

    assert result == [{"timestamp": "2026-09-08T00:00:00+00:00", "140": 0, "heart_rate": 88}]
    assert all(isinstance(k, str) for row in result for k in row)


def test_payload_sha256_does_not_crash_on_records_to_json_output() -> None:
    records = [{"timestamp": datetime(2026, 9, 8, tzinfo=UTC), 140: 0, "heart_rate": 88}]
    payload = {"activities": [{"activity_id": "1", "records": records_to_json(records)}]}

    payload_sha256(payload)
