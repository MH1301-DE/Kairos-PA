from __future__ import annotations

import math

_COEFFICIENTS = {"male": 0.64, "female": 0.86}
_EXPONENTS = {"male": 1.92, "female": 1.67}


def banister_trimp(
    bucket_seconds: dict[int, float], *, resting_hr: float, hr_max: float, sex: str
) -> float | None:
    if hr_max <= resting_hr:
        return None
    if not bucket_seconds:
        return 0.0

    total_seconds = sum(bucket_seconds.values())
    weighted_bpm = sum(bpm * secs for bpm, secs in bucket_seconds.items()) / total_seconds
    duration_min = total_seconds / 60.0
    delta_ratio = (weighted_bpm - resting_hr) / (hr_max - resting_hr)
    coefficient = _COEFFICIENTS[sex]
    exponent = _EXPONENTS[sex]
    return duration_min * delta_ratio * coefficient * math.exp(exponent * delta_ratio)
