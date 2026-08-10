from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.monotony_strain import monotony_strain
from kairos.metrics.types import MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series


class MonotonyStrainVariant:
    metric_id = "monotony_strain"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        series = await edwards_daily_load_series(session, user_id=user_id, end_day=as_of, days=7)
        result = monotony_strain(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="monotony_strain", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={"monotony": result.monotony, "strain": result.strain},
            unit="monotony_strain", confidence="high",
            coverage_days=len(series), coverage_required_days=7, as_of=as_of.isoformat(),
        )
