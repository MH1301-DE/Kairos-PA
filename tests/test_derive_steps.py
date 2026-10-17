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
    cadence: float | None = None,
) -> StepResultRow:
    n = seconds + 1
    speed = 1000 / pace_s_km
    channels: dict[str, list[float | None]] = {
        "distance_m": [speed * i for i in range(n)],
        "hr": hr if hr is not None else [140.0] * n,
    }
    if cadence is not None:
        channels["cadence"] = [cadence] * n
    stream = LoadedStream(
        start_at=START,
        t_offset_s=list(range(n)),
        channels=channels,
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
    rows, _ = _fixture_results(hr_targets={0: (150.0, 100.0)})
    warmup = rows[0]
    assert (warmup.target_type, warmup.target_source) == ("hr_range", "api")
    assert (warmup.target_low, warmup.target_high) == (100.0, 150.0)
    # plain 1 Hz sample count over the two warmup laps: 98.15 %
    assert warmup.hr_in_target_pct == pytest.approx(98.15, abs=0.2)
    assert warmup.avg_hr == pytest.approx(140.5, abs=0.1)
    assert warmup.hit is True
    assert rows[2].target_source == "unclear"


def test_fixture_hr_target_below_80_percent_misses() -> None:
    rows, _ = _fixture_results(hr_targets={0: (130.0, 145.0)})
    # plain 1 Hz sample count: 76.96 %
    assert rows[0].hr_in_target_pct == pytest.approx(76.9, abs=0.2)
    assert rows[0].hit is False


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


def _steps_run(
    workout_steps: list[dict[str, Any]], laps: list[tuple[int, float]]
) -> list[StepResultRow]:
    total = int(sum(sec for _, sec in laps)) + 1
    stream = LoadedStream(
        start_at=START,
        t_offset_s=list(range(total)),
        channels={"distance_m": [3.5 * i for i in range(total)]},
        source="fit_zip",
    )
    prep = prepare(stream, sport_profile="running", events=[])
    lap_mesgs: list[dict[str, Any]] = []
    offset = 0.0
    for index, sec in laps:
        lap_mesgs.append(
            {
                "start_time": START + timedelta(seconds=offset),
                "total_elapsed_time": sec,
                "total_timer_time": sec,
                "total_distance": 3.5 * sec,
                "wkt_step_index": index,
            }
        )
        offset += sec
    return step_results(
        prep,
        sport_profile="running",
        workout_steps=workout_steps,
        laps=lap_mesgs,
        start_at=START,
        hr_targets=None,
    )


def _time_step(index: int, secs: float) -> dict[str, Any]:
    return {"message_index": index, "duration_type": "time", "duration_time": secs}


def _repeat(index: int, first: int, count: int) -> dict[str, Any]:
    return {
        "message_index": index,
        "duration_type": "repeat_until_steps_cmplt",
        "duration_step": first,
        "target_value": count,
    }


def test_nested_repeat_iterations() -> None:
    # 0, outer x2 [1, inner x2 [2, 3], 5], 7
    steps = [
        _time_step(0, 60),
        _time_step(1, 60),
        _time_step(2, 30),
        _time_step(3, 30),
        _repeat(4, 2, 2),
        _time_step(5, 60),
        _repeat(6, 1, 2),
        _time_step(7, 60),
    ]
    one_pass = [(1, 60.0), (2, 30.0), (3, 30.0), (2, 30.0), (3, 30.0), (5, 60.0)]
    rows = _steps_run(steps, [(0, 60.0), *one_pass, *one_pass, (7, 60.0)])
    assert [r.wkt_step_index for r in rows] == [0, 1, 2, 3, 2, 3, 5, 1, 2, 3, 2, 3, 5, 7]
    assert [r.repeat_iteration for r in rows] == [
        None, 1, 1, 1, 2, 2, 1, 2, 1, 1, 2, 2, 2, None
    ]  # fmt: skip


def test_single_step_repeat_splits_on_planned_duration() -> None:
    steps = [_time_step(0, 60), _repeat(1, 0, 3)]
    # auto-lap splits pass 1, passes 2 and 3 are one lap each
    rows = _steps_run(steps, [(0, 40.0), (0, 20.0), (0, 60.0), (0, 60.0)])
    assert [r.repeat_iteration for r in rows] == [1, 2, 3]
    assert [r.timer_s for r in rows] == pytest.approx([60.0, 60.0, 60.0])


def test_unresolvable_window_has_no_timer() -> None:
    stream = LoadedStream(start_at=START, t_offset_s=[], channels={}, source="fit_zip")
    prep = prepare(stream, sport_profile="running", events=[])
    lap = {"start_time": START, "total_elapsed_time": 60.0, "wkt_step_index": 1}
    rows = step_results(
        prep,
        sport_profile="running",
        workout_steps=[_speed_step(1, 275, 285)],
        laps=[lap],
        start_at=START,
        hr_targets=None,
    )
    assert rows[0].timer_s is None and rows[0].avg_pace_s_km is None and rows[0].hit is None


@pytest.mark.parametrize(
    ("notes", "name", "expected"),
    [
        (["Auslaufen", "", "UUxD0 D0iC0$e8"], None, "Auslaufen"),
        (["", "", "junk"], "Trab", "Trab"),
        (["", "", "junk"], None, None),
    ],
)
def test_note_uses_fit_string_chunk_zero(
    notes: list[str], name: str | None, expected: str | None
) -> None:
    step = {**_hr_step(2), "notes": notes, "wkt_step_name": name}
    assert _synthetic(60, step).step_note == expected


def test_running_cadence_target_is_compared_in_steps_per_minute() -> None:
    # FIT stores running cadence targets per leg, like the cadence channel itself
    step = {
        "message_index": 1,
        "duration_type": "open",
        "target_type": "cadence",
        "custom_target_cadence_low": 81,
        "custom_target_cadence_high": 85,
        "intensity": "interval",
    }
    row = _synthetic(120, step, cadence=83.0)
    assert (row.target_low, row.target_high) == (162.0, 170.0)
    assert row.avg_cadence == pytest.approx(166.0)
    assert row.hit is True
