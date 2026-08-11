from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.hr_zones import HrZoneBounds, estimate_hr_max, karvonen_zones, percent_max_zones
from kairos.metrics.types import MetricResult
from kairos.metrics.variants._resting_hr import resolve_resting_hr
from kairos.repositories.metrics_data import hr_bucket_seconds, observed_max_hr_ever
from kairos.repositories.user_setting import get_or_default_user_setting


def _zone_seconds(buckets: dict[int, float], zones: list[HrZoneBounds]) -> dict[str, float]:
    out = {zone.name: 0.0 for zone in zones}
    for bpm_bucket, seconds in buckets.items():
        for zone in zones:
            if zone.low_bpm <= bpm_bucket < zone.high_bpm or (
                zone is zones[-1] and bpm_bucket >= zone.high_bpm
            ):
                out[zone.name] += seconds
                break
    return out


class HrZoneDistributionPercentMaxVariant:
    metric_id = "hr_zone_distribution"
    variant_id = "percent_max"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        if hr_max is None:
            return MetricResult(
                value=None, unit="seconds", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = percent_max_zones(hr_max)
        return MetricResult(
            value=_zone_seconds(buckets, zones), unit="seconds",
            confidence="high" if buckets else "low",
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )


class HrZoneDistributionKarvonenVariant:
    metric_id = "hr_zone_distribution"
    variant_id = "karvonen"

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult:
        setting = await get_or_default_user_setting(session, user_id=user_id)
        observed_max = await observed_max_hr_ever(session, user_id=user_id)
        hr_max = estimate_hr_max(
            setting.birth_date, setting.hr_max_override, observed_max, as_of=as_of
        )
        resting_hr = await resolve_resting_hr(
            session, user_id=user_id, override=setting.resting_hr_override, as_of=as_of
        )
        if hr_max is None or resting_hr is None:
            return MetricResult(
                value=None, unit="seconds", confidence="insufficient_data",
                coverage_days=0, coverage_required_days=1, as_of=as_of.isoformat(),
            )
        buckets = await hr_bucket_seconds(session, user_id=user_id, day=as_of)
        zones = karvonen_zones(float(hr_max), resting_hr)
        return MetricResult(
            value=_zone_seconds(buckets, zones), unit="seconds",
            confidence="high" if buckets else "low",
            coverage_days=1 if buckets else 0, coverage_required_days=1, as_of=as_of.isoformat(),
        )
