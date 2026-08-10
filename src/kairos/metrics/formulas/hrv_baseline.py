from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

Band = Literal["low", "normal", "high"]


@dataclass(frozen=True)
class HrvBaselineResult:
    today: float
    baseline_mean: float
    baseline_low: float
    baseline_high: float
    band: Band


def hrv_baseline(
    nightly_hrv: dict[date, float],
    *,
    as_of: date,
    window_days: int = 60,
    min_coverage_days: int = 20,
) -> HrvBaselineResult | None:
    if as_of not in nightly_hrv:
        return None

    window_start = as_of - timedelta(days=window_days - 1)
    window_values = [v for d, v in nightly_hrv.items() if window_start <= d <= as_of]
    if len(window_values) < min_coverage_days:
        return None

    mean = statistics.mean(window_values)
    stddev = statistics.pstdev(window_values)
    low, high = mean - stddev, mean + stddev
    today = nightly_hrv[as_of]

    if today < low:
        band: Band = "low"
    elif today > high:
        band = "high"
    else:
        band = "normal"

    return HrvBaselineResult(
        today=today, baseline_mean=mean, baseline_low=low, baseline_high=high, band=band
    )
