from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class LoadState:
    day: date
    ctl: float
    atl: float
    tsb: float


def training_load(
    daily_load: dict[date, float], *, tau_ctl: int = 42, tau_atl: int = 7
) -> list[LoadState]:
    if not daily_load:
        return []

    start = min(daily_load)
    end = max(daily_load)

    states: list[LoadState] = []
    ctl = 0.0
    atl = 0.0
    day = start
    while day <= end:
        load = daily_load.get(day, 0.0)
        ctl += (load - ctl) / tau_ctl
        atl += (load - atl) / tau_atl
        states.append(LoadState(day=day, ctl=ctl, atl=atl, tsb=ctl - atl))
        day += timedelta(days=1)
    return states
