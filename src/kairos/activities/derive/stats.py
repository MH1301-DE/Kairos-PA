from __future__ import annotations

import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from pydantic import BaseModel, ConfigDict

from kairos.activities.derive.common import (
    ACTIVITY_DERIVED_ALGO_VERSION,
    PAUSE_MAX_SPEED_MPS,
    Prepared,
    distance_source,
    elevation_gain_loss,
    interp,
    max_speed_10s,
    weighted_mean,
    weighted_median,
)
from kairos.activities.derive.splits import (
    SplitRow,
    fastest_and_slowest_split,
    pace_cv_pct,
)
from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import percent_max_zones, zone_seconds

DECOUPLING_INTERVALS = "Intervalltraining – nicht anwendbar"
DECOUPLING_TOO_SHORT = "zu kurz für Entkopplung (< 50 min)"
DECOUPLING_NO_HR = "ohne HF nicht berechenbar"
DECOUPLING_NO_OUTPUT = "ohne Distanz/Leistung nicht berechenbar"
DECOUPLING_SPARSE_HR = "zu wenig HF-Daten"
DECOUPLING_WARMUP_S = 600.0
DECOUPLING_MIN_REST_S = 2400.0
DECOUPLING_MAX_CV_PCT = 8.0
HR_BUCKET_BPM = 5
NP_WINDOW_S = 30.0
HIKING_SECTION_M = 100.0
HIKING_MIN_GRADE = 0.03
_PACE_PROFILES = frozenset({"running", "hiking"})
_DECOUPLING_PROFILES = frozenset({"running", "cycling"})
# Garmin typeKey (activity.sport) → FIT sub_sport, for the summary fallback
_SUB_SPORT_BY_SPORT = {
    "treadmill_running": "treadmill",
    "indoor_running": "indoor_running",
    "indoor_cycling": "indoor_cycling",
    "virtual_ride": "virtual_activity",
    "virtual_run": "virtual_activity",
    "indoor_walking": "indoor_walking",
    "lap_swimming": "lap_swimming",
}


@dataclass(frozen=True, kw_only=True)
class ActivitySummary:
    sport_profile: str
    sport: str | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    moving_duration_s: float | None = None
    avg_hr: int | None = None
    max_hr: int | None = None
    elevation_gain_m: float | None = None


class _SportMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CyclingMetrics(_SportMetrics):
    avg_moving_speed_kmh: float | None = None
    normalized_power_w: float | None = None


class SwimmingMetrics(_SportMetrics):
    pool_length_m: float | None = None
    active_lengths: int | None = None
    avg_swolf: float | None = None
    avg_strokes_per_length: float | None = None
    rest_s: float | None = None


class HikingMetrics(_SportMetrics):
    ascent_rate_m_h: float | None = None
    descent_rate_m_h: float | None = None


@dataclass(frozen=True, kw_only=True)
class StatsRow:
    sport_profile: str
    algo_version: int = ACTIVITY_DERIVED_ALGO_VERSION
    distance_m: float | None = None
    elapsed_s: float | None = None
    timer_s: float | None = None
    moving_s: float | None = None
    avg_pace_s_km: float | None = None
    avg_moving_pace_s_km: float | None = None
    avg_speed_kmh: float | None = None
    max_speed_kmh: float | None = None
    avg_pace_s_100m: float | None = None
    hr_avg: int | None = None
    hr_median: int | None = None
    hr_min: int | None = None
    hr_max: int | None = None
    hr_zone_s: dict[str, float] | None = None
    trimp_edwards: float | None = None
    elev_gain_m: float | None = None
    elev_loss_m: float | None = None
    alt_min_m: float | None = None
    alt_max_m: float | None = None
    cadence_avg: float | None = None
    power_avg_w: float | None = None
    power_max_w: float | None = None
    fastest_split_idx: int | None = None
    fastest_split_pace_s: float | None = None
    slowest_split_idx: int | None = None
    slowest_split_pace_s: float | None = None
    pace_cv_pct: float | None = None
    decoupling_pct: float | None = None
    decoupling_note: str | None = None
    distance_source: str | None = None
    hr_coverage_pct: float | None = None
    gps_coverage_pct: float | None = None
    quality: str = "ok"
    sport_metrics: dict[str, Any] = field(default_factory=dict)


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _session_sum(sessions: Sequence[Mapping[str, object]], key: str) -> float | None:
    values = [v for v in (_num(s.get(key)) for s in sessions) if v is not None]
    return sum(values) if values else None


def _round(value: float | None) -> int | None:
    return None if value is None else round(value)


def _paces(
    profile: str, distance: float | None, timer: float | None, moving: float | None
) -> tuple[float | None, float | None, float | None, float | None]:
    def per(seconds: float | None, unit_m: float) -> float | None:
        return seconds / distance * unit_m if distance and seconds else None

    if profile in _PACE_PROFILES:
        return per(timer, 1000), per(moving, 1000), None, None
    if profile == "cycling":
        return None, None, distance / timer * 3.6 if distance and timer else None, None
    if profile == "swimming":
        # rest between lengths runs on the timer, so pace uses the active time like Garmin
        return None, None, None, per(moving, 100)
    return None, None, None, None


def _with_paces(row: StatsRow) -> StatsRow:
    pace, moving_pace, speed, pace_100m = _paces(
        row.sport_profile, row.distance_m, row.timer_s, row.moving_s
    )
    return replace(
        row,
        avg_pace_s_km=pace,
        avg_moving_pace_s_km=moving_pace,
        avg_speed_kmh=speed,
        avg_pace_s_100m=pace_100m,
    )


def _summary_distance_source(activity: ActivitySummary) -> str:
    if not activity.distance_m:
        return "none"
    # unknown GPS coverage: 50 % sits between both thresholds, so outdoor maps to "mixed"
    return distance_source(
        sport_profile=activity.sport_profile,
        sub_sport=_SUB_SPORT_BY_SPORT.get(activity.sport or ""),
        gps_coverage_pct=50.0,
        has_distance=True,
    )


def _from_summary(activity: ActivitySummary) -> StatsRow:
    distance = activity.distance_m
    row = StatsRow(
        sport_profile=activity.sport_profile,
        distance_m=distance,
        timer_s=activity.duration_s,
        moving_s=activity.moving_duration_s,
        hr_avg=activity.avg_hr,
        hr_max=activity.max_hr,
        elev_gain_m=activity.elevation_gain_m,
        distance_source=_summary_distance_source(activity),
        quality="partial",
    )
    return _with_paces(row)


def _moving_seconds(prep: Prepared) -> float:
    if all(d is None for d in prep.distance):
        return sum(prep.weights)
    total = 0.0
    for i in range(len(prep.t) - 1):
        d0, d1 = prep.distance[i], prep.distance[i + 1]
        dt = prep.t[i + 1] - prep.t[i]
        if d0 is not None and d1 is not None and dt > 0 and (d1 - d0) / dt >= PAUSE_MAX_SPEED_MPS:
            total += prep.weights[i]
    return total


def _hr_buckets(prep: Prepared) -> dict[int, float]:
    out: dict[int, float] = {}
    for v, w in zip(prep.hr, prep.weights, strict=True):
        if v is None or w <= 0:
            continue
        key = int(v // HR_BUCKET_BPM * HR_BUCKET_BPM)
        out[key] = out.get(key, 0.0) + w
    return out


def efficiency(
    prep: Prepared, a: float, b: float, *, use_power: bool
) -> tuple[float | None, str | None]:
    idx = [i for i, tt in enumerate(prep.timer_t) if a <= tt < b and prep.weights[i] > 0]
    weights = [prep.weights[i] for i in idx]
    hr = weighted_mean([prep.hr[i] for i in idx], weights)
    if use_power:
        output = weighted_mean([prep.power[i] for i in idx], weights)
    else:
        da, db = interp(prep.timer_t, prep.distance, a), interp(prep.timer_t, prep.distance, b)
        output = None if da is None or db is None or b <= a else (db - da) / (b - a)
    if not output:
        return None, DECOUPLING_NO_OUTPUT
    if not hr:
        return None, DECOUPLING_SPARSE_HR
    return output / hr, None


def decoupling(
    prep: Prepared, profile: str, cv_pct: float | None
) -> tuple[float | None, str | None]:
    if profile not in _DECOUPLING_PROFILES:
        return None, None
    if all(v is None for v in prep.hr):
        return None, DECOUPLING_NO_HR
    end = prep.timer_t[-1]
    if end - DECOUPLING_WARMUP_S < DECOUPLING_MIN_REST_S:
        return None, DECOUPLING_TOO_SHORT
    if cv_pct is not None and cv_pct > DECOUPLING_MAX_CV_PCT:
        return None, DECOUPLING_INTERVALS
    use_power = profile == "cycling" and any(p is not None for p in prep.power)
    mid = DECOUPLING_WARMUP_S + (end - DECOUPLING_WARMUP_S) / 2
    ef1, note1 = efficiency(prep, DECOUPLING_WARMUP_S, mid, use_power=use_power)
    ef2, note2 = efficiency(prep, mid, end, use_power=use_power)
    if ef1 is None or ef2 is None:
        return None, note1 or note2
    return (ef1 - ef2) / ef1 * 100, None


def _normalized_power(prep: Prepared) -> float | None:
    pts = [
        (tt, p, w)
        for tt, p, w in zip(prep.timer_t, prep.power, prep.weights, strict=True)
        if p is not None and w > 0
    ]
    if not pts:
        return None
    left = 0
    sum_pw = sum_w = 0.0
    fourth = weight = 0.0
    for tt, p, w in pts:
        sum_pw += p * w
        sum_w += w
        while pts[left][0] <= tt - NP_WINDOW_S:
            sum_pw -= pts[left][1] * pts[left][2]
            sum_w -= pts[left][2]
            left += 1
        if tt - pts[0][0] >= NP_WINDOW_S and sum_w > 0:
            fourth += (sum_pw / sum_w) ** 4 * w
            weight += w
    return float((fourth / weight) ** 0.25) if weight > 0 else None


def _hiking_rates(prep: Prepared) -> tuple[float | None, float | None]:
    pts = [
        (tt, d, a)
        for tt, d, a in zip(prep.timer_t, prep.distance, prep.altitude_smooth, strict=True)
        if d is not None and a is not None
    ]
    up_m = up_s = down_m = down_s = 0.0
    if pts:
        t0, d0, a0 = pts[0]
        for tt, d, a in pts[1:]:
            if d - d0 < HIKING_SECTION_M:
                continue
            grade = (a - a0) / (d - d0)
            if grade > HIKING_MIN_GRADE:
                up_m, up_s = up_m + a - a0, up_s + tt - t0
            elif grade < -HIKING_MIN_GRADE:
                down_m, down_s = down_m + a0 - a, down_s + tt - t0
            t0, d0, a0 = tt, d, a
    return (
        up_m / up_s * 3600 if up_s > 0 else None,
        down_m / down_s * 3600 if down_s > 0 else None,
    )


def _swim_metrics(
    sessions: Sequence[Mapping[str, object]], lengths: Sequence[Mapping[str, object]]
) -> SwimmingMetrics:
    first = sessions[0] if sessions else {}
    active = [ln for ln in lengths if ln.get("length_type") == "active"]
    strokes = [s for s in (_num(ln.get("total_strokes")) for ln in active) if s is not None]
    swolf = [
        t + s
        for t, s in (
            (_num(ln.get("total_timer_time")), _num(ln.get("total_strokes"))) for ln in active
        )
        if t is not None and s is not None
    ]
    idle = [
        _num(ln.get("total_timer_time")) or 0.0
        for ln in lengths
        if ln.get("length_type") != "active"
    ]
    count = _num(first.get("num_active_lengths"))
    return SwimmingMetrics(
        pool_length_m=_num(first.get("pool_length")),
        active_lengths=len(active) if lengths else (None if count is None else int(count)),
        avg_swolf=statistics.fmean(swolf) if swolf else None,
        avg_strokes_per_length=statistics.fmean(strokes) if strokes else None,
        rest_s=sum(idle) if lengths else None,
    )


def _sport_metrics(
    prep: Prepared,
    profile: str,
    *,
    distance: float | None,
    moving: float | None,
    sessions: Sequence[Mapping[str, object]],
    lengths: Sequence[Mapping[str, object]],
) -> dict[str, Any]:
    model: _SportMetrics
    if profile == "cycling":
        model = CyclingMetrics(
            avg_moving_speed_kmh=distance / moving * 3.6 if distance and moving else None,
            normalized_power_w=_normalized_power(prep),
        )
    elif profile == "swimming":
        model = _swim_metrics(sessions, lengths)
    elif profile == "hiking":
        ascent, descent = _hiking_rates(prep)
        model = HikingMetrics(ascent_rate_m_h=ascent, descent_rate_m_h=descent)
    else:
        return {}
    return model.model_dump(exclude_none=True)


def compute_stats(
    prep: Prepared | None,
    *,
    activity: ActivitySummary,
    sessions: Sequence[Mapping[str, object]],
    lengths: Sequence[Mapping[str, object]],
    splits: Sequence[SplitRow],
    hr_max: int | None,
) -> StatsRow:
    if prep is None or not prep.t:
        return _from_summary(activity)
    profile = activity.sport_profile
    w = prep.weights
    stream_distance = max((d for d in prep.distance if d is not None), default=None)
    # the session total carries Garmin's calibration (treadmill), the records do not
    distance = _session_sum(sessions, "total_distance") or stream_distance or activity.distance_m
    timer = _session_sum(sessions, "total_timer_time") or prep.timer_t[-1]
    elapsed = _session_sum(sessions, "total_elapsed_time") or prep.t[-1] - prep.t[0]
    moving = activity.moving_duration_s or _moving_seconds(prep)

    hr_active = [v for v, wi in zip(prep.hr, w, strict=True) if v is not None and wi > 0]
    zone_s = trimp = None
    if hr_max is not None and hr_active:
        zones = percent_max_zones(hr_max)
        buckets = _hr_buckets(prep)
        by_name = zone_seconds(buckets, zones)
        zone_s = {f"z{i}": by_name[z.name] for i, z in enumerate(zones, start=1)}
        trimp = edwards_trimp(buckets, zones)

    alt = [v for v in prep.altitude_smooth if v is not None]
    gain, loss = elevation_gain_loss(prep.altitude_smooth) if alt else (None, None)
    # V4 decision 2026-10-17: the watch's barometric totals win; splits keep the own rule
    session0 = sessions[0] if sessions else {}
    watch_gain, watch_loss = _num(session0.get("total_ascent")), _num(session0.get("total_descent"))
    if watch_gain is not None:
        gain, loss = watch_gain, watch_loss if watch_loss is not None else loss
    power_active = [p for p, wi in zip(prep.power, w, strict=True) if p is not None and wi > 0]

    cv = pace_cv_pct(splits)
    extremes = fastest_and_slowest_split(splits)
    pace_key = "pace_s_100m" if profile == "swimming" else "pace_s_km"
    fastest, slowest = extremes if extremes else (None, None)
    decoupling_pct, note = decoupling(prep, profile, cv)
    max_speed = max_speed_10s(prep.timer_t, prep.distance) if profile == "cycling" else None
    first = sessions[0] if sessions else {}
    sub_sport = first.get("sub_sport")

    row = StatsRow(
        sport_profile=profile,
        distance_m=distance,
        elapsed_s=elapsed,
        timer_s=timer,
        moving_s=moving,
        max_speed_kmh=None if max_speed is None else max_speed * 3.6,
        hr_avg=_round(weighted_mean(prep.hr, w)),
        hr_median=_round(weighted_median(prep.hr, w)),
        hr_min=_round(min(hr_active)) if hr_active else None,
        hr_max=_round(max(hr_active)) if hr_active else None,
        hr_zone_s=zone_s,
        trimp_edwards=trimp,
        elev_gain_m=gain,
        elev_loss_m=loss,
        alt_min_m=min(alt) if alt else None,
        alt_max_m=max(alt) if alt else None,
        cadence_avg=weighted_mean(prep.cadence_spm_or_rpm, w),
        power_avg_w=weighted_mean(prep.power, w),
        power_max_w=max(power_active) if power_active else None,
        fastest_split_idx=None if fastest is None else fastest.idx,
        fastest_split_pace_s=None if fastest is None else getattr(fastest, pace_key),
        slowest_split_idx=None if slowest is None else slowest.idx,
        slowest_split_pace_s=None if slowest is None else getattr(slowest, pace_key),
        pace_cv_pct=cv,
        decoupling_pct=decoupling_pct,
        decoupling_note=note,
        distance_source=distance_source(
            sport_profile=profile,
            sub_sport=None if sub_sport is None else str(sub_sport),
            gps_coverage_pct=prep.gps_coverage_pct,
            has_distance=bool(distance),
        ),
        hr_coverage_pct=prep.hr_coverage_pct,
        gps_coverage_pct=prep.gps_coverage_pct,
        quality="partial" if profile == "swimming" else "ok",
        sport_metrics=_sport_metrics(
            prep, profile, distance=distance, moving=moving, sessions=sessions, lengths=lengths
        ),
    )
    return _with_paces(row)
