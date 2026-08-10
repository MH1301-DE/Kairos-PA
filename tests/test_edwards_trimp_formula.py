from __future__ import annotations

from kairos.metrics.formulas.edwards_trimp import edwards_trimp
from kairos.metrics.hr_zones import percent_max_zones


def test_edwards_trimp_weights_each_zone_by_its_multiplier() -> None:
    zones = percent_max_zones(hr_max=190.0)  # zone_1: 95-114, zone_2: 114-133, ...
    # 600s (10 min) at 100 bpm (zone_1, mult=1) + 600s at 120 bpm (zone_2, mult=2)
    buckets = {100: 600.0, 120: 600.0}

    result = edwards_trimp(buckets, zones)

    assert result == 30.0  # 10min*1 + 10min*2


def test_edwards_trimp_ignores_seconds_below_zone_1() -> None:
    zones = percent_max_zones(hr_max=190.0)
    buckets = {60: 3600.0}  # resting HR, below zone_1 (95 bpm)

    result = edwards_trimp(buckets, zones)

    assert result == 0.0
