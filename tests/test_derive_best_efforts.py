from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from kairos.activities.derive.best_efforts import BEST_EFFORT_DISTANCES, best_efforts
from kairos.activities.derive.common import distance_source, prepare
from kairos.activities.stream_repository import LoadedStream
from tests.activity_fixtures import AUTO_LAP_RUN, TREADMILL_RUN, WORKOUT_RUN, load_activity_fixture

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def _prep(t: list[int], dist: list[float], events: list[dict[str, object]] | None = None):  # type: ignore[no-untyped-def]
    stream = LoadedStream(
        start_at=START, t_offset_s=t, channels={"distance_m": list(dist)}, source="fit_zip"
    )
    return prepare(stream, sport_profile="running", events=events or [])


def _run(speeds: list[float], per_s: int = 1):  # type: ignore[no-untyped-def]
    # speeds: one value per second segment
    dist = [0.0]
    for v in speeds:
        dist.append(dist[-1] + v)
    return _prep(list(range(len(dist))), dist)


def _by_key(prep) -> dict:  # type: ignore[no-untyped-def]
    rows = best_efforts(prep, sport_profile="running", distance_source="gps")
    return {r.distance_key: r for r in rows}


def test_distance_table() -> None:
    assert list(BEST_EFFORT_DISTANCES) == [
        "800m", "1500m", "3000m", "5k", "10k", "hm", "m", "50k", "100k",
    ]  # fmt: skip
    assert BEST_EFFORT_DISTANCES["hm"] == 21097.5


def test_constant_pace_5k() -> None:
    rows = _by_key(_run([1000 / 240] * 1440))
    assert rows["5k"].duration_s == pytest.approx(1200.0, abs=0.01)
    assert rows["5k"].distance_m == 5000.0
    assert rows["800m"].duration_s == pytest.approx(192.0, abs=0.01)
    assert set(rows) == {"800m", "1500m", "3000m", "5k"}
    assert rows["5k"].quality == "ok"


def test_fast_section_located() -> None:
    speeds = [1000 / 240] * 1440
    for i in range(480, 690):
        speeds[i] = 1000 / 210
    rows = _by_key(_run(speeds))
    assert rows["800m"].duration_s == pytest.approx(168.0, abs=0.01)
    assert 2.0 <= rows["800m"].start_km <= 3.0
    assert rows["1500m"].duration_s == pytest.approx(330.0, abs=0.01)
    assert rows["1500m"].start_km == pytest.approx(rows["1500m"].start_offset_s / 240, abs=0.01)
    assert 360 - 1e-6 <= rows["1500m"].start_offset_s <= 480 + 1e-6


def test_gps_jump_discards_windows() -> None:
    speeds = [3.0] * 1500
    speeds[600] = 50.0
    rows = _by_key(_run(speeds))
    start_m = rows["800m"].start_km * 1000
    assert start_m + 800 <= 600 * 3.0 + 1e-6 or start_m >= 600 * 3.0 + 50.0 - 1e-6
    assert rows["800m"].duration_s == pytest.approx(800 / 3.0, abs=0.01)


def test_real_sprint_steps_are_not_treated_as_jumps() -> None:
    # V2 decision 2026-10-17: 8.5 m/s threw away sprint workouts and GPS jitter
    speeds = [3.0] * 2000
    for i in range(600, 604):
        speeds[i] = 9.0
    rows = _by_key(_run(speeds))
    # the fastest 800 m contains the sprint; under the old filter it had to avoid it
    start_m = rows["800m"].start_km * 1000
    assert start_m <= 600 * 3.0 <= start_m + 800


def test_jump_in_short_run_yields_no_row() -> None:
    prep = _run([5.0] * 100 + [60.0] + [5.0] * 100)
    rows = _by_key(prep)
    assert "800m" not in rows


def test_unrecognised_gap_marks_partial() -> None:
    t = list(range(0, 300)) + list(range(320, 700))
    rows = _by_key(_prep(t, [3.0 * x for x in t]))
    assert rows["1500m"].quality == "partial"


def test_recognised_pause_is_not_partial() -> None:
    t = list(range(0, 300)) + list(range(330, 800))
    dist = [3.0 * min(x, 300) for x in t]
    dist = [d if x < 330 else 900.0 + 3.0 * (x - 330) for x, d in zip(t, dist, strict=True)]
    events = [
        {"event": "timer", "event_type": "stop_all", "timestamp": START + timedelta(seconds=299)},
        {"event": "timer", "event_type": "start", "timestamp": START + timedelta(seconds=330)},
    ]
    rows = _by_key(_prep(t, dist, events))
    assert rows["1500m"].quality == "ok"


def test_short_run_has_no_5k() -> None:
    rows = _by_key(_run([3.0] * 1633))
    assert "5k" not in rows
    assert "3000m" in rows


def test_not_running_or_not_gps_gives_nothing() -> None:
    prep = _run([3.0] * 1500)
    assert best_efforts(prep, sport_profile="cycling", distance_source="gps") == []
    assert best_efforts(prep, sport_profile="running", distance_source="watch_estimate") == []


def test_treadmill_fixture_has_no_rows() -> None:
    fx = load_activity_fixture(TREADMILL_RUN)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages["event_mesgs"])
    src = distance_source(
        sport_profile="running",
        sub_sport=fx.messages["sport_mesgs"][0].get("sub_sport")
        if fx.messages.get("sport_mesgs")
        else None,
        gps_coverage_pct=prep.gps_coverage_pct,
        has_distance=any(d is not None for d in prep.distance),
    )
    assert src == "watch_estimate"
    assert best_efforts(prep, sport_profile="running", distance_source=src) == []


def test_hr_average() -> None:
    n = 1000
    stream = LoadedStream(
        start_at=START,
        t_offset_s=list(range(n)),
        channels={"distance_m": [3.0 * i for i in range(n)], "hr": [150.0] * n},
        source="fit_zip",
    )
    prep = prepare(stream, sport_profile="running", events=[])
    row = best_efforts(prep, sport_profile="running", distance_source="gps")[0]
    assert row.hr_avg == 150


def _brute_force(t: list[float], d: list[float], target: float) -> float:
    def at(x: float) -> float | None:
        for k in range(1, len(d)):
            if d[k - 1] <= x <= d[k] and d[k] > d[k - 1]:
                return t[k - 1] + (t[k] - t[k - 1]) * (x - d[k - 1]) / (d[k] - d[k - 1])
        return None

    cands = [(x, x + target) for x in d] + [(x - target, x) for x in d]
    best = float("inf")
    for a, b in cands:
        ta, tb = at(a), at(b)
        if ta is not None and tb is not None:
            best = min(best, tb - ta)
    return best


def test_matches_brute_force_on_irregular_profile() -> None:
    import random

    rng = random.Random(7)
    dist = [0.0]
    for _ in range(900):
        dist.append(dist[-1] + rng.uniform(1.5, 6.5))
    t = list(range(len(dist)))
    rows = _by_key(_prep(t, dist))
    for key in ("800m", "1500m"):
        expected = _brute_force([float(x) for x in t], dist, BEST_EFFORT_DISTANCES[key])
        assert rows[key].duration_s == pytest.approx(expected, abs=1e-6)


def test_v2_5k_against_garmin_fastest_split() -> None:
    fx = load_activity_fixture(AUTO_LAP_RUN)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages["event_mesgs"])
    ref = fx.list_item["fastestSplit_5000"]
    assert abs(_by_key(prep)["5k"].duration_s - ref) <= max(2.0, 0.01 * ref)


def test_v2_workout_matches_garmin_on_elapsed_time() -> None:
    # Garmin's fastestSplit counts elapsed time; Kairos uses timer time, so pauses inside differ
    fx = load_activity_fixture(WORKOUT_RUN)
    prep = prepare(fx.stream, sport_profile="running", events=fx.messages["event_mesgs"])
    elapsed = _by_key(replace(prep, timer_t=list(prep.t)))
    for key, garmin in (("5k", "fastestSplit_5000"), ("10k", "fastestSplit_10000")):
        ref = fx.list_item[garmin]
        assert abs(elapsed[key].duration_s - ref) <= max(2.0, 0.01 * ref)
        assert _by_key(prep)[key].duration_s < elapsed[key].duration_s
