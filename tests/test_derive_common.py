from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from kairos.activities.derive.common import (
    distance_source,
    elevation_gain_loss,
    interpolate_time_at_distance,
    max_speed_10s,
    pause_intervals,
    prepare,
    weighted_mean,
    weighted_median,
)
from kairos.activities.stream_repository import LoadedStream

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)


def _stream(t: list[int], **channels: list[float | None]) -> LoadedStream:
    return LoadedStream(start_at=START, t_offset_s=t, channels=channels, source="fit_zip")


def _timer(kind: str, offset_s: int) -> dict[str, object]:
    return {"event": "timer", "event_type": kind, "timestamp": START + timedelta(seconds=offset_s)}


def test_weight_capped_at_10s_for_gap() -> None:
    p = prepare(_stream([0, 1, 31, 32], hr=[100.0] * 4), sport_profile="running", events=[])
    assert p.weights[1] == 10.0
    assert p.weights[0] == 1.0


def test_event_pause_excluded_from_timer_time() -> None:
    t = list(range(0, 60)) + list(range(120, 180))
    events = [_timer("stop_all", 59), _timer("start", 120)]
    p = prepare(
        _stream(t, distance_m=[float(i) for i in range(len(t))]),
        sport_profile="running",
        events=events,
    )
    assert p.timer_t[-1] == pytest.approx(t[-1] - t[0] - 61)
    assert p.weights[59] == 0.0
    assert p.moving[59] is True


def test_legacy_pause_gap_without_distance() -> None:
    assert pause_intervals([0, 1, 21], [0.0, 1.0, 1.0], []) == [(1.0, 21.0)]


def test_legacy_gap_with_distance_is_no_pause() -> None:
    assert pause_intervals([0, 1, 21], [0.0, 1.0, 51.0], []) == []


def test_negative_distance_jump_clamped() -> None:
    p = prepare(
        _stream([0, 1, 2, 3], distance_m=[0.0, 10.0, 5.0, 15.0]), sport_profile="cycling", events=[]
    )
    assert p.distance == [0.0, 10.0, 10.0, 15.0]


def test_hr_out_of_range_ignored() -> None:
    p = prepare(_stream([0, 1, 2], hr=[240.0, 20.0, 150.0]), sport_profile="running", events=[])
    assert p.hr == [None, None, 150.0]
    assert p.hr_coverage_pct == pytest.approx(100 / 3)


def test_cadence_doubled_for_running_only() -> None:
    run = prepare(_stream([0], cadence=[85.0]), sport_profile="running", events=[])
    bike = prepare(_stream([0], cadence=[85.0]), sport_profile="cycling", events=[])
    assert run.cadence_spm_or_rpm == [170.0]
    assert bike.cadence_spm_or_rpm == [85.0]


def test_altitude_median_and_hysteresis() -> None:
    noise = [100.0, 101.0, 99.0, 101.0, 99.0, 100.0]
    assert elevation_gain_loss(noise) == (0.0, 0.0)
    assert elevation_gain_loss([100.0, 100.0, 105.0, 105.0]) == (5.0, 0.0)
    assert elevation_gain_loss([105.0, 100.0]) == (0.0, 5.0)
    p = prepare(
        _stream([0, 1, 2, 3, 4], altitude_m=[0.0, 0.0, 50.0, 0.0, 0.0]),
        sport_profile="running",
        events=[],
    )
    assert p.altitude_smooth == [0.0, 0.0, 0.0, 0.0, 0.0]


def test_gps_coverage() -> None:
    p = prepare(
        _stream([0, 1], lat_deg=[1.0, None], lng_deg=[1.0, None]),
        sport_profile="running",
        events=[],
    )
    assert p.gps_coverage_pct == 50.0


def test_weighted_stats() -> None:
    assert weighted_mean([1.0, 3.0, None], [1.0, 3.0, 5.0]) == pytest.approx(2.5)
    assert weighted_median([1.0, 2.0, 10.0], [1.0, 1.0, 5.0]) == 10.0
    assert weighted_mean([None], [1.0]) is None
    assert weighted_median([], []) is None


@pytest.mark.parametrize(
    ("profile", "sub", "gps", "has", "expected"),
    [
        ("running", "treadmill", 0.0, True, "watch_estimate"),
        ("swimming", "lap_swimming", 0.0, True, "pool"),
        ("running", "street", 95.0, True, "gps"),
        ("running", "street", 70.0, True, "mixed"),
        ("running", "street", 30.0, True, "watch_estimate"),
        ("running", None, 95.0, False, "none"),
    ],
)
def test_distance_source(
    profile: str, sub: str | None, gps: float, has: bool, expected: str
) -> None:
    assert (
        distance_source(
            sport_profile=profile, sub_sport=sub, gps_coverage_pct=gps, has_distance=has
        )
        == expected
    )


def test_interpolation_midpoint() -> None:
    assert interpolate_time_at_distance([0.0, 10.0], [0.0, 100.0], 50.0) == pytest.approx(5.0)
    assert interpolate_time_at_distance([0.0, 10.0], [0.0, 100.0], 200.0) is None


def test_max_speed_10s() -> None:
    t = [float(i) for i in range(30)]
    d = [float(i * 3 if i < 15 else 45 + (i - 15) * 5) for i in range(30)]
    assert max_speed_10s(t, d) == pytest.approx(5.0)
    assert max_speed_10s([0.0, 5.0], [0.0, 50.0]) is None


def test_distance_running_max_after_reset() -> None:
    p = prepare(
        _stream([0, 1, 2], distance_m=[1000.0, 0.0, 1001.0]), sport_profile="cycling", events=[]
    )
    assert p.distance == [1000.0, 1000.0, 1001.0]


def test_non_stop_timer_like_event_creates_no_pause() -> None:
    ev = [{"event": "hr_high_alert", "event_type": "stop", "timestamp": START}]
    assert pause_intervals([0, 1, 2], [0.0, 1.0, 2.0], ev, start_at=START) == []


def test_timer_events_disable_gap_fallback() -> None:
    ev = [_timer("start", 0)]
    assert pause_intervals([0, 1, 21], [0.0, 1.0, 1.0], ev, start_at=START) == []


def test_trailing_stop_without_start() -> None:
    t = list(range(10))
    p = prepare(
        _stream(t, distance_m=[float(i) for i in t]),
        sport_profile="running",
        events=[_timer("stop_all", 5)],
    )
    assert p.moving[5] is True
    assert p.moving[6:] == [False] * 4
    assert p.weights[-1] == 0.0
    assert p.timer_t[-1] == pytest.approx(5.0)


def test_moving_false_inside_pause() -> None:
    t = [0, 1, 2, 3, 4, 5]
    ev = [_timer("stop", 1), _timer("start", 4)]
    p = prepare(_stream(t), sport_profile="running", events=ev)
    assert p.moving == [True, True, False, False, True, True]
    assert p.weights[-1] == 1.0


def test_empty_stream() -> None:
    p = prepare(_stream([]), sport_profile="running", events=[])
    assert p.t == [] and p.weights == [] and p.timer_t == []
    assert p.gps_coverage_pct == 0.0 and p.hr_coverage_pct == 0.0


def test_interpolation_exact_sample_and_flat_segment() -> None:
    assert interpolate_time_at_distance([0.0, 5.0, 10.0], [0.0, 50.0, 100.0], 50.0) == 5.0
    assert interpolate_time_at_distance([0.0, 5.0, 10.0], [0.0, 50.0, 50.0], 50.0) == 5.0
    assert interpolate_time_at_distance([0.0, 5.0], [0.0, 50.0], 0.0) == 0.0
