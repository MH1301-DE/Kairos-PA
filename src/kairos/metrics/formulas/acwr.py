from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

RiskBand = Literal["undertraining", "sweet_spot", "caution", "high_risk"]


@dataclass(frozen=True)
class AcwrResult:
    ratio: float
    risk_band: RiskBand


def acwr(
    daily_load: dict[date, float],
    *,
    as_of: date,
    acute_days: int = 7,
    chronic_days: int = 28,
) -> AcwrResult | None:
    chronic_start = as_of - timedelta(days=chronic_days - 1)
    chronic_window_days = [chronic_start + timedelta(days=i) for i in range(chronic_days)]
    covered = sum(1 for d in chronic_window_days if d in daily_load)
    if covered < acute_days:
        return None

    acute_start = as_of - timedelta(days=acute_days - 1)
    acute_values = [daily_load.get(acute_start + timedelta(days=i), 0.0) for i in range(acute_days)]
    chronic_values = [daily_load.get(d, 0.0) for d in chronic_window_days]

    acute_mean = sum(acute_values) / acute_days
    chronic_mean = sum(chronic_values) / chronic_days
    if chronic_mean == 0.0:
        return None

    ratio = acute_mean / chronic_mean
    return AcwrResult(ratio=ratio, risk_band=_risk_band(ratio))


def _risk_band(ratio: float) -> RiskBand:
    if ratio < 0.8:
        return "undertraining"
    if ratio <= 1.3:
        return "sweet_spot"
    if ratio <= 1.5:
        return "caution"
    return "high_risk"
