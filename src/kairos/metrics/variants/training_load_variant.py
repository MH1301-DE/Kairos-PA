from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.training_load import training_load
from kairos.metrics.types import Confidence, MetricResult
from kairos.metrics.variants.edwards_trimp_variant import edwards_daily_load_series

_LOOKBACK_DAYS = 90


class TrainingLoadVariant:
    metric_id = "training_load"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        result = await edwards_daily_load_series(
            session, user_id=user_id, end_day=as_of, days=_LOOKBACK_DAYS
        )
        coverage = result.days_with_data
        # not result.series still catches hr_max is None (edwards_daily_load_series short-
        # circuits to an empty dict there); days_with_data == 0 catches the dense-but-all-
        # zero case, where hr_max resolved but the user has no real training data, ever.
        if not result.series or result.days_with_data == 0:
            return MetricResult(
                value=None, unit="ctl_atl_tsb", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=_LOOKBACK_DAYS, as_of=as_of.isoformat(),
            )
        states = training_load(result.series)
        today_state = states[-1]
        confidence: Confidence = "high" if coverage >= 28 else "medium" if coverage >= 7 else "low"
        return MetricResult(
            value={"ctl": today_state.ctl, "atl": today_state.atl, "tsb": today_state.tsb},
            unit="ctl_atl_tsb", confidence=confidence,
            coverage_days=coverage, coverage_required_days=_LOOKBACK_DAYS, as_of=as_of.isoformat(),
        )
