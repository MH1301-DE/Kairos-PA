from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from kairos.auth.deps import current_user
from kairos.db.rls import install_rls_listener
from kairos.db.session import get_session
from kairos.metrics.bootstrap import build_default_registry
from kairos.metrics.registry import MetricRegistry
from kairos.repositories.metrics_recompute import (
    recompute_hr_bucket_seconds_daily,
    recompute_metric_daily_values,
    recompute_wellness_daily_stats,
)

router = APIRouter(prefix="/api/metrics", tags=["metrics"])

_registry: MetricRegistry = build_default_registry()

# nothing in the ingestion pipeline calls metrics_recompute automatically --
# the daily-aggregate tables that feed every dashboard tile stay empty after
# a sync unless something calls this. 2 years matches the current default
# backfill window (see routers/sync.py _DEFAULT_BACKFILL_MONTHS).
_RECOMPUTE_DEFAULT_DAYS = 730


@router.post("/recompute")
async def recompute_metrics(
    from_date: date | None = None,
    to_date: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)
    end = to_date or date.today()
    start = from_date or (end - timedelta(days=_RECOMPUTE_DEFAULT_DAYS))
    await recompute_wellness_daily_stats(session, user_id=user_id, start=start, end=end)
    await recompute_hr_bucket_seconds_daily(session, user_id=user_id, start=start, end=end)
    await recompute_metric_daily_values(session, user_id=user_id, start=start, end=end)
    await session.commit()
    return {"status": "ok", "from_date": start.isoformat(), "to_date": end.isoformat()}


@router.get("")
async def list_metrics(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
    del user
    return {"metric_ids": _registry.metric_ids()}


@router.get("/{metric_id}/variants")
async def list_variants(
    metric_id: str,
    user: dict[str, Any] = Depends(current_user),
) -> dict[str, Any]:
    del user
    variants = _registry.variants_for(metric_id)
    if not variants:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric_id}")
    return {"variants": variants}


@router.get("/{metric_id}")
async def get_metric(
    metric_id: str,
    variant: str | None = None,
    as_of: date | None = None,
    user: dict[str, Any] = Depends(current_user),
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    user_id = UUID(user["user_id"])
    install_rls_listener(session, user_id)

    variants = _registry.variants_for(metric_id)
    if not variants:
        raise HTTPException(status_code=404, detail=f"Unknown metric: {metric_id}")
    chosen_variant = variant or variants[0]
    if chosen_variant not in variants:
        raise HTTPException(status_code=404, detail=f"Unknown variant: {chosen_variant}")

    result = await _registry.get(metric_id, chosen_variant).compute(
        session, user_id=user_id, as_of=as_of or date.today()
    )
    return {
        "metric_id": metric_id,
        "variant": chosen_variant,
        "value": result.value,
        "unit": result.unit,
        "confidence": result.confidence,
        "coverage_days": result.coverage_days,
        "coverage_required_days": result.coverage_required_days,
        "as_of": result.as_of,
    }
