from __future__ import annotations

import bisect
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime

from kairos.activities.derive.common import (
    MAX_WEIGHT_S,
    Prepared,
    elevation_gain_loss,
    interpolate_time_at_distance,
    weighted_mean,
    weighted_median,
)

SPLIT_UNIT_M = {"running": 1000.0, "hiking": 1000.0, "cycling": 5000.0, "swimming": 100.0}
MIN_PARTIAL_M = {"running": 100.0, "hiking": 100.0, "cycling": 1000.0, "swimming": 25.0}
_EPS_M = 1e-6


@dataclass(frozen=True, kw_only=True)
class SplitRow:
    kind: str
    idx: int
    unit_m: float | None = None
    start_offset_s: float | None = None
    distance_m: float | None = None
    timer_s: float | None = None
    pace_s_km: float | None = None
    speed_kmh: float | None = None
    pace_s_100m: float | None = None
    elev_gain_m: float | None = None
    elev_loss_m: float | None = None
    hr_min: int | None = None
    hr_median: int | None = None
    hr_max: int | None = None
    hr_avg: int | None = None
    cadence_avg: float | None = None
    power_avg_w: float | None = None
    is_partial: bool = False
    lap_intensity: str | None = None
    lap_trigger: str | None = None
    wkt_step_index: int | None = None
    swim_lengths: int | None = None
    swolf: float | None = None
    quality: str = "ok"


def _offset(value: object, start_at: datetime) -> float | None:
    if not isinstance(value, datetime):
        return None
    ts = value if value.tzinfo else value.replace(tzinfo=UTC)
    ref = start_at if start_at.tzinfo else start_at.replace(tzinfo=UTC)
    return (ts - ref).total_seconds()


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _interp(xs: Sequence[float], ys: Sequence[float | None], x: float) -> float | None:
    pts = [(a, b) for a, b in zip(xs, ys, strict=True) if b is not None]
    if not pts:
        return None
    keys = [a for a, _ in pts]
    i = bisect.bisect_right(keys, x)
    if i == 0:
        return pts[0][1]
    if i == len(pts):
        return pts[-1][1]
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)


def _round(value: float | None) -> int | None:
    return None if value is None else round(value)


def _row(
    prep: Prepared,
    idx: list[int],
    *,
    kind: str,
    number: int,
    start_offset_s: float,
    distance_m: float | None,
    timer_s: float | None,
    quality: str,
) -> SplitRow:
    def sub(values: Sequence[float | None]) -> list[float | None]:
        return [values[i] for i in idx]

    weights = [prep.weights[i] for i in idx]
    hr = [v for v in sub(prep.hr) if v is not None]
    gain, loss = elevation_gain_loss(sub(prep.altitude_smooth))
    has_alt = any(v is not None for v in sub(prep.altitude_smooth))
    # unrecognised recording gaps make the window unreliable
    gap = any(
        prep.timer_t[i + 1] - prep.timer_t[i] > MAX_WEIGHT_S for i in idx if i + 1 < len(prep.t)
    )
    pace_s_km = speed_kmh = pace_s_100m = None
    if distance_m is not None and timer_s is not None and distance_m > 0 and timer_s > 0:
        pace_s_km = timer_s / distance_m * 1000
        speed_kmh = distance_m / timer_s * 3.6
        pace_s_100m = timer_s / distance_m * 100
    return SplitRow(
        kind=kind,
        idx=number,
        start_offset_s=start_offset_s,
        distance_m=distance_m,
        timer_s=timer_s,
        pace_s_km=pace_s_km,
        speed_kmh=speed_kmh,
        pace_s_100m=pace_s_100m,
        elev_gain_m=gain if has_alt else None,
        elev_loss_m=loss if has_alt else None,
        hr_min=_round(min(hr)) if hr else None,
        hr_median=_round(weighted_median(sub(prep.hr), weights)),
        hr_max=_round(max(hr)) if hr else None,
        hr_avg=_round(weighted_mean(sub(prep.hr), weights)),
        cadence_avg=weighted_mean(sub(prep.cadence_spm_or_rpm), weights),
        power_avg_w=weighted_mean(sub(prep.power), weights),
        quality="partial" if gap else quality,
    )


def _timer_window(prep: Prepared, a: float, b: float) -> list[int]:
    return [i for i, tt in enumerate(prep.timer_t) if a <= tt < b]


def _real_window(prep: Prepared, a: float, b: float) -> list[int]:
    return [i for i, t in enumerate(prep.t) if a <= t < b]


def distance_splits(
    prep: Prepared,
    *,
    sport_profile: str,
    lengths: Sequence[Mapping[str, object]],
    pool_length_m: float | None = None,
    start_at: datetime | None = None,
) -> list[SplitRow]:
    unit = SPLIT_UNIT_M.get(sport_profile)
    if unit is None:
        return []
    if sport_profile == "swimming":
        if not pool_length_m or start_at is None:
            return []
        return _swim_splits(prep, lengths, pool_length_m, start_at)
    with_dist = [i for i, d in enumerate(prep.distance) if d is not None]
    if not with_dist:
        return []
    last = with_dist[-1]
    total = max(d for d in prep.distance if d is not None)
    bounds: list[tuple[float, float, float, bool]] = []
    start_t = start_d = 0.0
    k = 1
    while k * unit <= total + _EPS_M:
        end_t = interpolate_time_at_distance(prep.timer_t, prep.distance, k * unit)
        if end_t is None:
            break
        bounds.append((start_t, end_t, unit, False))
        start_t, start_d = end_t, k * unit
        k += 1
    rest = total - start_d
    if rest >= MIN_PARTIAL_M[sport_profile] and prep.timer_t[last] > start_t:
        bounds.append((start_t, prep.timer_t[last], rest, True))
    rows: list[SplitRow] = []
    for number, (a, b, dist, partial) in enumerate(bounds, start=1):
        idx = _timer_window(prep, a, b)
        row = _row(
            prep,
            idx,
            kind="distance",
            number=number,
            start_offset_s=a,
            distance_m=dist,
            timer_s=b - a,
            quality="ok",
        )
        rows.append(replace(row, unit_m=unit, is_partial=partial))
    return rows


def _swim_splits(
    prep: Prepared,
    lengths: Sequence[Mapping[str, object]],
    pool_length_m: float,
    start_at: datetime,
) -> list[SplitRow]:
    unit = SPLIT_UNIT_M["swimming"]
    active = [ln for ln in lengths if ln.get("length_type") == "active"]
    groups: list[list[Mapping[str, object]]] = []
    current: list[Mapping[str, object]] = []
    for ln in active:
        current.append(ln)
        if len(current) * pool_length_m >= unit - _EPS_M:
            groups.append(current)
            current = []
    if current and len(current) * pool_length_m >= MIN_PARTIAL_M["swimming"]:
        groups.append(current)
    rows: list[SplitRow] = []
    for number, group in enumerate(groups, start=1):
        starts = [_offset(ln.get("start_time"), start_at) for ln in group]
        secs = [_num(ln.get("total_timer_time")) or 0.0 for ln in group]
        last_elapsed = _num(group[-1].get("total_elapsed_time")) or secs[-1]
        strokes = [_num(ln.get("total_strokes")) for ln in group]
        first, last_start = starts[0], starts[-1]
        a = first if first is not None else 0.0
        b = (last_start if last_start is not None else a) + last_elapsed
        timer_s = sum(secs)
        swolf = (
            (timer_s + sum(s for s in strokes if s is not None)) / len(group)
            if all(s is not None for s in strokes)
            else None
        )
        dist = len(group) * pool_length_m
        row = _row(
            prep,
            _real_window(prep, a, b),
            kind="distance",
            number=number,
            start_offset_s=_interp(prep.t, prep.timer_t, a) or 0.0,
            distance_m=dist,
            timer_s=timer_s,
            quality="partial",
        )
        rows.append(
            replace(
                row,
                unit_m=unit,
                is_partial=dist < unit - _EPS_M,
                swim_lengths=len(group),
                swolf=swolf,
            )
        )
    return rows


def lap_splits(
    prep: Prepared, *, laps: Sequence[Mapping[str, object]], start_at: datetime
) -> list[SplitRow]:
    has_dist = any(d is not None for d in prep.distance)
    rows: list[SplitRow] = []
    for number, lap in enumerate(laps, start=1):
        a = _offset(lap.get("start_time"), start_at)
        if a is None:
            continue
        b = a + (_num(lap.get("total_elapsed_time")) or 0.0)
        ta = _interp(prep.t, prep.timer_t, a) or 0.0
        tb = _interp(prep.t, prep.timer_t, b) or 0.0
        if has_dist:
            da, db = _interp(prep.t, prep.distance, a), _interp(prep.t, prep.distance, b)
            dist = None if da is None or db is None else db - da
        else:
            dist = _num(lap.get("total_distance"))
        active = _num(lap.get("num_active_lengths"))
        strokes = _num(lap.get("total_strokes"))
        lap_timer = _num(lap.get("total_timer_time"))
        swolf = (
            (lap_timer + strokes) / active
            if active and strokes is not None and lap_timer is not None
            else None
        )
        step = lap.get("wkt_step_index")
        intensity, trigger = lap.get("intensity"), lap.get("lap_trigger")
        row = _row(
            prep,
            _real_window(prep, a, b),
            kind="lap",
            number=number,
            start_offset_s=ta,
            distance_m=dist,
            timer_s=tb - ta,
            quality="partial" if lap.get("sport") == "swimming" else "ok",
        )
        rows.append(
            replace(
                row,
                lap_intensity=None if intensity is None else str(intensity),
                lap_trigger=None if trigger is None else str(trigger),
                wkt_step_index=step if isinstance(step, int) else None,
                swim_lengths=None if active is None else int(active),
                swolf=swolf,
            )
        )
    return rows


def _full_paces(splits: Sequence[SplitRow]) -> list[SplitRow]:
    return [
        s for s in splits if s.kind == "distance" and not s.is_partial and s.pace_s_km is not None
    ]


def pace_cv_pct(splits: Sequence[SplitRow]) -> float | None:
    paces = [s.pace_s_km for s in _full_paces(splits) if s.pace_s_km is not None]
    if len(paces) < 2:
        return None
    return statistics.pstdev(paces) / statistics.fmean(paces) * 100


def fastest_and_slowest_split(splits: Sequence[SplitRow]) -> tuple[SplitRow, SplitRow] | None:
    full = _full_paces(splits)
    if not full:
        return None
    by_pace = sorted(full, key=lambda s: (s.pace_s_km or 0.0, s.idx))
    return by_pace[0], by_pace[-1]
