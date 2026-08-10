from __future__ import annotations

import math

from kairos.metrics.formulas.banister_trimp import banister_trimp


def test_banister_trimp_male_formula() -> None:
    # 30 min at a constant 140 bpm; resting=50, max=190 -> delta_ratio=(140-50)/(190-50)=0.6429
    buckets = {140: 1800.0}

    result = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="male")

    delta = (140 - 50) / (190 - 50)
    expected = 30.0 * delta * 0.64 * math.exp(1.92 * delta)
    assert result is not None
    assert math.isclose(result, expected, rel_tol=1e-9)


def test_banister_trimp_female_uses_different_coefficients() -> None:
    buckets = {140: 1800.0}

    male = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="male")
    female = banister_trimp(buckets, resting_hr=50.0, hr_max=190.0, sex="female")

    assert male != female


def test_banister_trimp_returns_none_when_hr_max_equals_resting_hr() -> None:
    result = banister_trimp({140: 600.0}, resting_hr=190.0, hr_max=190.0, sex="male")
    assert result is None


def test_banister_trimp_returns_zero_for_no_data() -> None:
    result = banister_trimp({}, resting_hr=50.0, hr_max=190.0, sex="male")
    assert result == 0.0
