from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import percent_max_zones
from kairos.metrics.types import Confidence, MetricResult
from kairos.metrics.variants._hr_max import HR_MAX_MISSING_NOTE, hr_max_for
from kairos.repositories.metrics_data import hr_bucket_seconds, hr_bucket_seconds_range
from kairos.repositories.user_setting import get_or_default_user_setting


class EdwardsTrimpVariant:
    metric_id = "trimp"
    variant_id = "edwards"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        hr_max = hr_max_for(setting, as_of)
        if hr_max is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
                note=HR_MAX_MISSING_NOTE,
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = percent_max_zones(hr_max)
        value = edwards_trimp(buckets, zones)
        confidence: Confidence = "high" if buckets else "low"
        return MetricResult(
            value=value, unit="trimp_pt", confidence=confidence,
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )


@dataclass(frozen=True)
class LoadSeriesResult:
    # dense: every day in [end_day - (days-1), end_day], 0.0-filled for rest days
    series: dict[date, float]
    # count of days within that window that had real (non-imputed) activity data
    days_with_data: int


async def edwards_daily_load_series(
    session: AsyncSession, *, user_id: UUID, end_day: date, days: int
) -> LoadSeriesResult:
    """Canonical training-load series consumed by CTL/ATL/TSB, ACWR, Monotony/Strain."""
    setting = await get_or_default_user_setting(session, user_id=user_id)
    hr_max = hr_max_for(setting, end_day)
    if hr_max is None:
        return LoadSeriesResult(series={}, days_with_data=0)

    zones = percent_max_zones(hr_max)
    start = end_day - timedelta(days=days - 1)
    ranged = await hr_bucket_seconds_range(session, user_id=user_id, start=start, end=end_day)
    # dense: fill every day in the window, not just days with real data, so CTL/ATL/TSB
    # and monotony/strain simulate rest-day decay instead of stalling at the last workout
    dense = {
        start + timedelta(days=i): edwards_trimp(ranged.get(start + timedelta(days=i), {}), zones)
        for i in range(days)
    }
    return LoadSeriesResult(series=dense, days_with_data=len(ranged))
