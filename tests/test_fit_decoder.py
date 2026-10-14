from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta

from garmin_fit_sdk import Encoder, Profile

from kairos.connectors.garmin.fit_decoder import decode_fit_zip, records_to_json
from kairos.ingestion.hash import payload_sha256


def mini_fit_zip(start: datetime, heart_rates: list[int]) -> bytes:
    enc = Encoder()
    enc.write_mesg({
        "mesg_num": Profile["mesg_num"]["FILE_ID"],
        "type": "activity",
        "manufacturer": "garmin",
        "product": 1,
        "time_created": start,
        "serial_number": 1,
    })
    for i, hr in enumerate(heart_rates):
        enc.write_mesg({
            "mesg_num": Profile["mesg_num"]["RECORD"],
            "timestamp": start + timedelta(seconds=i),
            "heart_rate": hr,
            "distance": 2.5 * i,
        })
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("activity.fit", enc.close())
    return buf.getvalue()


def test_mini_fit_zip_decodes_records() -> None:
    start = datetime(2026, 8, 4, 9, 0, tzinfo=UTC)

    messages = decode_fit_zip(mini_fit_zip(start, [140, 141]))

    assert [r["heart_rate"] for r in messages["record_mesgs"]] == [140, 141]
    assert messages["record_mesgs"][0]["timestamp"] == start


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
