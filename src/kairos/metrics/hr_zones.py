from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal

_ZONE_FRACTIONS: tuple[tuple[float, float, int], ...] = (
    (0.50, 0.60, 1),
    (0.60, 0.70, 2),
    (0.70, 0.80, 3),
    (0.80, 0.90, 4),
    (0.90, 1.00, 5),
)


@dataclass(frozen=True)
class HrZoneBounds:
    name: str
    low_bpm: float
    high_bpm: float
    multiplier: int


def percent_max_zones(hr_max: float) -> list[HrZoneBounds]:
    return [
        HrZoneBounds(f"zone_{i + 1}", hr_max * lo, hr_max * hi, mult)
        for i, (lo, hi, mult) in enumerate(_ZONE_FRACTIONS)
    ]


def karvonen_zones(hr_max: float, resting_hr: float) -> list[HrZoneBounds]:
    reserve = hr_max - resting_hr
    return [
        HrZoneBounds(f"zone_{i + 1}", resting_hr + reserve * lo, resting_hr + reserve * hi, mult)
        for i, (lo, hi, mult) in enumerate(_ZONE_FRACTIONS)
    ]


def zone_seconds(buckets: dict[int, float], zones: list[HrZoneBounds]) -> dict[str, float]:
    out = {zone.name: 0.0 for zone in zones}
    for bpm_bucket, seconds in buckets.items():
        for zone in zones:
            if zone.low_bpm <= bpm_bucket < zone.high_bpm or (
                zone is zones[-1] and bpm_bucket >= zone.high_bpm
            ):
                out[zone.name] += seconds
                break
    return out


HrMaxSource = Literal["eingetragen", "aus Alter"]


def resolve_hr_max(
    birth_date: date | None,
    hr_max_override: int | None,
    *,
    as_of: date,
) -> tuple[int | None, HrMaxSource | None]:
    if hr_max_override is not None:
        return hr_max_override, "eingetragen"
    if birth_date is None:
        return None, None
    age = (
        as_of.year
        - birth_date.year
        - ((as_of.month, as_of.day) < (birth_date.month, birth_date.day))
    )
    return 220 - age, "aus Alter"


def hr_max_warning(
    used: int | None, source: HrMaxSource | None, measured: int | None
) -> str | None:
    if used is not None and measured is not None and measured > used:
        return f"gemessen {measured} bpm, {source} {used} – prüfen"
    return None
