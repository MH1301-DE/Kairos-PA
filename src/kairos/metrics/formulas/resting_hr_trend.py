from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class RestingHrTrendResult:
    recent_avg: float
    prior_avg: float
    delta_bpm: float


def resting_hr_trend(
    daily_resting_hr: dict[date, float],
    *,
    as_of: date,
    recent_days: int = 7,
    prior_days: int = 30,
    min_recent_coverage: int = 4,
    min_prior_coverage: int = 15,
) -> RestingHrTrendResult | None:
    recent_start = as_of - timedelta(days=recent_days - 1)
    recent_window = [recent_start + timedelta(days=i) for i in range(recent_days)]
    recent_values = [daily_resting_hr[d] for d in recent_window if d in daily_resting_hr]
    if len(recent_values) < min_recent_coverage:
        return None

    prior_end = recent_start - timedelta(days=1)
    prior_start = prior_end - timedelta(days=prior_days - 1)
    prior_window = [prior_start + timedelta(days=i) for i in range(prior_days)]
    prior_values = [daily_resting_hr[d] for d in prior_window if d in daily_resting_hr]
    if len(prior_values) < min_prior_coverage:
        return None

    recent_avg = sum(recent_values) / len(recent_values)
    prior_avg = sum(prior_values) / len(prior_values)
    return RestingHrTrendResult(
        recent_avg=recent_avg, prior_avg=prior_avg, delta_bpm=recent_avg - prior_avg
    )
