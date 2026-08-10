from __future__ import annotations

from datetime import date, timedelta


def sleep_debt(
    nightly_hours: dict[date, float], *, as_of: date, target_hours: float, window_days: int = 7
) -> float | None:
    start = as_of - timedelta(days=window_days - 1)
    window = [start + timedelta(days=i) for i in range(window_days)]
    covered = [d for d in window if d in nightly_hours]
    if not covered:
        return None

    return sum(target_hours - nightly_hours[d] for d in covered)
