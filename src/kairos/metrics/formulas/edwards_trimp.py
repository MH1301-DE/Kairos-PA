from __future__ import annotations

from kairos.metrics.hr_zones import HrZoneBounds


def edwards_trimp(bucket_seconds: dict[int, float], zones: list[HrZoneBounds]) -> float:
    total_minutes_weighted = 0.0
    for bpm_bucket, seconds in bucket_seconds.items():
        zone = _zone_for_bucket(float(bpm_bucket), zones)
        if zone is None:
            continue
        total_minutes_weighted += (seconds / 60.0) * zone.multiplier
    return total_minutes_weighted


def _zone_for_bucket(bpm: float, zones: list[HrZoneBounds]) -> HrZoneBounds | None:
    for zone in zones:
        if zone.low_bpm <= bpm < zone.high_bpm:
            return zone
    if zones and bpm >= zones[-1].high_bpm:
        return zones[-1]
    return None
