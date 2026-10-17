"""Reference values -> pace and heart-rate ranges (coach spec 4.3).

Paces come from the published Daniels & Gilbert (1979) formulas, never from book tables
(research 7.4): oxygen cost ``VO2 = -4.60 + 0.182258 v + 0.000104 v^2`` (v in m/min) and the
fraction of VO2max sustainable for t minutes
``0.8 + 0.1894393 e^(-0.012778 t) + 0.2989558 e^(-0.1932605 t)``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from kairos.coach.rules import Zonen

_A, _B, _C = 0.000104, 0.182258, -4.60


def vo2_cost(v_m_per_min: float) -> float:
    return _C + _B * v_m_per_min + _A * v_m_per_min**2


def fraction_sustainable(minutes: float) -> float:
    return (
        0.8 + 0.1894393 * math.exp(-0.012778 * minutes) + 0.2989558 * math.exp(-0.1932605 * minutes)
    )


def vdot_from_race(distance_m: float, seconds: float) -> float:
    """VDOT of a maximal effort over ``distance_m`` (3-15 km per the knowledge base)."""
    if distance_m <= 0 or seconds <= 0:
        raise ValueError("Distanz und Zeit müssen positiv sein")
    minutes = seconds / 60
    return vo2_cost(distance_m / minutes) / fraction_sustainable(minutes)


def velocity_for_vo2(vo2: float) -> float:
    """Inverse of :func:`vo2_cost`: speed in m/min that costs ``vo2`` ml/kg/min."""
    disc = _B**2 - 4 * _A * (_C - vo2)
    return (-_B + math.sqrt(disc)) / (2 * _A)


def pace_s_per_km(vdot: float, pct_vo2max: float) -> float:
    return 1000 / velocity_for_vo2(vdot * pct_vo2max / 100) * 60


def race_time_s(vdot: float, distance_m: float) -> float:
    """Equivalent race time for ``distance_m`` at ``vdot`` (bisection on the race formula)."""
    lo, hi = 60.0, 20 * 3600.0
    for _ in range(80):
        mid = (lo + hi) / 2
        if vdot_from_race(distance_m, mid) > vdot:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def hr_max_estimate(age: int) -> int:
    # Tanaka 2001, same rule as metrics.hr_zones.resolve_hr_max (coach spec 1.3)
    return math.floor(208 - 0.7 * age + 0.5)


@dataclass(frozen=True)
class Target:
    tempo: str
    zone3: str
    # pace in s/km, fast..slow; None without VDOT
    pace: tuple[float, float] | None
    hr: tuple[int, int] | None
    hr_estimated: bool


@dataclass(frozen=True)
class ZoneTable:
    targets: dict[str, Target]

    def zone3(self, tempo: str) -> str:
        target = self.targets.get(tempo)
        return target.zone3 if target else "z1"

    def easy_pace(self) -> float | None:
        target = self.targets.get("E")
        return (target.pace[0] + target.pace[1]) / 2 if target and target.pace else None

    def pace(self, tempo: str) -> float | None:
        target = self.targets.get(tempo)
        return (target.pace[0] + target.pace[1]) / 2 if target and target.pace else None


def build_zone_table(
    *,
    vdot: float | None,
    lthr: float | None,
    hr_max: float | None,
    pace_zones: Zonen,
    lthr_zones: Zonen | None,
    hrmax_zones: Zonen | None,
) -> ZoneTable:
    hr_source: tuple[Zonen, float] | None = None
    estimated = False
    if lthr and lthr_zones is not None:
        hr_source = (lthr_zones, lthr)
    elif hr_max and hrmax_zones is not None:
        hr_source, estimated = (hrmax_zones, hr_max), True
    hr_by_name = (
        {
            z.name: (round(hr_source[1] * z.von / 100), round(hr_source[1] * z.bis / 100))
            for z in hr_source[0].zonen
        }
        if hr_source
        else {}
    )
    targets: dict[str, Target] = {}
    for zone in pace_zones.zonen:
        pace = (pace_s_per_km(vdot, zone.bis), pace_s_per_km(vdot, zone.von)) if vdot else None
        targets[zone.name] = Target(
            tempo=zone.name,
            zone3=zone.zone3,
            pace=pace,
            hr=hr_by_name.get(zone.name),
            hr_estimated=estimated,
        )
    # walking breaks inside repetitions
    targets["G"] = Target(tempo="G", zone3="z1", pace=None, hr=None, hr_estimated=False)
    return ZoneTable(targets)


def format_pace(seconds_per_km: float) -> str:
    total = round(seconds_per_km)
    return f"{total // 60}:{total % 60:02d}"
