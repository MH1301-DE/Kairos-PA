from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.acwr import acwr
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series

_ACUTE_DAYS = 7
_CHRONIC_DAYS = 28


class AcwrVariant:
    metric_id = "acwr"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        load = await edwards_daily_load_series(
            session, user_id=user_id, end_day=as_of, days=_CHRONIC_DAYS
        )
        # acwr()'s own coverage gate counts days present in the dict, which is always
        # every day now that the series is dense — gate on real-data days ourselves first,
        # otherwise a brand-new user with almost no history would never get insufficient_data
        if load.days_with_data < _ACUTE_DAYS:
            return MetricResult(
                value=None, unit="ratio", confidence="insufficient_data",
                coverage_days=load.days_with_data, coverage_required_days=_ACUTE_DAYS,
                as_of=as_of.isoformat(),
            )
        result = acwr(load.series, as_of=as_of, acute_days=_ACUTE_DAYS, chronic_days=_CHRONIC_DAYS)
        if result is None:
            return MetricResult(
                value=None, unit="ratio", confidence="insufficient_data",
                coverage_days=load.days_with_data, coverage_required_days=_ACUTE_DAYS,
                as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={"ratio": result.ratio}, unit="ratio", confidence="high",
            coverage_days=load.days_with_data, coverage_required_days=_ACUTE_DAYS,
            as_of=as_of.isoformat(),
        )
