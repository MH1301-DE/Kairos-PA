from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.acwr import acwr
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series


class AcwrVariant:
    metric_id = "acwr"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        series = await edwards_daily_load_series(session, user_id=user_id, end_day=as_of, days=28)
        result = acwr(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="ratio", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={"ratio": result.ratio}, unit="ratio", confidence="high",
            coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
        )
