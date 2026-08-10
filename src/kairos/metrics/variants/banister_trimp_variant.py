from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.banister_trimp import banister_trimp
from kairos.metrics.hr_zones import estimate_hr_max
from kairos.metrics.types import Confidence, MetricResult
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


class BanisterTrimpVariant:
    metric_id = "trimp"
    variant_id = "banister"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None or setting.sex is None or setting.resting_hr_override is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        value = banister_trimp(
            buckets, resting_hr=float(setting.resting_hr_override), hr_max=float(hr_max),
            sex=setting.sex,
        )
        if value is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        confidence: Confidence = "high" if buckets else "low"
        return MetricResult(
            value=value, unit="trimp_pt", confidence=confidence,
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )
