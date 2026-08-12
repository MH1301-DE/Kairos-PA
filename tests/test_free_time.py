from __future__ import annotations

from datetime import UTC, datetime, time

from kairos.calendar.free_time import BusyBlock, CalendarPrefs, FreeBlock, compute_free_blocks

_NO_WORK_HOURS = CalendarPrefs(
    work_hours_start=None, work_hours_end=None, buffer_minutes=0, min_free_minutes=30
)


def test_empty_calendar_yields_whole_window_as_free() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)

    blocks = compute_free_blocks([], window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [FreeBlock(start=window_start, end=window_end)]


def test_single_meeting_splits_window_into_two_free_blocks() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy_start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    busy_end = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    busy = [BusyBlock(start=busy_start, end=busy_end)]

    blocks = compute_free_blocks(busy, window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [
        FreeBlock(start=window_start, end=busy_start),
        FreeBlock(start=busy_end, end=window_end),
    ]


def test_buffer_minutes_shrinks_adjacent_free_blocks() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy_start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    busy_end = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    busy = [BusyBlock(start=busy_start, end=busy_end)]
    prefs = CalendarPrefs(
        work_hours_start=None,
        work_hours_end=None,
        buffer_minutes=15,
        min_free_minutes=30,
    )

    blocks = compute_free_blocks(busy, window_start, window_end, prefs)

    assert blocks[0].end == datetime(2026, 6, 1, 8, 45, tzinfo=UTC)
    assert blocks[1].start == datetime(2026, 6, 1, 10, 15, tzinfo=UTC)


def test_blocks_shorter_than_min_free_minutes_are_dropped() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 9, 20, tzinfo=UTC)
    busy_start = datetime(2026, 6, 1, 8, 10, tzinfo=UTC)
    busy_end = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    busy = [BusyBlock(start=busy_start, end=busy_end)]
    prefs = CalendarPrefs(
        work_hours_start=None,
        work_hours_end=None,
        buffer_minutes=0,
        min_free_minutes=30,
    )

    blocks = compute_free_blocks(busy, window_start, window_end, prefs)

    # first block is 8:00-8:10 (10 min, dropped); second is 9:00-9:20 (20 min, dropped)
    assert blocks == []


def test_overlapping_busy_blocks_are_merged() -> None:
    window_start = datetime(2026, 6, 1, 8, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
    busy1_start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    busy1_end = datetime(2026, 6, 1, 10, 30, tzinfo=UTC)
    busy2_start = datetime(2026, 6, 1, 10, 0, tzinfo=UTC)
    busy2_end = datetime(2026, 6, 1, 11, 0, tzinfo=UTC)
    busy = [
        BusyBlock(start=busy1_start, end=busy1_end),
        BusyBlock(start=busy2_start, end=busy2_end),
    ]

    blocks = compute_free_blocks(busy, window_start, window_end, _NO_WORK_HOURS)

    assert blocks == [
        FreeBlock(start=window_start, end=busy1_start),
        FreeBlock(start=busy2_end, end=window_end),
    ]


def test_work_hours_constrain_free_blocks_per_day() -> None:
    window_start = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
    window_end = datetime(2026, 6, 1, 22, 0, tzinfo=UTC)
    prefs = CalendarPrefs(
        work_hours_start=time(9, 0),
        work_hours_end=time(17, 0),
        buffer_minutes=0,
        min_free_minutes=30,
    )

    blocks = compute_free_blocks([], window_start, window_end, prefs)

    work_start = datetime(2026, 6, 1, 9, 0, tzinfo=UTC)
    work_end = datetime(2026, 6, 1, 17, 0, tzinfo=UTC)
    assert blocks == [FreeBlock(start=work_start, end=work_end)]
