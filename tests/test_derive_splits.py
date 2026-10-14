from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest

from kairos.activities.derive.common import prepare
from kairos.activities.derive.splits import (
    SplitRow,
    distance_splits,
    fastest_and_slowest_split,
    lap_splits,
    pace_cv_pct,
)
from kairos.activities.stream_repository import LoadedStream
from tests.activity_fixtures import AUTO_LAP_RUN, POOL_SWIM, WORKOUT_RUN, load_activity_fixture

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def _stream(t: list[int], **channels: list[float | None]) -> LoadedStream:
    return LoadedStream(start_at=START, t_offset_s=t, channels=channels, source="fit_zip")


def _timer(kind: str, offset_s: int) -> dict[str, object]:
    return {"event": "timer", "event_type": kind, "timestamp": START + timedelta(seconds=offset_s)}


def _constant_run(total_m: float, speed: float = 3.0, profile: str = "running") -> list[SplitRow]:
    n = math.ceil(total_m / speed) + 1
    dist = [min(speed * i, total_m) for i in range(n)]
    prep = prepare(
        _stream(list(range(n)), distance_m=dist, hr=[150.0] * n),
        sport_profile=profile,
        events=[],
    )
    return distance_splits(prep, sport_profile=profile, lengths=[])


def test_remainder_below_100m_dropped() -> None:
    rows = _constant_run(8020.0)
    assert len(rows) == 8
    assert not any(r.is_partial for r in rows)
    assert [r.idx for r in rows] == list(range(1, 9))
    assert all(r.kind == "distance" and r.unit_m == 1000.0 for r in rows)
    assert rows[0].timer_s == pytest.approx(1000 / 3)
    assert rows[0].pace_s_km == pytest.approx(1000 / 3)
    assert rows[1].start_offset_s == pytest.approx(1000 / 3)
    assert rows[0].hr_avg == 150 and rows[0].hr_median == 150


def test_remainder_from_100m_is_partial() -> None:
    rows = _constant_run(8370.0)
    assert len(rows) == 9
    assert rows[-1].is_partial
    assert rows[-1].distance_m == pytest.approx(370.0)
    assert rows[-1].pace_s_km == pytest.approx(1000 / 3)
    assert not any(r.is_partial for r in rows[:-1])


def test_split_time_interpolated_between_samples() -> None:
    prep = prepare(
        _stream([0, 10, 20, 30], distance_m=[0.0, 900.0, 1100.0, 1150.0]),
        sport_profile="running",
        events=[],
    )
    rows = distance_splits(prep, sport_profile="running", lengths=[])
    assert rows[0].timer_s == pytest.approx(15.0)
    assert rows[1].is_partial is True
    assert rows[1].start_offset_s == pytest.approx(15.0)
    assert rows[1].timer_s == pytest.approx(15.0)


def test_pause_inside_km_not_counted() -> None:
    t = list(range(261))
    dist = [5.0 * min(i, 100) + 5.0 * max(0, i - 160) for i in t]
    prep = prepare(
        _stream(t, distance_m=dist),
        sport_profile="running",
        events=[_timer("start", 0), _timer("stop_all", 100), _timer("start", 160)],
    )
    rows = distance_splits(prep, sport_profile="running", lengths=[])
    assert len(rows) == 1
    assert rows[0].timer_s == pytest.approx(200.0)
    assert rows[0].pace_s_km == pytest.approx(200.0)


def test_unrecognised_gap_marks_split_partial() -> None:
    t = [*range(0, 100), *range(130, 400)]
    prep = prepare(_stream(t, distance_m=[3.0 * x for x in t]), sport_profile="running", events=[])
    rows = distance_splits(prep, sport_profile="running", lengths=[])
    assert rows[0].quality == "partial"
    assert rows[1].quality == "ok"


def test_cycling_5km_splits_with_partial() -> None:
    rows = _constant_run(23000.0, speed=8.0, profile="cycling")
    assert [r.unit_m for r in rows] == [5000.0] * 5
    assert [r.is_partial for r in rows] == [False] * 4 + [True]
    assert rows[-1].distance_m == pytest.approx(3000.0)
    assert rows[0].speed_kmh == pytest.approx(28.8)


def test_cycling_remainder_below_1km_dropped() -> None:
    assert len(_constant_run(20900.0, speed=8.0, profile="cycling")) == 4


def test_generic_has_no_distance_splits() -> None:
    assert _constant_run(5000.0, profile="generic") == []


def _length(start_s: float, secs: float, strokes: int, kind: str = "active") -> dict[str, object]:
    return {
        "start_time": START + timedelta(seconds=start_s),
        "total_elapsed_time": secs,
        "total_timer_time": secs,
        "total_strokes": strokes,
        "length_type": kind,
    }


def test_swim_100m_splits_from_lengths() -> None:
    lengths = [
        _length(0, 40, 20),
        _length(40, 40, 20),
        _length(80, 30, 0, kind="idle"),
        _length(110, 40, 20),
        _length(150, 40, 20),
        _length(190, 40, 20),
    ]
    prep = prepare(_stream(list(range(231)), hr=[120.0] * 231), sport_profile="swimming", events=[])
    rows = distance_splits(
        prep, sport_profile="swimming", lengths=lengths, pool_length_m=50.0, start_at=START
    )
    assert [r.distance_m for r in rows] == [100.0, 100.0, 50.0]
    assert [r.is_partial for r in rows] == [False, False, True]
    assert rows[0].timer_s == pytest.approx(80.0)
    assert rows[0].pace_s_100m == pytest.approx(80.0)
    assert rows[0].swim_lengths == 2
    assert rows[0].swolf == pytest.approx(60.0)
    assert rows[1].start_offset_s == pytest.approx(110.0)
    assert all(r.quality == "partial" for r in rows)


def test_swim_without_lengths_has_no_distance_splits() -> None:
    prep = prepare(_stream([0, 1, 2], hr=[120.0] * 3), sport_profile="swimming", events=[])
    assert distance_splits(prep, sport_profile="swimming", lengths=[], start_at=START) == []


def test_lap_splits_from_arrays() -> None:
    t = list(range(301))
    dist = [3.0 * i if i <= 200 else 600.0 + 2.0 * (i - 200) for i in t]
    prep = prepare(
        _stream(t, distance_m=dist, speed_mps=[9.9] * 301, hr=[140.0] * 301),
        sport_profile="running",
        events=[],
    )
    laps = [
        {
            "start_time": START,
            "total_elapsed_time": 200.0,
            "total_timer_time": 200.0,
            "intensity": "active",
            "lap_trigger": "time",
            "wkt_step_index": 1,
        },
        {
            "start_time": START + timedelta(seconds=200),
            "total_elapsed_time": 100.0,
            "total_timer_time": 100.0,
            "intensity": "recovery",
            "lap_trigger": "manual",
            "wkt_step_index": 2,
        },
    ]
    rows = lap_splits(prep, laps=laps, start_at=START)
    assert [r.kind for r in rows] == ["lap", "lap"]
    assert [r.idx for r in rows] == [1, 2]
    assert rows[0].distance_m == pytest.approx(600.0)
    assert rows[0].timer_s == pytest.approx(200.0)
    assert rows[0].pace_s_km == pytest.approx(1000 / 3)
    assert rows[1].start_offset_s == pytest.approx(200.0)
    assert rows[1].distance_m == pytest.approx(200.0)
    assert (rows[1].lap_intensity, rows[1].lap_trigger, rows[1].wkt_step_index) == (
        "recovery",
        "manual",
        2,
    )
    assert rows[0].unit_m is None and rows[0].hr_avg == 140


def _row(idx: int, pace: float, partial: bool = False) -> SplitRow:
    return SplitRow(kind="distance", idx=idx, pace_s_km=pace, is_partial=partial, quality="ok")


def test_pace_cv_and_extremes_ignore_partial() -> None:
    rows = [_row(1, 300.0), _row(2, 310.0), _row(3, 290.0), _row(4, 400.0, partial=True)]
    assert pace_cv_pct(rows) == pytest.approx(100 * 8.16496580927726 / 300)
    extremes = fastest_and_slowest_split(rows)
    assert extremes is not None
    assert (extremes[0].idx, extremes[1].idx) == (3, 2)


def test_pace_cv_needs_two_full_splits() -> None:
    assert pace_cv_pct([_row(1, 300.0), _row(2, 400.0, partial=True)]) is None
    assert fastest_and_slowest_split([_row(1, 400.0, partial=True)]) is None


def test_v1_km_splits_match_auto_laps() -> None:
    fx = load_activity_fixture(AUTO_LAP_RUN)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages["event_mesgs"])
    splits = distance_splits(prep, sport_profile="running", lengths=[])
    laps = [
        lap
        for lap in fx.messages["lap_mesgs"]
        if lap["lap_trigger"] == "distance" and lap["total_distance"] == 1000.0
    ]
    assert len(splits) == len(laps) == 9
    diffs = [abs(s.timer_s - lap["total_timer_time"]) for s, lap in zip(splits, laps, strict=True)]
    assert sum(d <= 1.0 for d in diffs) / len(diffs) >= 0.95


def test_workout_fixture_lap_rows() -> None:
    fx = load_activity_fixture(WORKOUT_RUN)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages["event_mesgs"])
    laps = fx.messages["lap_mesgs"]
    rows = lap_splits(prep, laps=laps, start_at=fx.stream.start_at)
    assert len(rows) == 16
    assert [r.wkt_step_index for r in rows] == [lap.get("wkt_step_index") for lap in laps]
    assert [r.lap_intensity for r in rows] == [lap.get("intensity") for lap in laps]
    full = [(r, lap) for r, lap in zip(rows, laps, strict=True) if lap["total_timer_time"] > 10]
    assert all(abs(r.timer_s - lap["total_timer_time"]) <= 1.5 for r, lap in full)
    assert all(abs(r.distance_m - lap["total_distance"]) <= 15 for r, lap in full)


def test_swim_fixture_100m_splits() -> None:
    fx = load_activity_fixture(POOL_SWIM)
    prep = prepare(fx.stream, sport_profile="swimming", events=fx.messages["event_mesgs"])
    rows = distance_splits(
        prep,
        sport_profile="swimming",
        lengths=fx.messages["length_mesgs"],
        pool_length_m=fx.messages["session_mesgs"][0]["pool_length"],
        start_at=fx.stream.start_at,
    )
    assert len(rows) == 10
    assert sum(r.swim_lengths or 0 for r in rows) == 20
    assert not any(r.is_partial for r in rows)
    active = [ln for ln in fx.messages["length_mesgs"] if ln["length_type"] == "active"]
    assert sum(r.timer_s or 0 for r in rows) == pytest.approx(
        sum(ln["total_timer_time"] for ln in active)
    )
    # Garmin's fastestSplit_100 is a rolling window, aligned splits can only be slower
    fastest = fastest_and_slowest_split(rows)
    assert fastest is not None
    assert fastest[0].timer_s >= fx.list_item["fastestSplit_100"]
    swolf = sum((r.swolf or 0) * (r.swim_lengths or 0) for r in rows) / 20
    assert swolf == pytest.approx(fx.list_item["averageSwolf"], abs=1.0)
