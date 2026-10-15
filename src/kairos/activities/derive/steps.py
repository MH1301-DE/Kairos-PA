from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from kairos.activities.derive.common import Prepared, interp, weighted_mean

MIN_LAP_S = 5.0
MIN_RATED_S = 20.0
AVG_TOLERANCE = 0.02
HR_IN_TARGET_MIN_PCT = 80.0
_STEP_TYPES = frozenset({"warmup", "interval", "recovery", "rest", "cooldown"})
_POWER_TARGETS = frozenset({"power", "power_3s", "power_10s", "power_30s", "power_lap"})
_PACE_PROFILES = frozenset({"running", "hiking"})
# FIT workout_power: values above 1000 are watts + 1000, below are % FTP
_POWER_WATTS_OFFSET = 1000.0


@dataclass(frozen=True, kw_only=True)
class StepResultRow:
    exec_idx: int
    wkt_step_index: int
    repeat_iteration: int | None
    step_type: str
    step_note: str | None
    planned_end: str | None
    target_type: str | None
    target_low: float | None
    target_high: float | None
    target_source: str
    secondary_type: str | None = None
    secondary_low: float | None = None
    secondary_high: float | None = None
    timer_s: float | None
    distance_m: float | None
    avg_pace_s_km: float | None
    avg_hr: float | None
    hr_in_target_pct: float | None
    avg_cadence: float | None
    avg_power_w: float | None
    hit: bool | None
    secondary_hit: bool | None = None


@dataclass(frozen=True)
class _Target:
    kind: str | None
    low: float | None
    high: float | None
    source: str


def _num(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _offset(value: object, start_at: datetime) -> float | None:
    if not isinstance(value, datetime):
        return None
    ts = value if value.tzinfo else value.replace(tzinfo=UTC)
    ref = start_at if start_at.tzinfo else start_at.replace(tzinfo=UTC)
    return (ts - ref).total_seconds()


def _text(value: object) -> str | None:
    # long notes decode as a list of string chunks
    if isinstance(value, list):
        value = next((v for v in value if isinstance(v, str) and v.strip()), None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _planned_end(step: Mapping[str, object]) -> str | None:
    kind = step.get("duration_type")
    raw = _num(step.get("duration_value"))
    if kind == "time":
        secs = _num(step.get("duration_time"))
        secs = secs if secs is not None else None if raw is None else raw / 1000
        return "time" if secs is None else f"time {secs:g} s"
    if kind == "distance":
        metres = _num(step.get("duration_distance"))
        metres = metres if metres is not None else None if raw is None else raw / 100
        return "distance" if metres is None else f"distance {metres:g} m"
    if kind == "open":
        return "lap_button"
    return None if kind is None else str(kind)


def _sorted_pair(low: float | None, high: float | None) -> tuple[float, float] | None:
    if low is None or high is None or (low == 0 and high == 0):
        return None
    return (min(low, high), max(low, high))


def _target(
    step: Mapping[str, object],
    *,
    sport_profile: str,
    hr_targets: Mapping[int, tuple[float, float]] | None,
    step_index: int,
) -> _Target:
    kind = step.get("target_type")
    raw_low = _num(step.get("custom_target_value_low"))
    raw_high = _num(step.get("custom_target_value_high"))
    if kind is None or kind == "open":
        return _Target("none", None, None, "none")
    if kind == "heart_rate":
        api = None if hr_targets is None else hr_targets.get(step_index)
        if api is None:
            return _Target("hr_range", None, None, "unclear")
        lo, hi = sorted(api)
        return _Target("hr_range", lo, hi, "api")
    if kind in ("speed", "cadence"):
        out = "cadence" if kind == "cadence" else "speed"
        if kind == "speed" and sport_profile in _PACE_PROFILES:
            out = "pace"
        low = _num(step.get(f"custom_target_{kind}_low"))
        high = _num(step.get(f"custom_target_{kind}_high"))
        if low is None and high is None and raw_low is not None and raw_high is not None:
            # raw speed is mm/s
            scale = 1000 if kind == "speed" else 1
            low, high = raw_low / scale, raw_high / scale
        pair = _sorted_pair(low, high)
        return _Target(out, None, None, "unclear") if pair is None else _Target(out, *pair, "fit")
    if kind in _POWER_TARGETS:
        pair = _sorted_pair(raw_low, raw_high)
        if pair is None or pair[0] <= _POWER_WATTS_OFFSET:
            return _Target("power", None, None, "unclear")
        return _Target("power", pair[0] - _POWER_WATTS_OFFSET, pair[1] - _POWER_WATTS_OFFSET, "fit")
    return _Target(None, None, None, "unclear")


def _repeat_blocks(steps: Sequence[Mapping[str, object]]) -> dict[int, int]:
    block_of: dict[int, int] = {}
    blocks: list[tuple[int, int]] = []
    for step in steps:
        end = step.get("message_index")
        start = step.get("duration_step")
        if (
            step.get("duration_type") == "repeat_until_steps_cmplt"
            and isinstance(end, int)
            and isinstance(start, int)
        ):
            blocks.append((start, end))
    # widest first, so nested (narrower) blocks overwrite their outer block
    for start, end in sorted(blocks, key=lambda b: b[0] - b[1]):
        for i in range(start, end):
            block_of[i] = end
    return block_of


def _step_type(step: Mapping[str, object]) -> str:
    intensity = step.get("intensity")
    return intensity if isinstance(intensity, str) and intensity in _STEP_TYPES else "interval"


def _within(value: float | None, low: float, high: float) -> bool | None:
    if value is None:
        return None
    return low * (1 - AVG_TOLERANCE) <= value <= high * (1 + AVG_TOLERANCE)


def step_results(
    prep: Prepared,
    *,
    sport_profile: str,
    workout_steps: Sequence[Mapping[str, object]],
    laps: Sequence[Mapping[str, object]],
    start_at: datetime,
    hr_targets: Mapping[int, tuple[float, float]] | None,
) -> list[StepResultRow]:
    steps = {mi: s for s in workout_steps if isinstance(mi := s.get("message_index"), int)}
    if not steps:
        return []
    block_of = _repeat_blocks(workout_steps)

    execs: list[tuple[int, list[tuple[float, float]]]] = []
    for lap in laps:
        index = lap.get("wkt_step_index")
        a = _offset(lap.get("start_time"), start_at)
        elapsed = _num(lap.get("total_elapsed_time")) or 0.0
        if not isinstance(index, int) or index not in steps or a is None or elapsed < MIN_LAP_S:
            continue
        if execs and execs[-1][0] == index:
            execs[-1][1].append((a, a + elapsed))
        else:
            execs.append((index, [(a, a + elapsed)]))

    rows: list[StepResultRow] = []
    iteration: dict[int, int] = {}
    prev_index: int | None = None
    for number, (index, windows) in enumerate(execs, start=1):
        block = block_of.get(index)
        repeat_iteration: int | None = None
        if block is not None:
            if prev_index is None or block_of.get(prev_index) != block:
                iteration[block] = 1
            elif index <= prev_index:
                # stepping back inside the block starts its next pass
                iteration[block] += 1
            repeat_iteration = iteration[block]
        prev_index = index

        timer_s = 0.0
        distance: float | None = 0.0
        idx: list[int] = []
        for a, b in windows:
            ta, tb = interp(prep.t, prep.timer_t, a), interp(prep.t, prep.timer_t, b)
            timer_s += 0.0 if ta is None or tb is None else tb - ta
            da, db = interp(prep.t, prep.distance, a), interp(prep.t, prep.distance, b)
            distance = None if distance is None or da is None or db is None else distance + db - da
            idx.extend(i for i, t in enumerate(prep.t) if a <= t < b)
        weights = [prep.weights[i] for i in idx]
        hr = [prep.hr[i] for i in idx]
        pace = timer_s / distance * 1000 if distance and timer_s > 0 else None
        speed = distance / timer_s if distance and timer_s > 0 else None
        cadence = weighted_mean([prep.cadence_spm_or_rpm[i] for i in idx], weights)
        power = weighted_mean([prep.power[i] for i in idx], weights)

        step = steps[index]
        target = _target(step, sport_profile=sport_profile, hr_targets=hr_targets, step_index=index)
        hr_pct: float | None = None
        if target.kind == "hr_range" and target.low is not None and target.high is not None:
            lo, hi = target.low, target.high
            rated = [(v, w) for v, w in zip(hr, weights, strict=True) if v is not None and w > 0]
            total = sum(w for _, w in rated)
            if total > 0:
                hr_pct = 100.0 * sum(w for v, w in rated if lo <= v <= hi) / total

        hit: bool | None = None
        if target.low is not None and target.high is not None and timer_s >= MIN_RATED_S:
            if target.kind == "hr_range":
                hit = None if hr_pct is None else hr_pct >= HR_IN_TARGET_MIN_PCT
            elif target.kind == "pace":
                hit = _within(pace, 1000 / target.high, 1000 / target.low)
            elif target.kind == "speed":
                hit = _within(speed, target.low, target.high)
            elif target.kind == "cadence":
                hit = _within(cadence, target.low, target.high)
            elif target.kind == "power":
                hit = _within(power, target.low, target.high)

        rows.append(
            StepResultRow(
                exec_idx=number,
                wkt_step_index=index,
                repeat_iteration=repeat_iteration,
                step_type=_step_type(step),
                step_note=_text(step.get("notes")) or _text(step.get("wkt_step_name")),
                planned_end=_planned_end(step),
                target_type=target.kind,
                target_low=target.low,
                target_high=target.high,
                target_source=target.source,
                timer_s=timer_s,
                distance_m=distance,
                avg_pace_s_km=pace,
                avg_hr=weighted_mean(hr, weights),
                hr_in_target_pct=hr_pct,
                avg_cadence=cadence,
                avg_power_w=power,
                hit=hit,
            )
        )
    return rows
