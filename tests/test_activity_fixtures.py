from __future__ import annotations

from datetime import datetime

import pytest

from tests.activity_fixtures import (
    AUTO_LAP_RUN,
    POOL_SWIM,
    TREADMILL_RUN,
    WORKOUT_RUN,
    load_activity_fixture,
)

ALL = [AUTO_LAP_RUN, WORKOUT_RUN, POOL_SWIM, TREADMILL_RUN]


@pytest.mark.parametrize("name", ALL)
def test_fixture_loads_aligned_stream_and_datetimes(name: str) -> None:
    fx = load_activity_fixture(name)
    n = len(fx.stream.t_offset_s)
    assert n > 1000
    assert all(len(v) == n for v in fx.stream.channels.values())
    assert isinstance(fx.stream.start_at, datetime)
    assert isinstance(fx.summary["start_at"], datetime)
    for lap in fx.messages["lap_mesgs"]:
        assert isinstance(lap["start_time"], datetime)
    assert fx.messages["session_mesgs"]


@pytest.mark.parametrize("name", ALL)
def test_fixture_is_anonymized(name: str) -> None:
    fx = load_activity_fixture(name)
    assert set(fx.messages) == {
        "session_mesgs",
        "lap_mesgs",
        "length_mesgs",
        "event_mesgs",
        "split_mesgs",
        "workout_mesgs",
        "workout_step_mesgs",
    }
    for msgs in fx.messages.values():
        for m in msgs:
            assert all(not k.isdigit() and "serial" not in k for k in m)
    assert "name" not in fx.summary
    assert not {"activityId", "activityName", "ownerFullName", "deviceId"} & set(fx.list_item)


def test_fixture_contents_match_selection() -> None:
    assert len(load_activity_fixture(AUTO_LAP_RUN).messages["lap_mesgs"]) == 10
    workout = load_activity_fixture(WORKOUT_RUN)
    assert len(workout.messages["lap_mesgs"]) == 16
    assert workout.messages["workout_mesgs"][0]["wkt_name"] == "W3 Do Schwelle 4x6"
    swim = load_activity_fixture(POOL_SWIM)
    assert swim.summary["sport_profile"] == "swimming"
    assert swim.messages["length_mesgs"]
    assert "lat_deg" not in load_activity_fixture(TREADMILL_RUN).stream.channels
