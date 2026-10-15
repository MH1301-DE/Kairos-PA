from __future__ import annotations

from dataclasses import dataclass
from itertools import accumulate

from kairos.activities.derive.common import PAUSE_MIN_GAP_S, Prepared, weighted_mean

BEST_EFFORT_DISTANCES: dict[str, float] = {
    "800m": 800.0,
    "1500m": 1500.0,
    "3000m": 3000.0,
    "5k": 5000.0,
    "10k": 10000.0,
    "hm": 21097.5,
    "m": 42195.0,
    "50k": 50000.0,
    "100k": 100000.0,
}
BEST_EFFORT_MAX_STEP_SPEED_MPS = 8.5


@dataclass(frozen=True, kw_only=True)
class BestEffortRow:
    distance_key: str
    distance_m: float
    duration_s: float
    start_offset_s: float
    start_km: float
    hr_avg: int | None
    quality: str


@dataclass(frozen=True)
class _Window:
    duration: float
    start_t: float
    end_t: float
    start_d: float
    steps: tuple[int, int]


def _time_at(timer: list[float], dist: list[float], q: int, target: float) -> float:
    if dist[q] == target or q == 0:
        return timer[q]
    return timer[q - 1] + (timer[q] - timer[q - 1]) * (target - dist[q - 1]) / (
        dist[q] - dist[q - 1]
    )


def _windows(timer: list[float], dist: list[float], target_m: float) -> list[_Window]:
    n = len(dist)
    out: list[_Window] = []
    q = 0
    for p in range(n):
        goal = dist[p] + target_m
        q = max(q, p)
        while q < n and dist[q] < goal:
            q += 1
        if q >= n:
            break
        end_t = _time_at(timer, dist, q, goal)
        out.append(_Window(end_t - timer[p], timer[p], end_t, dist[p], (p + 1, q)))
    p = 0
    for q in range(n):
        goal = dist[q] - target_m
        if goal < dist[0]:
            continue
        while dist[p] < goal:
            p += 1
        start_t = _time_at(timer, dist, p, goal)
        first_step = p + 1 if dist[p] == goal else p
        out.append(_Window(timer[q] - start_t, start_t, timer[q], goal, (first_step, q)))
    return out


def best_efforts(
    prep: Prepared, *, sport_profile: str, distance_source: str
) -> list[BestEffortRow]:
    if sport_profile != "running" or distance_source != "gps":
        return []
    idx = [i for i, d in enumerate(prep.distance) if d is not None]
    if len(idx) < 2:
        return []
    timer = [prep.timer_t[i] for i in idx]
    dist = [float(prep.distance[i] or 0.0) for i in idx]
    wall = [prep.t[i] for i in idx]
    bad = [0]
    gap = [0]
    for k in range(1, len(idx)):
        dt, dd = wall[k] - wall[k - 1], dist[k] - dist[k - 1]
        jump = dd > 0 and (dt <= 0 or dd / dt > BEST_EFFORT_MAX_STEP_SPEED_MPS)
        bad.append(int(jump))
        gap.append(int(timer[k] - timer[k - 1] > PAUSE_MIN_GAP_S))
    bad_cum = [0, *accumulate(bad)]
    gap_cum = [0, *accumulate(gap)]

    rows: list[BestEffortRow] = []
    for key, target in BEST_EFFORT_DISTANCES.items():
        best: _Window | None = None
        for w in _windows(timer, dist, target):
            lo, hi = w.steps
            if bad_cum[hi + 1] - bad_cum[lo] > 0:
                continue
            if best is None or w.duration < best.duration:
                best = w
        if best is None:
            continue
        lo, hi = best.steps
        partial = gap_cum[hi + 1] - gap_cum[lo] > 0
        inside = [i for i, tt in enumerate(prep.timer_t) if best.start_t <= tt <= best.end_t]
        hr = weighted_mean([prep.hr[i] for i in inside], [prep.weights[i] for i in inside])
        rows.append(
            BestEffortRow(
                distance_key=key,
                distance_m=target,
                duration_s=best.duration,
                start_offset_s=best.start_t,
                start_km=best.start_d / 1000.0,
                hr_avg=None if hr is None else round(hr),
                quality="partial" if partial else "ok",
            )
        )
    return rows
