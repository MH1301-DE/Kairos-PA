"""Restricted cron subset and next-run calculation in a job's time zone.

Supported per field: minute and hour accept a number, a list, a range, ``*/N`` and
``A-B/N`` (hour also ``*``); day of month and month only ``*``; weekday ``*``, a number,
a list or a range (0 = Sunday, 7 is accepted as Sunday). ``*/N`` must divide 60 (minutes)
or 24 (hours) -- ``*/45`` would mean ":00 and :45", not "every 45 minutes".

DST rule (PEP 495, ``fold=0``): a wall time that does not exist (spring gap) runs shifted
by the gap's length, a wall time that exists twice (autumn) runs only on its first pass;
intervals are wall-clock based.
"""

from __future__ import annotations

import functools
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

MAX_EXPRESSIONS = 6
_WEEKDAY_NAMES = ("So", "Mo", "Di", "Mi", "Do", "Fr", "Sa")
_WEEKDAY_PLURAL = (
    "Sonntags",
    "Montags",
    "Dienstags",
    "Mittwochs",
    "Donnerstags",
    "Freitags",
    "Samstags",
)


class InvalidSchedule(ValueError):
    pass


@dataclass(frozen=True)
class CronSpec:
    minutes: tuple[int, ...]
    hours: tuple[int, ...]
    weekdays: frozenset[int]
    # original fields, kept for describe()
    minute_field: str
    hour_field: str


def parse(expr: str) -> CronSpec:
    fields = expr.split()
    if len(fields) != 5:
        raise InvalidSchedule(f"„{expr}“: erwartet werden genau 5 Felder")
    minute, hour, dom, month, weekday = fields
    if dom != "*" or month != "*":
        raise InvalidSchedule(f"„{expr}“: Tag und Monat müssen „*“ sein")
    if minute == "*":
        raise InvalidSchedule(f"„{expr}“: „jede Minute“ wird nicht unterstützt")
    return CronSpec(
        minutes=tuple(sorted(_parse_field(minute, 0, 59, 60, "Minute", expr))),
        hours=tuple(sorted(_parse_field(hour, 0, 23, 24, "Stunde", expr))),
        weekdays=frozenset(_parse_weekdays(weekday, expr)),
        minute_field=minute,
        hour_field=hour,
    )


def validate(exprs: list[str], tz: str) -> list[CronSpec]:
    if not 1 <= len(exprs) <= MAX_EXPRESSIONS:
        raise InvalidSchedule(f"1 bis {MAX_EXPRESSIONS} Zeitpläne erlaubt")
    zone(tz)
    return [parse(e) for e in exprs]


def zone(tz: str) -> ZoneInfo:
    if tz not in _timezones():
        raise InvalidSchedule(f"Unbekannte Zeitzone „{tz}“")
    try:
        return ZoneInfo(tz)
    except ZoneInfoNotFoundError as exc:
        raise InvalidSchedule(f"Unbekannte Zeitzone „{tz}“") from exc


def next_occurrence(exprs: list[str], tz: str, after: datetime) -> datetime:
    if after.tzinfo is None:
        raise ValueError("after must be timezone-aware")
    specs = validate(exprs, tz)
    zi = zone(tz)
    day = after.astimezone(zi).date() - timedelta(days=1)
    found: datetime | None = None
    # one extra day after the first hit: DST can reorder wall time vs UTC around midnight
    for offset in range(9):
        candidates = [
            c for c in _day_candidates(specs, zi, day + timedelta(days=offset)) if c > after
        ]
        if candidates:
            best = min(candidates)
            if found is not None:
                return min(found, best)
            found = best
        elif found is not None:
            return found
    if found is None:
        raise InvalidSchedule("Zeitplan ergibt keinen Termin")
    return found


def occurrences(exprs: list[str], tz: str, start: datetime, end: datetime) -> list[datetime]:
    out: list[datetime] = []
    current = start
    while True:
        current = next_occurrence(exprs, tz, current)
        if current > end:
            return out
        out.append(current)


def min_gap(exprs: list[str], tz: str, start: datetime, days: int = 14) -> timedelta:
    runs = occurrences(exprs, tz, start, start + timedelta(days=days))
    if len(runs) < 2:
        return timedelta(days=days)
    return min(b - a for a, b in zip(runs, runs[1:], strict=False))


def describe(exprs: list[str], tz: str) -> str:
    del tz  # labels are wall-clock, the zone is shown separately
    specs = [parse(e) for e in exprs]
    fixed: dict[frozenset[int], list[str]] = {}
    parts: list[str] = []
    for spec in specs:
        days = _describe_days(spec.weekdays)
        interval = _describe_interval(spec)
        if interval is not None:
            parts.append(interval if days == "Täglich" else f"{days}, {interval}")
            continue
        times = [f"{h:02d}:{m:02d}" for h in spec.hours for m in spec.minutes]
        fixed.setdefault(spec.weekdays, []).extend(times)
    fixed_parts = [
        f"{_describe_days(weekdays)} {', '.join(sorted(set(times)))}"
        for weekdays, times in fixed.items()
    ]
    return "; ".join(fixed_parts + parts)


# --- internals ---------------------------------------------------------------------


@functools.cache
def _timezones() -> frozenset[str]:
    return frozenset(available_timezones())


def _day_candidates(specs: list[CronSpec], zi: ZoneInfo, day: date) -> set[datetime]:
    cron_weekday = (day.weekday() + 1) % 7
    out: set[datetime] = set()
    for spec in specs:
        if cron_weekday not in spec.weekdays:
            continue
        for h in spec.hours:
            for m in spec.minutes:
                local = datetime.combine(day, time(h, m), zi).replace(fold=0)
                out.add(local.astimezone(UTC))
    return out


def _parse_field(field: str, lo: int, hi: int, cycle: int, label: str, expr: str) -> set[int]:
    values: set[int] = set()
    for item in field.split(","):
        base, _, step_text = item.partition("/")
        step = 1
        if step_text:
            step = _int(step_text, label, expr)
            if step < 1:
                raise InvalidSchedule(f"„{expr}“: Schrittweite der {label} muss ≥ 1 sein")
        if base == "*":
            if step_text and cycle % step:
                raise InvalidSchedule(
                    f"„{expr}“: „*/{step}“ bei {label}n nur mit Teilern von {cycle}"
                )
            start, end = lo, hi
        elif "-" in base:
            a, b = base.split("-", 1)
            start, end = _int(a, label, expr), _int(b, label, expr)
        else:
            if step_text:
                raise InvalidSchedule(f"„{expr}“: „{item}“ ist keine gültige {label}")
            start = end = _int(base, label, expr)
        if not lo <= start <= end <= hi:
            raise InvalidSchedule(f"„{expr}“: {label} „{item}“ außerhalb von {lo}–{hi}")
        values.update(range(start, end + 1, step))
    return values


def _parse_weekdays(field: str, expr: str) -> set[int]:
    if field == "*":
        return set(range(7))
    if "/" in field:
        raise InvalidSchedule(f"„{expr}“: Schrittweite beim Wochentag nicht erlaubt")
    days: set[int] = set()
    for item in field.split(","):
        if "-" in item:
            a, b = item.split("-", 1)
            start, end = _int(a, "Wochentag", expr), _int(b, "Wochentag", expr)
        else:
            start = end = _int(item, "Wochentag", expr)
        if not 0 <= start <= end <= 7:
            raise InvalidSchedule(f"„{expr}“: Wochentag „{item}“ außerhalb von 0–7")
        days.update(d % 7 for d in range(start, end + 1))
    return days


def _int(text: str, label: str, expr: str) -> int:
    if not text.isdigit():
        raise InvalidSchedule(f"„{expr}“: „{text}“ ist keine gültige {label}")
    return int(text)


def _describe_days(weekdays: frozenset[int]) -> str:
    if len(weekdays) == 7:
        return "Täglich"
    if weekdays == frozenset(range(1, 6)):
        return "Werktags"
    if weekdays == frozenset({0, 6}):
        return "Am Wochenende"
    if len(weekdays) == 1:
        return _WEEKDAY_PLURAL[next(iter(weekdays))]
    # Monday first, Sunday last
    ordered = sorted(weekdays, key=lambda d: (d + 6) % 7)
    return ", ".join(_WEEKDAY_NAMES[d] for d in ordered)


def _describe_interval(spec: CronSpec) -> str | None:
    window = _hour_window(spec.hour_field)
    if spec.minute_field.startswith("*/"):
        return f"Alle {spec.minute_field[2:]} Minuten{window}"
    if "/" in spec.hour_field and len(spec.minutes) == 1:
        step = int(spec.hour_field.split("/", 1)[1])
        unit = "Stunde" if step == 1 else f"{step} Stunden"
        minute = f" (:{spec.minutes[0]:02d})" if spec.minutes[0] else ""
        return f"Jede {unit}{minute}{window}" if step == 1 else f"Alle {unit}{minute}{window}"
    return None


def _hour_window(hour_field: str) -> str:
    base = hour_field.split("/", 1)[0]
    if "-" in base and "," not in base:
        a, b = base.split("-", 1)
        return f", {int(a):02d}–{int(b):02d} Uhr"
    return ""
