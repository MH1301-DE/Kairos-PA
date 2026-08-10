from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class MonotonyStrainResult:
    monotony: float
    strain: float


def monotony_strain(
    daily_load: dict[date, float], *, as_of: date, window_days: int = 7
) -> MonotonyStrainResult | None:
    start = as_of - timedelta(days=window_days - 1)
    window = [start + timedelta(days=i) for i in range(window_days)]
    if any(d not in daily_load for d in window):
        return None

    values = [daily_load[d] for d in window]
    stddev = statistics.pstdev(values)
    if stddev == 0.0:
        return None

    monotony = statistics.mean(values) / stddev
    strain = sum(values) * monotony
    return MonotonyStrainResult(monotony=monotony, strain=strain)
