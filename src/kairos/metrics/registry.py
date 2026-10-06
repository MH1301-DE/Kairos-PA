from __future__ import annotations

from datetime import date
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kairos.metrics.types import MetricResult

# Edwards is the canonical TRIMP; Banister needs user_setting.sex and is often insufficient_data
_PREFERRED_DEFAULT_VARIANTS = {"trimp": "edwards", "hr_zone_distribution": "percent_max"}


class MetricVariant(Protocol):
    metric_id: str
    variant_id: str

    async def compute(
        self, session: AsyncSession, *, user_id: UUID, as_of: date
    ) -> MetricResult: ...


class MetricRegistry:
    def __init__(self) -> None:
        self._variants: dict[tuple[str, str], MetricVariant] = {}

    def register(self, variant: MetricVariant) -> None:
        key = (variant.metric_id, variant.variant_id)
        if key in self._variants:
            raise ValueError(f"Metric variant already registered: {key}")
        self._variants[key] = variant

    def get(self, metric_id: str, variant_id: str) -> MetricVariant:
        return self._variants[(metric_id, variant_id)]

    def variants_for(self, metric_id: str) -> list[str]:
        return sorted(v for (m, v) in self._variants if m == metric_id)

    def default_variant(self, metric_id: str) -> str:
        variants = self.variants_for(metric_id)
        if not variants:
            raise KeyError(metric_id)
        preferred = _PREFERRED_DEFAULT_VARIANTS.get(metric_id)
        return preferred if preferred in variants else variants[0]

    def metric_ids(self) -> list[str]:
        return sorted({m for (m, _v) in self._variants})
