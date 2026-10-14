from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Confidence = Literal["high", "medium", "low", "insufficient_data"]


@dataclass(frozen=True)
class MetricResult:
    value: float | dict[str, float] | None
    unit: str
    confidence: Confidence
    coverage_days: int
    coverage_required_days: int
    as_of: str
    note: str | None = None
