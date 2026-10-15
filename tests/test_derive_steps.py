from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from kairos.activities.derive.common import prepare
from kairos.activities.derive.steps import StepResultRow, step_results
from kairos.activities.stream_repository import LoadedStream
from kairos.db.models import ActivityStepResult
from tests.activity_fixtures import AUTO_LAP_RUN, WORKOUT_RUN, load_activity_fixture

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def _fixture_results(
    name: str = WORKOUT_RUN, hr_targets: dict[int, tuple[float, float]] | None = None
) -> tuple[list[StepResultRow], dict[str, list[dict[str, Any]]]]:
    fx = load_activity_fixture(name)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages.get("event_mesgs", []))
    rows = step_results(
        prep,
        sport_profile="running",
        workout_steps=fx.messages.get("workout_step_mesgs", []),
        laps=fx.messages["lap_mesgs"],
        start_at=fx.stream.start_at,
        hr_targets=hr_targets,
    )
    return rows, fx.messages


def _speed_step(index: int, low_pace_s: float, high_pace_s: float) -> dict[str, Any]:
    return {
        "message_index": index,
        "duration_type": "time",
        "duration_time": 300.0,
        "target_type": "speed",
        "target_value": 0,
        "custom_target_speed_low": 1000 / high_pace_s,
        "custom_target_speed_high": 1000 / low_pace_s,
        "intensity": "active",
        "notes": "Tempo",
    }


def _hr_step(index: int) -> dict[str, Any]:
    return {
        "message_index": index,
        "duration_type": "open",
        "target_type": "heart_rate",
        "target_value": 0,
        "custom_target_value_low": 100,
        "custom_target_value_high": 150,
        "custom_target_heart_rate_low": "bpm_offset",
        "custom_target_heart_rate_high": 150,
        "intensity": "recovery",
        "wkt_step_name": "Trab",
    }


def _synthetic(
    seconds: int,
    step: dict[str, Any],
    *,
    pace_s_km: float = 300.0,
    hr: list[float | None] | None = None,
    hr_targets: dict[int, tuple[float, float]] | None = None,
) -> StepResultRow:
    n = seconds + 1
    speed = 1000 / pace_s_km
    stream = LoadedStream(
        start_at=START,
        t_offset_s=list(range(n)),
        channels={
            "distance_m": [speed * i for i in range(n)],
            "hr": hr if hr is not None else [140.0] * n,
        },
        source="fit_zip",
    )
    prep = prepare(stream, sport_profile="running", events=[])
    lap = {
        "start_time": START,
        "total_elapsed_time": float(seconds),
        "total_timer_time": float(seconds),
        "wkt_step_index": step["message_index"],
    }
    rows = step_results(
        prep,
        sport_profile="running",
        workout_steps=[step],
        laps=[lap],
        start_at=START,
        hr_targets=hr_targets,
    )
    assert len(rows) == 1
    return rows[0]


def test_row_matches_orm_columns() -> None:
    orm = {c.name for c in ActivityStepResult.__table__.columns} - {"activity_id", "user_id"}
    assert {f.name for f in fields(StepResultRow)} == orm


def test_fixture_executions_group_auto_laps_and_repeats() -> None:
    rows, _ = _fixture_results()
    assert [r.wkt_step_index for r in rows] == [0, 1, 2, 1, 2, 1, 2, 1, 4]
    assert [r.exec_idx for r in rows] == list(range(1, 10))
    assert [r.repeat_iteration for r in rows] == [None, 1, 1, 2, 2, 3, 3, 4, None]
    assert [r.step_type for r in rows] == [
        "warmup",
        "interval",
        "recovery",
        "interval",
        "recovery",
        "interval",
        "recovery",
        "interval",
        "cooldown",
    ]
    # repeat count 4 from the repeat step: every interval ran four times
    assert sum(1 for r in rows if r.wkt_step_index == 1) == 4


def test_fixture_duration_matches_lap_sum() -> None:
    rows, messages = _fixture_results()
    laps = [lap for lap in messages["lap_mesgs"] if lap.get("wkt_step_index") is not None]
    groups: list[float] = []
    prev: int | None = None
    for lap in laps:
        if lap["wkt_step_index"] == prev:
            groups[-1] += lap["total_timer_time"]
        else:
            groups.append(lap["total_timer_time"])
        prev = lap["wkt_step_index"]
    assert len(groups) == len(rows)
    for row, expected in zip(rows, groups, strict=True):
        assert row.timer_s == pytest.approx(expected, abs=1.0)


def test_fixture_targets_and_notes() -> None:
    rows, _ = _fixture_results()
    interval = rows[1]
    assert interval.planned_end == "time 360 s"
    assert interval.step_note == "SCHWELLE 4:50"
    assert interval.target_type == "pace"
    assert interval.target_source == "fit"
    assert interval.target_low == pytest.approx(3.509)
    assert interval.target_high == pytest.approx(3.636)
    assert interval.hit is not None
    warmup = rows[0]
    assert warmup.planned_end == "distance 2000 m"
    assert warmup.step_note == "Einlaufen locker"
    assert warmup.target_type == "hr_range"
    assert warmup.target_source == "unclear"
    assert warmup.target_low is None and warmup.target_high is None
    assert warmup.hit is None
    assert rows[-1].step_note == "Auslaufen"
    assert all(r.secondary_type is None and r.secondary_hit is None for r in rows)


def test_fixture_hr_targets_from_api() -> None:
    rows, _ = _fixture_results(hr_targets={0: (100.0, 150.0)})
    assert rows[0].target_source == "api"
    assert (rows[0].target_low, rows[0].target_high) == (100.0, 150.0)
    assert rows[0].hr_in_target_pct is not None
    assert rows[0].hit is not None
    assert rows[2].target_source == "unclear"


def test_activity_without_workout_is_empty() -> None:
    rows, _ = _fixture_results(AUTO_LAP_RUN)
    assert rows == []


def test_pace_inside_target_hits() -> None:
    row = _synthetic(300, _speed_step(1, 275, 285), pace_s_km=279)
    assert row.avg_pace_s_km == pytest.approx(279, abs=0.5)
    assert row.timer_s == pytest.approx(300)
    assert row.planned_end == "time 300 s"
    assert row.hit is True


def test_pace_too_slow_misses() -> None:
    row = _synthetic(300, _speed_step(1, 275, 285), pace_s_km=292)
    assert row.hit is False


def test_pace_within_tolerance_hits() -> None:
    row = _synthetic(300, _speed_step(1, 275, 285), pace_s_km=290)
    assert row.hit is True


def test_hr_target_without_api_is_unclear() -> None:
    row = _synthetic(120, _hr_step(2))
    assert row.target_type == "hr_range"
    assert row.target_source == "unclear"
    assert row.hit is None
    assert row.planned_end == "lap_button"
    assert row.step_note == "Trab"
    assert row.avg_hr == pytest.approx(140)


def _hr_share(in_range: int, total: int = 100) -> list[float | None]:
    return [140.0] * in_range + [170.0] * (total + 1 - in_range)


def test_hr_target_85_percent_in_range_hits() -> None:
    row = _synthetic(100, _hr_step(2), hr=_hr_share(85), hr_targets={2: (130.0, 150.0)})
    assert row.target_source == "api"
    assert row.hr_in_target_pct == pytest.approx(85, abs=1.5)
    assert row.hit is True


def test_hr_target_64_percent_in_range_misses() -> None:
    row = _synthetic(100, _hr_step(2), hr=_hr_share(64), hr_targets={2: (130.0, 150.0)})
    assert row.hr_in_target_pct == pytest.approx(64, abs=1.5)
    assert row.hit is False


def test_short_execution_not_rated() -> None:
    row = _synthetic(15, _speed_step(1, 275, 285), pace_s_km=279)
    assert row.hit is None


def test_lap_under_5s_ignored() -> None:
    n = 304
    stream = LoadedStream(
        start_at=START,
        t_offset_s=list(range(n)),
        channels={"distance_m": [3.5 * i for i in range(n)]},
        source="fit_zip",
    )
    prep = prepare(stream, sport_profile="running", events=[])
    laps = [
        {"start_time": START, "total_elapsed_time": 300.0, "wkt_step_index": 1},
        {
            "start_time": START + timedelta(seconds=300),
            "total_elapsed_time": 3.0,
            "wkt_step_index": 2,
        },
    ]
    rows = step_results(
        prep,
        sport_profile="running",
        workout_steps=[_speed_step(1, 275, 285), _hr_step(2)],
        laps=laps,
        start_at=START,
        hr_targets=None,
    )
    assert [r.wkt_step_index for r in rows] == [1]


def test_open_target_has_no_rating() -> None:
    step = {"message_index": 0, "duration_type": "open", "target_type": "open"}
    row = _synthetic(60, step)
    assert (row.target_type, row.target_source, row.hit) == ("none", "none", None)
    assert row.step_type == "interval"
