from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from kairos.calendar.free_time import FreeBlock

WorkoutType = Literal["long_run", "hard", "easy", "rest"]

_LONG_RUN_SHARE = 0.35
_HARD_SHARE = 0.25
_HARD_MIN_FREE_MINUTES = 60.0
_HARD_MIN_SPACING_DAYS = 2  # >= 48h between two hard sessions
_MAX_HARD_DAYS_PER_WEEK = 2
_WEEKLY_LOAD_GROWTH = 1.1
_TAPER_DAYS = 7
_TAPER_MULTIPLIER = 0.5


@dataclass(frozen=True)
class PlannedBlock:
    day: date
    workout_type: WorkoutType
    target_trimp: float | None


def generate_plan_blocks(
    *,
    start: date,
    end: date,
    goal_date: date | None,
    free_blocks_by_day: dict[date, list[FreeBlock]],
    current_ctl: float,
) -> list[PlannedBlock]:
    """Deterministic, rule-based training plan. See design spec Scope-
    Entscheidung 2 for the full reasoning -- a heuristic, not a solver.
    """
    all_days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    weeks = [all_days[i : i + 7] for i in range(0, len(all_days), 7)]

    blocks: list[PlannedBlock] = []
    for week_index, week_days in enumerate(weeks):
        blocks.extend(_plan_week(week_days, free_blocks_by_day, current_ctl, week_index))

    if goal_date is not None and start <= goal_date <= end:
        taper_start = goal_date - timedelta(days=_TAPER_DAYS - 1)
        blocks = [
            block
            if not (taper_start <= block.day <= goal_date) or block.target_trimp is None
            else PlannedBlock(block.day, block.workout_type, block.target_trimp * _TAPER_MULTIPLIER)
            for block in blocks
        ]

    return blocks


def _longest_free_minutes(free_blocks: list[FreeBlock]) -> float:
    if not free_blocks:
        return 0.0
    return max((b.end - b.start).total_seconds() / 60 for b in free_blocks)


def _plan_week(
    week_days: list[date],
    free_blocks_by_day: dict[date, list[FreeBlock]],
    current_ctl: float,
    week_index: int,
) -> list[PlannedBlock]:
    free_minutes = {d: _longest_free_minutes(free_blocks_by_day.get(d, [])) for d in week_days}

    long_run_day: date | None = None
    if any(m > 0 for m in free_minutes.values()):
        long_run_day = max(week_days, key=lambda d: free_minutes[d])

    hard_candidates = sorted(
        (
            d
            for d in week_days
            if d != long_run_day and free_minutes[d] >= _HARD_MIN_FREE_MINUTES
        ),
        key=lambda d: -free_minutes[d],
    )
    hard_days: list[date] = []
    for candidate in hard_candidates:
        if len(hard_days) >= _MAX_HARD_DAYS_PER_WEEK:
            break
        if all(abs((candidate - h).days) >= _HARD_MIN_SPACING_DAYS for h in hard_days):
            hard_days.append(candidate)

    assigned = {long_run_day, *hard_days}
    easy_days = [d for d in week_days if d not in assigned and free_minutes[d] > 0]
    rest_days = [d for d in week_days if d not in assigned and free_minutes[d] <= 0]

    # every week needs at least one real rest day, even if every day happens
    # to have a usable free block
    if not rest_days and easy_days:
        smallest = min(easy_days, key=lambda d: free_minutes[d])
        easy_days.remove(smallest)
        rest_days.append(smallest)

    weekly_total = current_ctl * 7 * (_WEEKLY_LOAD_GROWTH**week_index)
    long_run_load = weekly_total * _LONG_RUN_SHARE if long_run_day else 0.0
    hard_load_each = weekly_total * _HARD_SHARE if hard_days else 0.0
    remaining = weekly_total - long_run_load - hard_load_each * len(hard_days)
    easy_load_each = remaining / len(easy_days) if easy_days else 0.0

    result: list[PlannedBlock] = []
    for d in week_days:
        if d == long_run_day:
            result.append(PlannedBlock(d, "long_run", long_run_load))
        elif d in hard_days:
            result.append(PlannedBlock(d, "hard", hard_load_each))
        elif d in easy_days:
            result.append(PlannedBlock(d, "easy", easy_load_each))
        else:
            result.append(PlannedBlock(d, "rest", None))
    return result
