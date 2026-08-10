from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.resting_hr_trend import resting_hr_trend
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import wellness_daily_stat_range


class RestingHrTrendVariant:
    metric_id = "resting_hr_trend"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        start = as_of - timedelta(days=36)
        stats = await wellness_daily_stat_range(
            session, user_id=user_id, metric_code="hr", start=start, end=as_of
        )
        series = {day: stat.min for day, stat in stats.items()}  # daily min HR as resting-HR proxy
        result = resting_hr_trend(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="bpm", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=19, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={
                "recent_avg": result.recent_avg, "prior_avg": result.prior_avg,
                "delta_bpm": result.delta_bpm,
            },
            unit="bpm", confidence="high",
            coverage_days=len(series), coverage_required_days=19, as_of=as_of.isoformat(),
        )
