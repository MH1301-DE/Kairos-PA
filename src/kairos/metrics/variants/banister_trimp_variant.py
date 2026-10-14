from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.banister_trimp import banister_trimp
from kairos.metrics.types import Confidence, MetricResult
from kairos.metrics.variants._hr_max import HR_MAX_MISSING_NOTE, hr_max_for
from kairos.metrics.variants._resting_hr import resolve_resting_hr
from kairos.repositories.metrics_data import hr_bucket_seconds
from kairos.repositories.user_setting import get_or_default_user_setting


class BanisterTrimpVariant:
    metric_id = "trimp"
    variant_id = "banister"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        hr_max = hr_max_for(setting, as_of)
        resting_hr = await resolve_resting_hr(
            session, user_id=user_id, override=setting.resting_hr_override, as_of=as_of
        )
        if hr_max is None or setting.sex is None or resting_hr is None:
            return MetricResult(
                value=None, unit="trimp_pt", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
                note=HR_MAX_MISSING_NOTE if hr_max is None else None,
            )

        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        value = banister_trimp(
            buckets, resting_hr=resting_hr, hr_max=float(hr_max),
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
