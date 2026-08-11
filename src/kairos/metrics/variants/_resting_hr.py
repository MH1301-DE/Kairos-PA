from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.repositories.metrics_data import wellness_daily_stat_range

_FALLBACK_WINDOW_DAYS = 7


async def resolve_resting_hr(
    session: AsyncSession, *, user_id: UUID, override: int | None, as_of: date
) -> float | None:
    """override wins; else the observed daily-min HR proxy (same source as resting_hr_trend)."""
    if override is not None:
        return float(override)
    start = as_of - timedelta(days=_FALLBACK_WINDOW_DAYS - 1)
    stats = await wellness_daily_stat_range(
        session, user_id=user_id, metric_code="hr", start=start, end=as_of
    )
    if not stats:
        return None
    return min(stat.min for stat in stats.values())
