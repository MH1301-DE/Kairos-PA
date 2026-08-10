from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.hrv_baseline import hrv_baseline
from kairos.metrics.types import MetricResult
from kairos.repositories.metrics_data import wellness_daily_stat_range


class HrvBaselineVariant:
    metric_id = "hrv_baseline"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        start = as_of - timedelta(days=59)
        stats = await wellness_daily_stat_range(
            session, user_id=user_id, metric_code="hrv_5min", start=start, end=as_of
        )
        series = {day: stat.avg for day, stat in stats.items()}
        result = hrv_baseline(series, as_of=as_of)
        if result is None:
            return MetricResult(
                value=None, unit="ms", confidence="insufficient_data",
                coverage_days=len(series), coverage_required_days=20, as_of=as_of.isoformat(),
            )
        return MetricResult(
            value={
                "today": result.today, "baseline_mean": result.baseline_mean,
                "baseline_low": result.baseline_low, "baseline_high": result.baseline_high,
            },
            unit="ms", confidence="high",
            coverage_days=len(series), coverage_required_days=20, as_of=as_of.isoformat(),
        )
