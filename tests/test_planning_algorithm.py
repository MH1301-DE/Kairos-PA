from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from kairos.calendar.free_time import FreeBlock
from kairos.planning.algorithm import generate_plan_blocks


def _free_blocks_every_day(
    start: date, end: date, minutes: int = 90
) -> dict[date, list[FreeBlock]]:
    result: dict[date, list[FreeBlock]] = {}
    day = start
    while day <= end:
        block_start = datetime(day.year, day.month, day.day, 8, 0, tzinfo=UTC)
        result[day] = [FreeBlock(start=block_start, end=block_start + timedelta(minutes=minutes))]
        day += timedelta(days=1)
    return result


def test_three_week_window_produces_one_long_run_per_week() -> None:
    start = date(2026, 1, 5)
    end = start + timedelta(days=20)  # exactly 3 weeks
    blocks = generate_plan_blocks(
        start=start, end=end, goal_date=None,
        free_blocks_by_day=_free_blocks_every_day(start, end), current_ctl=40.0,
    )
    long_runs = [b for b in blocks if b.workout_type == "long_run"]
    assert len(long_runs) == 3

    # 48h spacing between hard sessions, checked within each week
    weeks = [blocks[i : i + 7] for i in range(0, len(blocks), 7)]
    for week in weeks:
        hard_days = sorted(b.day for b in week if b.workout_type == "hard")
        for a, b in zip(hard_days, hard_days[1:], strict=False):
            assert (b - a).days >= 2


def test_no_free_blocks_anywhere_produces_an_all_rest_plan() -> None:
    start = date(2026, 1, 5)
    end = start + timedelta(days=6)
    blocks = generate_plan_blocks(
        start=start, end=end, goal_date=None, free_blocks_by_day={}, current_ctl=40.0,
    )
    assert len(blocks) == 7
    assert all(b.workout_type == "rest" for b in blocks)
    assert all(b.target_trimp is None for b in blocks)


def test_goal_date_taper_week_has_lower_load_than_the_week_before() -> None:
    start = date(2026, 1, 5)
    end = start + timedelta(days=20)  # 3 weeks
    goal_date = end  # taper window = the final 7 days, i.e. week 3
    blocks = generate_plan_blocks(
        start=start, end=end, goal_date=goal_date,
        free_blocks_by_day=_free_blocks_every_day(start, end), current_ctl=40.0,
    )
    weeks = [blocks[i : i + 7] for i in range(0, len(blocks), 7)]
    assert len(weeks) == 3

    def week_load(week: list) -> float:
        return sum(b.target_trimp or 0.0 for b in week)

    assert week_load(weeks[2]) < week_load(weeks[1])


def test_every_week_has_at_least_one_rest_day_even_with_free_blocks_daily() -> None:
    start = date(2026, 1, 5)
    end = start + timedelta(days=13)  # 2 weeks
    blocks = generate_plan_blocks(
        start=start, end=end, goal_date=None,
        free_blocks_by_day=_free_blocks_every_day(start, end), current_ctl=40.0,
    )
    weeks = [blocks[i : i + 7] for i in range(0, len(blocks), 7)]
    for week in weeks:
        assert sum(1 for b in week if b.workout_type == "rest") >= 1
