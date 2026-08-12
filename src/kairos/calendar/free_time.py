from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta


@dataclass(frozen=True)
class BusyBlock:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class FreeBlock:
    start: datetime
    end: datetime


@dataclass(frozen=True)
class CalendarPrefs:
    work_hours_start: time | None
    work_hours_end: time | None
    buffer_minutes: int
    min_free_minutes: int


def compute_free_blocks(
    busy: list[BusyBlock],
    window_start: datetime,
    window_end: datetime,
    prefs: CalendarPrefs,
) -> list[FreeBlock]:
    merged = _merge_overlapping(sorted(busy, key=lambda b: b.start))
    buffer = timedelta(minutes=prefs.buffer_minutes)
    min_duration = timedelta(minutes=prefs.min_free_minutes)

    candidates: list[FreeBlock] = []
    cursor = window_start
    for block in merged:
        buffered_start = block.start - buffer
        buffered_end = block.end + buffer
        if buffered_start > cursor:
            candidates.append(FreeBlock(start=cursor, end=buffered_start))
        cursor = max(cursor, buffered_end)
    if cursor < window_end:
        candidates.append(FreeBlock(start=cursor, end=window_end))

    constrained = [
        c for c in _apply_work_hours(candidates, prefs) if c.end - c.start >= min_duration
    ]
    return constrained


def _merge_overlapping(blocks: list[BusyBlock]) -> list[BusyBlock]:
    if not blocks:
        return []
    merged = [blocks[0]]
    for block in blocks[1:]:
        last = merged[-1]
        if block.start <= last.end:
            merged[-1] = BusyBlock(start=last.start, end=max(last.end, block.end))
        else:
            merged.append(block)
    return merged


def _apply_work_hours(blocks: list[FreeBlock], prefs: CalendarPrefs) -> list[FreeBlock]:
    if prefs.work_hours_start is None or prefs.work_hours_end is None:
        return blocks
    result: list[FreeBlock] = []
    for block in blocks:
        day_start = block.start.replace(
            hour=prefs.work_hours_start.hour,
            minute=prefs.work_hours_start.minute,
            second=0,
            microsecond=0,
        )
        day_end = block.start.replace(
            hour=prefs.work_hours_end.hour,
            minute=prefs.work_hours_end.minute,
            second=0,
            microsecond=0,
        )
        clipped_start = max(block.start, day_start)
        clipped_end = min(block.end, day_end)
        if clipped_start < clipped_end:
            result.append(FreeBlock(start=clipped_start, end=clipped_end))
    return result
