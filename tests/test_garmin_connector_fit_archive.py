from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from kairos.connectors.garmin.connector import GarminConnector
from kairos.connectors.types import Window
from tests.test_fit_decoder import mini_fit_zip

WINDOW = Window(start=datetime(2026, 8, 4, tzinfo=UTC), end=datetime(2026, 8, 5, tzinfo=UTC))


class FakeGarmin:
    def __init__(self, activities: list[dict[str, Any]], zips: dict[int, bytes | Exception]):
        self._activities = activities
        self._zips = zips
        self.downloaded: list[int] = []

    def get_activities_by_date(self, start: str, end: str) -> list[dict[str, Any]]:
        del start, end
        return self._activities

    def download_activity(self, activity_id: int, dl_fmt: Any = None) -> bytes:
        del dl_fmt
        self.downloaded.append(activity_id)
        result = self._zips[activity_id]
        if isinstance(result, Exception):
            raise result
        return result


def _zip(hr: int) -> bytes:
    return mini_fit_zip(datetime(2026, 8, 4, 9, 0, tzinfo=UTC), [hr, hr + 1])


def test_activity_fit_archives_zips_and_returns_manifest() -> None:
    zip_a, zip_b = _zip(120), _zip(150)
    garmin = FakeGarmin(
        [
            {"activityId": 11, "startTimeGMT": "2026-08-04 09:00:00"},
            {"activityId": 22},
        ],
        {11: zip_a, 22: zip_b},
    )
    connector = GarminConnector(garmin, fit_download_pause_s=2.0)

    with patch("kairos.connectors.garmin.connector.time.sleep") as sleep:
        envelope = connector.fetch(user_id=uuid4(), kind="activity_fit", window=WINDOW)

    sleep.assert_called_once_with(2.0)
    assert envelope.payload == {
        "activities": [
            {"activity_id": "11", "sha256": hashlib.sha256(zip_a).hexdigest()},
            {"activity_id": "22", "sha256": hashlib.sha256(zip_b).hexdigest()},
        ]
    }
    assert [(f.kind, f.key, f.payload_format) for f in envelope.files] == [
        ("activity_fit_file", "11", "fit_zip"),
        ("activity_fit_file", "22", "fit_zip"),
    ]
    assert envelope.files[0].content == zip_a
    assert envelope.files[0].window_start == datetime(2026, 8, 4, 9, 0, tzinfo=UTC)
    # no startTimeGMT -> day window start
    assert envelope.files[1].window_start == WINDOW.start


def test_failed_download_is_listed_and_next_activity_still_loaded() -> None:
    zip_b = _zip(150)
    garmin = FakeGarmin(
        [{"activityId": 11}, {"activityId": 22}],
        {11: RuntimeError("gone"), 22: zip_b},
    )
    connector = GarminConnector(garmin)

    with patch("kairos.connectors.garmin.connector.time.sleep") as sleep:
        envelope = connector.fetch(user_id=uuid4(), kind="activity_fit", window=WINDOW)

    sleep.assert_not_called()
    assert garmin.downloaded == [11, 22]
    assert envelope.payload == {
        "activities": [
            {"activity_id": "11", "error": "gone"},
            {"activity_id": "22", "sha256": hashlib.sha256(zip_b).hexdigest()},
        ]
    }
    assert [f.key for f in envelope.files] == ["22"]
