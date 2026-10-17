from __future__ import annotations

import bisect
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from kairos.activities.stream_repository import LoadedStream
from kairos.activities.streams import message_time

ACTIVITY_DERIVED_ALGO_VERSION = 3

MAX_WEIGHT_S = 10.0
PAUSE_MIN_GAP_S = 10.0
PAUSE_MAX_SPEED_MPS = 0.3
HR_MIN = 25.0
HR_MAX = 230.0
_STOP_TYPES = frozenset({"stop", "stop_all", "stop_disable", "stop_disable_all"})
_INDOOR_SUB_SPORTS = frozenset(
    {"treadmill", "indoor_running", "indoor_cycling", "virtual_activity", "indoor_walking"}
)


@dataclass(frozen=True)
class Prepared:
    t: list[float]
    weights: list[float]
    moving: list[bool]
    timer_t: list[float]
    distance: list[float | None]
    hr: list[float | None]
    altitude_smooth: list[float | None]
    cadence_spm_or_rpm: list[float | None]
    power: list[float | None]
    gps_coverage_pct: float
    hr_coverage_pct: float


def message_offset(value: object, start_at: datetime) -> float | None:
    # the fit_json fallback archive keeps message times as ISO strings
    ts = message_time(value)
    if ts is None:
        return None
    ref = start_at if start_at.tzinfo else start_at.replace(tzinfo=UTC)
    return (ts - ref).total_seconds()


def _event_offset(value: object, start_at: datetime | None) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if start_at is not None:
        return message_offset(value, start_at)
    return None


def pause_intervals(
    t: Sequence[float],
    distance: Sequence[float | None],
    events: Sequence[Mapping[str, object]],
    *,
    start_at: datetime | None = None,
) -> list[tuple[float, float]]:
    if not t:
        return []
    timer_events: list[tuple[float, bool]] = []
    for ev in events:
        if ev.get("event") != "timer":
            continue
        off = _event_offset(ev.get("timestamp"), start_at)
        if off is None:
            continue
        timer_events.append((off, str(ev.get("event_type")) in _STOP_TYPES))
    if timer_events:
        timer_events.sort(key=lambda e: e[0])
        out: list[tuple[float, float]] = []
        stopped_at: float | None = None
        for off, is_stop in timer_events:
            if is_stop and stopped_at is None:
                stopped_at = off
            elif not is_stop and stopped_at is not None:
                if off > stopped_at:
                    out.append((stopped_at, off))
                stopped_at = None
        if stopped_at is not None and t[-1] > stopped_at:
            out.append((stopped_at, float("inf")))
        return out

    out = []
    last_dist: float | None = None
    last_t: float | None = None
    for ti, d in zip(t, distance, strict=True):
        if d is None:
            continue
        if last_t is not None and last_dist is not None:
            gap = ti - last_t
            if gap > PAUSE_MIN_GAP_S and max(d - last_dist, 0.0) / gap < PAUSE_MAX_SPEED_MPS:
                out.append((float(last_t), float(ti)))
        last_dist, last_t = d, ti
    return out


def _overlap(a: float, b: float, pauses: Sequence[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, e) - max(a, s)) for s, e in pauses)


def _clamp_distance(raw: Sequence[float | None]) -> list[float | None]:
    out: list[float | None] = []
    cum = 0.0
    prev: float | None = None
    for d in raw:
        if d is None:
            out.append(None)
            continue
        cum = d if prev is None else max(cum, d)
        prev = d
        out.append(cum)
    return out


def _rolling_median(values: Sequence[float | None], window: int) -> list[float | None]:
    half = window // 2
    out: list[float | None] = []
    for i, v in enumerate(values):
        win = [x for x in values[max(0, i - half) : i + half + 1] if x is not None]
        out.append(statistics.median(win) if v is not None and win else None)
    return out


def prepare(
    stream: LoadedStream,
    *,
    sport_profile: str,
    events: Sequence[Mapping[str, object]],
) -> Prepared:
    n = len(stream.t_offset_s)
    t = [float(x) for x in stream.t_offset_s]
    ch = stream.channels

    def channel(code: str) -> list[float | None]:
        return list(ch.get(code, [None] * n))

    distance = _clamp_distance(channel("distance_m"))
    pauses = pause_intervals(t, distance, events, start_at=stream.start_at)

    weights: list[float] = []
    moving: list[bool] = []
    timer_t: list[float] = []
    acc = 0.0
    for i in range(n):
        moving.append(not any(s < t[i] < e for s, e in pauses))
        timer_t.append(acc)
        if i + 1 < n:
            active = t[i + 1] - t[i] - _overlap(t[i], t[i + 1], pauses)
            weights.append(min(active, MAX_WEIGHT_S))
            acc += active
        else:
            weights.append(1.0 if moving[i] else 0.0)

    hr = [v if v is not None and HR_MIN <= v <= HR_MAX else None for v in channel("hr")]
    factor = 2.0 if sport_profile == "running" else 1.0
    cadence = [None if v is None else v * factor for v in channel("cadence")]
    gps = sum(
        1
        for a, b in zip(channel("lat_deg"), channel("lng_deg"), strict=True)
        if a is not None and b is not None
    )
    hr_n = sum(1 for v in hr if v is not None)

    return Prepared(
        t=t,
        weights=weights,
        moving=moving,
        timer_t=timer_t,
        distance=distance,
        hr=hr,
        altitude_smooth=_rolling_median(channel("altitude_m"), 5),
        cadence_spm_or_rpm=cadence,
        power=channel("power_w"),
        gps_coverage_pct=100.0 * gps / n if n else 0.0,
        hr_coverage_pct=100.0 * hr_n / n if n else 0.0,
    )


def weighted_mean(values: Sequence[float | None], weights: Sequence[float]) -> float | None:
    pairs = [(v, w) for v, w in zip(values, weights, strict=True) if v is not None and w > 0]
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    return sum(v * w for v, w in pairs) / total


def weighted_median(values: Sequence[float | None], weights: Sequence[float]) -> float | None:
    pairs = sorted((v, w) for v, w in zip(values, weights, strict=True) if v is not None and w > 0)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    cum = 0.0
    for v, w in pairs:
        cum += w
        if cum >= total / 2:
            return v
    return pairs[-1][0]


def elevation_gain_loss(
    alt_smooth: Sequence[float | None], hysteresis_m: float = 2.0
) -> tuple[float, float]:
    # extremes count in full once the reversal from them exceeds the threshold
    gain = loss = 0.0
    lo = hi = ref = ext = 0.0
    rising: bool | None = None
    started = False
    for v in alt_smooth:
        if v is None:
            continue
        if not started:
            lo = hi = v
            started = True
        elif rising is None:
            lo, hi = min(lo, v), max(hi, v)
            if v - lo > hysteresis_m:
                rising, ref, ext = True, lo, v
            elif hi - v > hysteresis_m:
                rising, ref, ext = False, hi, v
        elif rising:
            if v > ext:
                ext = v
            elif ext - v > hysteresis_m:
                gain += ext - ref
                rising, ref, ext = False, ext, v
        elif v < ext:
            ext = v
        elif v - ext > hysteresis_m:
            loss += ref - ext
            rising, ref, ext = True, ext, v
    if rising:
        gain += ext - ref
    elif rising is False:
        loss += ref - ext
    return gain, loss


def distance_source(
    *,
    sport_profile: str,
    sub_sport: str | None,
    gps_coverage_pct: float,
    has_distance: bool,
) -> str:
    if not has_distance:
        return "none"
    if sport_profile == "swimming" and sub_sport == "lap_swimming":
        return "pool"
    if sub_sport in _INDOOR_SUB_SPORTS:
        return "watch_estimate"
    if gps_coverage_pct >= 90:
        return "gps"
    if gps_coverage_pct < 50:
        return "watch_estimate"
    return "mixed"


def max_speed_10s(timer_t: Sequence[float], distance: Sequence[float | None]) -> float | None:
    pts = [(t, d) for t, d in zip(timer_t, distance, strict=True) if d is not None]
    best: float | None = None
    j = 0
    for i, (ti, di) in enumerate(pts):
        j = max(j, i)
        while j < len(pts) and pts[j][0] - ti < 10.0:
            j += 1
        if j >= len(pts):
            break
        v = (pts[j][1] - di) / (pts[j][0] - ti)
        if best is None or v > best:
            best = v
    return best


def interpolate_time_at_distance(
    timer_t: Sequence[float], distance: Sequence[float | None], target_m: float
) -> float | None:
    prev: tuple[float, float] | None = None
    for t, d in zip(timer_t, distance, strict=True):
        if d is None:
            continue
        if d >= target_m:
            if prev is None or d == prev[1]:
                return t if d == target_m else None
            return prev[0] + (t - prev[0]) * (target_m - prev[1]) / (d - prev[1])
        prev = (t, d)
    return None


def interp(xs: Sequence[float], ys: Sequence[float | None], x: float) -> float | None:
    pts = [(a, b) for a, b in zip(xs, ys, strict=True) if b is not None]
    if not pts:
        return None
    keys = [a for a, _ in pts]
    i = bisect.bisect_right(keys, x)
    if i == 0:
        return pts[0][1]
    # clamp to the last value: windows may end after the last sample
    if i == len(pts):
        return pts[-1][1]
    (x0, y0), (x1, y1) = pts[i - 1], pts[i]
    return y0 if x1 == x0 else y0 + (y1 - y0) * (x - x0) / (x1 - x0)
