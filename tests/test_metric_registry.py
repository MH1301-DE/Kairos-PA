from __future__ import annotations

from datetime import date
from uuid import UUID, uuid4

import pytest

from kairos.metrics.registry import MetricRegistry
from kairos.metrics.types import MetricResult


class _StubVariant:
    def __init__(self, metric_id: str, variant_id: str) -> None:
        self.metric_id = metric_id
        self.variant_id = variant_id

    async def compute(self, session: object, *, user_id: UUID, as_of: date) -> MetricResult:
        del session, user_id, as_of
        return MetricResult(
            value=1.0, unit="pt", confidence="high", coverage_days=7,
            coverage_required_days=7, as_of="2026-08-10",
        )


def test_register_and_get_variant() -> None:
    registry = MetricRegistry()
    variant = _StubVariant("trimp", "edwards")
    registry.register(variant)

    assert registry.get("trimp", "edwards") is variant
    assert registry.variants_for("trimp") == ["edwards"]
    assert registry.metric_ids() == ["trimp"]


def test_register_duplicate_raises() -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant("trimp", "edwards"))

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_StubVariant("trimp", "edwards"))


@pytest.mark.asyncio
async def test_compute_returns_metric_result() -> None:
    registry = MetricRegistry()
    registry.register(_StubVariant("trimp", "edwards"))

    result = await registry.get("trimp", "edwards").compute(
        session=None, user_id=uuid4(), as_of=date(2026, 8, 10)
    )

    assert result.confidence == "high"
    assert result.value == 1.0
