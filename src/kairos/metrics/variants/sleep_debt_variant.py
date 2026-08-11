from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.formulas.sleep_debt import sleep_debt
from kairos.metrics.types import Confidence, MetricResult
from kairos.repositories.metrics_data import sleep_hours_range
from kairos.repositories.user_setting import get_or_default_user_setting


class SleepDebtVariant:
    metric_id = "sleep_debt"
    variant_id = "default"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        start = as_of - timedelta(days=6)
        nightly = await sleep_hours_range(session, user_id=user_id, start=start, end=as_of)

        value = sleep_debt(nightly, as_of=as_of, target_hours=setting.sleep_target_hours)
        if value is None:
            return MetricResult(
                value=None, unit="hours", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        confidence: Confidence = (
            "high" if len(nightly) >= 5 else "medium" if len(nightly) >= 3 else "low"
        )
        return MetricResult(
            value=value, unit="hours", confidence=confidence,
            coverage_days=len(nightly), coverage_required_days=7, as_of=as_of.isoformat(),
        )
