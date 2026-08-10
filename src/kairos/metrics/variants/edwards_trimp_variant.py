from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import estimate_hr_max, percent_max_zones
from kairos.metrics.types import Confidence, MetricResult
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


class EdwardsTrimpVariant:
    metric_id = "trimp"
    variant_id = "edwards"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = percent_max_zones(hr_max)
        value = edwards_trimp(buckets, zones)
        confidence: Confidence = "high" if buckets else "low"
        return MetricResult(
            value=value, unit="trimp_pt", confidence=confidence,
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )


async def edwards_daily_load_series(
    session: AsyncSession, *, user_id: UUID, end_day: date, days: int
) -> dict[date, float]:
    """Canonical training-load series consumed by CTL/ATL/TSB, ACWR, Monotony/Strain."""
    setting = await get_or_default_user_setting(session, user_id=user_id)
    observed_max = await observed_max_hr_ever(session, user_id=user_id)
    hr_max = estimate_hr_max(
        setting.birth_date, setting.hr_max_override, observed_max, as_of=end_day
    )
    if hr_max is None:
        return {}

    zones = percent_max_zones(hr_max)
    start = end_day - timedelta(days=days - 1)
    from kairos.repositories.metrics_data import hr_bucket_seconds_range

    ranged = await hr_bucket_seconds_range(session, user_id=user_id, start=start, end=end_day)
    return {day: edwards_trimp(buckets, zones) for day, buckets in ranged.items()}
