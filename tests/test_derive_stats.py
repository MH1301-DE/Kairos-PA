from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from kairos.activities.derive.common import ACTIVITY_DERIVED_ALGO_VERSION, Prepared, prepare
from kairos.activities.derive.splits import SplitRow, distance_splits, lap_splits
from kairos.activities.derive.stats import (
    DECOUPLING_INTERVALS,
    DECOUPLING_NO_HR,
    DECOUPLING_NO_OUTPUT,
    DECOUPLING_SPARSE_HR,
    DECOUPLING_TOO_SHORT,
    ActivitySummary,
    CyclingMetrics,
    HikingMetrics,
    StatsRow,
    SwimmingMetrics,
    compute_stats,
)
from kairos.activities.stream_repository import LoadedStream
from kairos.db.models import ActivityStats
from tests.activity_fixtures import (
    AUTO_LAP_RUN,
    POOL_SWIM,
    TREADMILL_RUN,
    WORKOUT_RUN,
    ActivityFixture,
    load_activity_fixture,
)

START = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
SUMMARY_KEYS = (
    "sport_profile",
    "sport",
    "distance_m",
    "duration_s",
    "moving_duration_s",
    "avg_hr",
    "max_hr",
    "elevation_gain_m",
)


def _stream(t: list[int], **channels: list[float | None]) -> LoadedStream:
    return LoadedStream(start_at=START, t_offset_s=t, channels=channels, source="fit_zip")


def _summary(profile: str = "running", **kw: Any) -> ActivitySummary:
    return ActivitySummary(sport_profile=profile, **kw)


def _run(
    minutes: int,
    *,
    speed: float = 1000 / 300,
    hr: Any = None,
    profile: str = "running",
    hr_max: int | None = 190,
    **channels: list[float | None],
) -> StatsRow:
    n = minutes * 60 + 1
    hr_values = [hr(i) if callable(hr) else (140.0 if hr is None else hr) for i in range(n)]
    prep = prepare(
        _stream(
            list(range(n)),
            distance_m=[speed * i for i in range(n)],
            hr=hr_values,
            **channels,
        ),
        sport_profile=profile,
        events=[],
    )
    return _stats(prep, profile=profile, hr_max=hr_max)


def _stats(prep: Prepared, *, profile: str = "running", hr_max: int | None = 190) -> StatsRow:
    splits = distance_splits(prep, sport_profile=profile, lengths=[])
    return compute_stats(
        prep,
        activity=_summary(profile),
        sessions=[],
        lengths=[],
        splits=splits,
        hr_max=hr_max,
    )


def test_stats_row_matches_orm_columns() -> None:
    orm = set(ActivityStats.__table__.columns.keys()) - {"activity_id", "user_id", "computed_at"}
    assert set(StatsRow.__dataclass_fields__) == orm


def test_constant_run_has_zero_decoupling() -> None:
    row = _run(60)
    assert row.decoupling_pct == pytest.approx(0.0, abs=1e-6)
    assert row.decoupling_note is None
    assert row.avg_pace_s_km == pytest.approx(300.0, rel=1e-3)
    assert row.hr_avg == 140 and row.hr_median == 140 and row.hr_min == 140
    assert row.algo_version == ACTIVITY_DERIVED_ALGO_VERSION
    assert row.quality == "ok"
    assert row.sport_metrics == {}


def test_hr_drift_in_second_half_gives_positive_decoupling() -> None:
    # 10 min warm-up dropped, halves of 25 min each: second half starts at 35 min
    row = _run(60, hr=lambda i: 140.0 if i < 35 * 60 else 150.0)
    assert row.decoupling_pct == pytest.approx((1 - 140 / 150) * 100, abs=0.1)
    assert row.decoupling_note is None


def test_short_run_has_no_decoupling() -> None:
    row = _run(30)
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_TOO_SHORT == "zu kurz für Entkopplung (< 50 min)"


def test_run_without_hr_has_no_decoupling_and_no_zones() -> None:
    row = _run(60, hr=lambda _i: None)
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_NO_HR == "ohne HF nicht berechenbar"
    assert row.hr_avg is None and row.trimp_edwards is None
    assert row.hr_coverage_pct == 0.0


def test_interval_run_has_no_decoupling() -> None:
    n = 60 * 60 + 1
    dist, d = [], 0.0
    for i in range(n):
        dist.append(d)
        # alternating 4 km/h and 18 km/h blocks of 4 min
        d += 5.0 if (i // 240) % 2 else 1.1
    prep = prepare(
        _stream(list(range(n)), distance_m=dist, hr=[150.0] * n), sport_profile="running", events=[]
    )
    row = _stats(prep)
    assert row.pace_cv_pct is not None and row.pace_cv_pct > 8
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_INTERVALS == "Intervalltraining – nicht anwendbar"


def test_hr_average_is_time_weighted_with_uneven_spacing() -> None:
    # weights: 1, 1, 10 (capped gap), 1 (last sample)
    prep = prepare(
        _stream([0, 1, 2, 30], hr=[100.0, 100.0, 200.0, 200.0]),
        sport_profile="generic",
        events=[],
    )
    row = _stats(prep, profile="generic")
    assert row.hr_avg == round((100 + 100 + 2000 + 200) / 13)
    assert row.hr_median == 200
    assert row.hr_min == 100 and row.hr_max == 200


def test_zones_and_trimp_use_hr_max() -> None:
    # hr_max 190: 140 bpm ≈ 74 % → zone 3 (multiplier 3) for the full hour
    row = _run(60)
    assert row.hr_zone_s is not None
    assert row.hr_zone_s["z3"] == pytest.approx(3601.0)
    assert sum(row.hr_zone_s.values()) == pytest.approx(3601.0)
    assert set(row.hr_zone_s) == {"z1", "z2", "z3", "z4", "z5"}
    assert row.trimp_edwards == pytest.approx(3601.0 / 60 * 3)


def test_without_hr_max_no_zones_and_trimp() -> None:
    row = _run(60, hr_max=None)
    assert row.hr_zone_s is None and row.trimp_edwards is None
    assert row.hr_avg == 140


def test_without_stream_falls_back_to_summary() -> None:
    row = compute_stats(
        None,
        activity=_summary(
            "running",
            distance_m=10000.0,
            duration_s=3000.0,
            moving_duration_s=2950.0,
            avg_hr=150,
            max_hr=170,
            elevation_gain_m=55.0,
        ),
        sessions=[],
        lengths=[],
        splits=[],
        hr_max=190,
    )
    assert row.quality == "partial"
    assert row.distance_m == 10000.0 and row.timer_s == 3000.0 and row.moving_s == 2950.0
    assert row.avg_pace_s_km == pytest.approx(300.0)
    assert row.avg_moving_pace_s_km == pytest.approx(295.0)
    assert row.hr_avg == 150 and row.hr_max == 170 and row.elev_gain_m == 55.0
    assert row.hr_zone_s is None and row.trimp_edwards is None
    assert row.decoupling_pct is None and row.fastest_split_idx is None


def test_cycling_speed_and_normalized_power() -> None:
    row = _run(60, speed=8.0, profile="cycling", power_w=[200.0] * 3601)
    assert row.avg_speed_kmh == pytest.approx(28.8, rel=1e-3)
    assert row.max_speed_kmh == pytest.approx(28.8, rel=1e-3)
    assert row.avg_pace_s_km is None
    assert row.power_avg_w == pytest.approx(200.0) and row.power_max_w == 200.0
    metrics = CyclingMetrics.model_validate(row.sport_metrics)
    assert metrics.normalized_power_w == pytest.approx(200.0)
    assert metrics.avg_moving_speed_kmh == pytest.approx(28.8, rel=1e-3)
    assert row.decoupling_pct == pytest.approx(0.0, abs=1e-6)


def test_cycling_without_power_has_no_normalized_power() -> None:
    row = _run(60, speed=8.0, profile="cycling")
    assert "normalized_power_w" not in row.sport_metrics
    assert row.decoupling_pct == pytest.approx(0.0, abs=1e-6)


def test_hiking_ascent_rate_counts_only_steep_sections() -> None:
    # 1 m/s; first 30 min flat, then 30 min at 10 % grade
    n = 3601
    alt = [500.0 if i < 1800 else 500.0 + 0.1 * (i - 1800) for i in range(n)]
    row = _run(60, speed=1.0, profile="hiking", altitude_m=alt)
    metrics = HikingMetrics.model_validate(row.sport_metrics)
    assert metrics.ascent_rate_m_h == pytest.approx(360.0, rel=0.05)
    assert metrics.descent_rate_m_h is None
    assert row.elev_gain_m == pytest.approx(180.0, abs=2.0)
    assert row.alt_min_m == 500.0 and row.alt_max_m == pytest.approx(680.0, abs=0.2)
    assert row.decoupling_pct is None and row.decoupling_note is None


def test_sport_metrics_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        SwimmingMetrics.model_validate({"pool_length_m": 25.0, "foo": 1})


def _fixture_stats(name: str, *, hr_max: int | None = 190) -> tuple[StatsRow, ActivityFixture]:
    fx = load_activity_fixture(name)
    profile = fx.summary["sport_profile"]
    msgs = fx.messages
    prep = prepare(fx.stream, sport_profile=profile, events=msgs["event_mesgs"])
    session = msgs["session_mesgs"][0]
    splits = distance_splits(
        prep,
        sport_profile=profile,
        lengths=msgs["length_mesgs"],
        pool_length_m=session.get("pool_length"),
        start_at=fx.stream.start_at,
    ) + lap_splits(prep, sport_profile=profile, laps=msgs["lap_mesgs"], start_at=fx.stream.start_at)
    row = compute_stats(
        prep,
        activity=ActivitySummary(**{k: fx.summary[k] for k in SUMMARY_KEYS}),
        sessions=msgs["session_mesgs"],
        lengths=msgs["length_mesgs"],
        splits=splits,
        hr_max=hr_max,
    )
    return row, fx


@pytest.mark.parametrize("name", [AUTO_LAP_RUN, WORKOUT_RUN, TREADMILL_RUN])
def test_fixture_runs_match_garmin_hr_and_cadence(name: str) -> None:
    row, fx = _fixture_stats(name)
    # V6 and V5 (spec §12.3)
    assert row.hr_avg is not None and abs(row.hr_avg - fx.summary["avg_hr"]) <= 1
    garmin_cadence = fx.list_item["averageRunningCadenceInStepsPerMinute"]
    assert row.cadence_avg is not None and abs(row.cadence_avg - garmin_cadence) <= 2
    assert row.timer_s == pytest.approx(fx.list_item["duration"], abs=1.0)
    assert row.elapsed_s == pytest.approx(fx.list_item["elapsedDuration"], abs=1.0)
    assert row.moving_s == pytest.approx(fx.list_item["movingDuration"], abs=0.01)
    assert row.quality == "ok"


@pytest.mark.parametrize(("name", "gain"), [(AUTO_LAP_RUN, 42.2), (WORKOUT_RUN, 34.0)])
def test_fixture_elevation_gain_near_garmin(name: str, gain: float) -> None:
    # V4 (spec §12.3): Garmin 40 m and 35 m; the 2 m step rule gave 28.2 m and 24.0 m
    row, fx = _fixture_stats(name)
    assert row.elev_gain_m == pytest.approx(gain, abs=0.5)
    garmin = fx.list_item["elevationGain"]
    assert abs(row.elev_gain_m - garmin) <= 0.1 * garmin


def test_fixture_steady_run_has_decoupling() -> None:
    row, fx = _fixture_stats(AUTO_LAP_RUN)
    assert row.decoupling_pct is not None and row.decoupling_note is None
    assert row.distance_source == "gps"
    assert row.distance_m == pytest.approx(fx.list_item["distance"])
    assert row.fastest_split_idx == 9 and row.slowest_split_idx == 2
    assert row.power_avg_w == pytest.approx(fx.list_item["avgPower"], abs=2)


def test_fixture_workout_run_is_intervals() -> None:
    row, _ = _fixture_stats(WORKOUT_RUN)
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_INTERVALS


def test_fixture_treadmill_reports_session_distance() -> None:
    row, fx = _fixture_stats(TREADMILL_RUN)
    assert row.distance_source == "watch_estimate"
    # calibrated session distance, not the uncalibrated stream (≈ 5.3 km)
    assert row.distance_m == pytest.approx(7300.0)
    assert row.avg_pace_s_km == pytest.approx(fx.list_item["duration"] / 7.3, abs=0.5)
    assert row.decoupling_note == DECOUPLING_TOO_SHORT
    assert row.elev_gain_m is None and row.alt_min_m is None


def test_fixture_swim_is_partial_with_pool_metrics() -> None:
    row, fx = _fixture_stats(POOL_SWIM)
    assert row.quality == "partial"
    assert row.distance_source == "pool"
    assert row.distance_m == pytest.approx(1000.0)
    assert row.hr_avg is not None and abs(row.hr_avg - fx.summary["avg_hr"]) <= 1
    metrics = SwimmingMetrics.model_validate(row.sport_metrics)
    assert metrics.pool_length_m == 50.0
    assert metrics.active_lengths == fx.list_item["activeLengths"]
    assert metrics.avg_swolf is not None
    assert abs(metrics.avg_swolf - fx.list_item["averageSwolf"]) <= 1
    assert metrics.avg_strokes_per_length == pytest.approx(fx.list_item["avgStrokes"], abs=0.5)
    assert metrics.rest_s == pytest.approx(354.776, abs=0.01)
    assert row.avg_pace_s_100m == pytest.approx(fx.list_item["movingDuration"] / 10, abs=0.1)
    assert row.avg_pace_s_km is None and row.cadence_avg is None
    assert row.decoupling_pct is None and row.decoupling_note is None


def test_split_extremes_use_full_distance_splits_only() -> None:
    def split(idx: int, pace: float, partial: bool = False) -> SplitRow:
        return SplitRow(
            kind="distance", idx=idx, pace_s_km=pace, pace_s_100m=pace / 10, is_partial=partial
        )

    prep = prepare(_stream([0, 1], hr=[120.0, 120.0]), sport_profile="running", events=[])
    row = compute_stats(
        prep,
        activity=_summary(),
        sessions=[],
        lengths=[],
        splits=[split(1, 310.0), split(2, 290.0), split(3, 250.0, partial=True)],
        hr_max=None,
    )
    assert (row.fastest_split_idx, row.fastest_split_pace_s) == (2, 290.0)
    assert (row.slowest_split_idx, row.slowest_split_pace_s) == (1, 310.0)
    assert row.pace_cv_pct == pytest.approx(10 / 300 * 100)
    assert math.isclose(row.gps_coverage_pct or 0.0, 0.0)


def test_run_without_distance_has_decoupling_reason() -> None:
    n = 3601
    prep = prepare(_stream(list(range(n)), hr=[140.0] * n), sport_profile="running", events=[])
    row = _stats(prep)
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_NO_OUTPUT == "ohne Distanz/Leistung nicht berechenbar"


def test_cycling_without_power_and_distance_has_decoupling_reason() -> None:
    n = 3601
    prep = prepare(_stream(list(range(n)), hr=[140.0] * n), sport_profile="cycling", events=[])
    row = _stats(prep, profile="cycling")
    assert row.decoupling_note == DECOUPLING_NO_OUTPUT


def test_half_without_hr_has_decoupling_reason() -> None:
    row = _run(60, hr=lambda i: 140.0 if i < 35 * 60 else None)
    assert row.decoupling_pct is None
    assert row.decoupling_note == DECOUPLING_SPARSE_HR == "zu wenig HF-Daten"


def test_cycling_power_drift_decoupling() -> None:
    # same HR, power drops 200 → 190 W in the second half: EF falls by 5 %
    power: list[float | None] = [200.0 if i < 35 * 60 else 190.0 for i in range(3601)]
    row = _run(60, speed=8.0, profile="cycling", power_w=power)
    assert row.decoupling_pct == pytest.approx(5.0, abs=0.01)


def test_normalized_power_with_alternating_blocks() -> None:
    # 30 s blocks 100/300 W at 1 Hz: the 30-s mean holds k of 30 samples at 300 W,
    # k runs 1..30, 29..0 over each 60-s period
    power: list[float | None] = [300.0 if (i // 30) % 2 else 100.0 for i in range(3601)]
    row = _run(60, speed=8.0, profile="cycling", power_w=power)
    ks = list(range(1, 31)) + list(range(29, -1, -1))
    expected = statistics.fmean((100 + 200 * k / 30) ** 4 for k in ks) ** 0.25
    metrics = CyclingMetrics.model_validate(row.sport_metrics)
    # close to a uniform 100–300 W ramp: ((300^5 - 100^5) / (5 * 200)) ** 0.25 = 221.8 W
    assert expected == pytest.approx(((300**5 - 100**5) / 1000) ** 0.25, abs=0.5)
    assert metrics.normalized_power_w == pytest.approx(expected, rel=1e-3)
    assert row.power_avg_w == pytest.approx(200.0, abs=0.1)


@pytest.mark.parametrize(
    ("profile", "sport", "distance", "expected"),
    [
        ("running", "treadmill_running", 7300.0, "watch_estimate"),
        ("running", "running", 10000.0, "mixed"),
        ("swimming", "lap_swimming", 1000.0, "pool"),
        ("generic", "strength_training", None, "none"),
    ],
)
def test_summary_fallback_distance_source(
    profile: str, sport: str, distance: float | None, expected: str
) -> None:
    row = compute_stats(
        None,
        activity=_summary(profile, sport=sport, distance_m=distance, duration_s=1800.0),
        sessions=[],
        lengths=[],
        splits=[],
        hr_max=None,
    )
    assert row.distance_source == expected
    assert row.quality == "partial"
