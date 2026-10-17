from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from kairos.scheduler.schedule import (
    InvalidSchedule,
    describe,
    min_gap,
    next_occurrence,
    occurrences,
    parse,
    validate,
)

BERLIN = "Europe/Berlin"
_TZ = ZoneInfo(BERLIN)


def _local(y: int, mo: int, d: int, h: int = 0, mi: int = 0, fold: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=_TZ, fold=fold)


def _utc(y: int, mo: int, d: int, h: int = 0, mi: int = 0) -> datetime:
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# --- presets ------------------------------------------------------------------------


def test_daily_at_eight_berlin() -> None:
    after = _local(2026, 10, 15, 8, 0)
    assert next_occurrence(["0 8 * * *"], BERLIN, after) == _local(2026, 10, 16, 8, 0)
    assert next_occurrence(["0 8 * * *"], BERLIN, after - timedelta(seconds=1)) == after


def test_weekdays_friday_and_sunday() -> None:
    # 2026-10-15 is a Thursday
    after = _local(2026, 10, 15, 12)
    runs = occurrences(["0 18 * * 5", "0 18 * * 0"], BERLIN, after, after + timedelta(days=7))
    assert runs == [_local(2026, 10, 16, 18), _local(2026, 10, 18, 18)]


def test_several_fixed_times_and_lists() -> None:
    after = _local(2026, 10, 15, 9)
    runs = occurrences(["0 8,12,18 * * *", "30 19 * * *"], BERLIN, after, _local(2026, 10, 16))
    assert runs == [
        _local(2026, 10, 15, 12),
        _local(2026, 10, 15, 18),
        _local(2026, 10, 15, 19, 30),
    ]


def test_every_n_minutes_with_hour_window() -> None:
    after = _local(2026, 10, 15, 20, 20)
    assert next_occurrence(["*/20 8-20 * * *"], BERLIN, after) == _local(2026, 10, 15, 20, 40)
    assert next_occurrence(["*/20 8-20 * * *"], BERLIN, _local(2026, 10, 15, 20, 40)) == (
        _local(2026, 10, 16, 8, 0)
    )


def test_every_n_hours_with_window() -> None:
    after = _local(2026, 10, 15, 7)
    runs = occurrences(["0 8-20/2 * * *"], BERLIN, after, _local(2026, 10, 15, 23))
    assert [r.astimezone(_TZ).hour for r in runs] == [8, 10, 12, 14, 16, 18, 20]


def test_result_is_utc() -> None:
    nxt = next_occurrence(["0 8 * * *"], BERLIN, _utc(2026, 7, 1))
    assert nxt.tzinfo is UTC
    assert nxt == _utc(2026, 7, 1, 6)


def test_weekday_seven_is_sunday() -> None:
    assert parse("0 8 * * 7").weekdays == frozenset({0})
    assert parse("0 8 * * 1-5").weekdays == frozenset({1, 2, 3, 4, 5})


# --- DST in Europe/Berlin -----------------------------------------------------------


def test_spring_gap_runs_shifted_by_the_gap() -> None:
    nxt = next_occurrence(["30 2 * * *"], BERLIN, _local(2026, 3, 29, 0))
    assert nxt == _utc(2026, 3, 29, 1, 30)
    assert nxt.astimezone(_TZ).strftime("%H:%M") == "03:30"


def test_autumn_double_time_runs_once() -> None:
    first = next_occurrence(["30 2 * * *"], BERLIN, _local(2026, 10, 25, 0))
    assert first == _utc(2026, 10, 25, 0, 30)  # first pass, still CEST
    assert next_occurrence(["30 2 * * *"], BERLIN, first) == _utc(2026, 10, 26, 1, 30)


def test_hourly_over_both_dst_nights() -> None:
    autumn = occurrences(["0 * * * *"], BERLIN, _local(2026, 10, 25), _local(2026, 10, 26))
    # 25-hour day, 02:00 only on its first pass
    assert len([r for r in autumn if r < _local(2026, 10, 26)]) == 24 - 1
    assert _utc(2026, 10, 25, 1) not in autumn
    spring = occurrences(["0 * * * *"], BERLIN, _local(2026, 3, 29), _local(2026, 3, 30))
    # 23-hour day: 02:00 falls onto 03:00 and runs once
    assert len([r for r in spring if r < _local(2026, 3, 30)]) == 23 - 1
    assert len(spring) == len(set(spring))


# --- validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "expr",
    [
        "*/45 * * * *",  # cron would mean :00 and :45
        "0 */7 * * *",
        "0 8 1 * *",
        "0 8 * 6 *",
        "* 8 * * *",
        "0 8 * * */2",
        "60 8 * * *",
        "0 24 * * *",
        "0 8 * * 8",
        "0 8 * *",
        "a 8 * * *",
        "10-5 8 * * *",
    ],
)
def test_rejects_outside_the_subset(expr: str) -> None:
    with pytest.raises(InvalidSchedule):
        parse(expr)


def test_rejects_more_than_six_expressions_and_unknown_zone() -> None:
    with pytest.raises(InvalidSchedule):
        validate([f"0 {h} * * *" for h in range(7)], BERLIN)
    with pytest.raises(InvalidSchedule):
        validate([], BERLIN)
    with pytest.raises(InvalidSchedule):
        validate(["0 8 * * *"], "Mars/Olympus")


def test_messages_are_german() -> None:
    with pytest.raises(InvalidSchedule, match="Teilern von 60"):
        parse("*/45 * * * *")


# --- min_gap and describe -----------------------------------------------------------


def test_min_gap_catches_two_expressions_five_minutes_apart() -> None:
    gap = min_gap(["0 8 * * *", "5 8 * * *"], BERLIN, _local(2026, 10, 15))
    assert gap == timedelta(minutes=5)


def test_min_gap_of_hourly_window_and_weekly() -> None:
    start = _local(2026, 11, 2)
    assert min_gap(["0 8-20/2 * * *"], BERLIN, start) == timedelta(hours=2)
    assert min_gap(["0 18 * * 0"], BERLIN, start) == timedelta(days=7)
    # across the autumn switch a week of wall-clock time is 7 days and 1 hour
    assert min_gap(["0 18 * * 0"], BERLIN, _local(2026, 10, 15)) == timedelta(days=7, hours=1)


@pytest.mark.parametrize(
    ("exprs", "label"),
    [
        (["0 8 * * *"], "Täglich 08:00"),
        (["0 18 * * 0"], "Sonntags 18:00"),
        (["0 18 * * 5", "0 18 * * 0"], "Freitags 18:00; Sonntags 18:00"),
        (["0 8,12 * * *", "30 19 * * *"], "Täglich 08:00, 12:00, 19:30"),
        (["30 7 * * 1-5"], "Werktags 07:30"),
        (["0 8-20/2 * * *"], "Alle 2 Stunden, 08–20 Uhr"),
        (["0 */1 * * *"], "Jede Stunde"),
        (["*/15 * * * *"], "Alle 15 Minuten"),
    ],
)
def test_describe(exprs: list[str], label: str) -> None:
    assert describe(exprs, BERLIN) == label
