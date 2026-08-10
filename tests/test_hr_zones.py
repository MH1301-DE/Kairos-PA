from __future__ import annotations

from datetime import date

from kairos.metrics.hr_zones import estimate_hr_max, karvonen_zones, percent_max_zones


def test_percent_max_zones_covers_50_to_100_percent() -> None:
    zones = percent_max_zones(hr_max=190.0)

    assert [z.name for z in zones] == ["zone_1", "zone_2", "zone_3", "zone_4", "zone_5"]
    assert zones[0].low_bpm == 95.0  # 50% of 190
    assert zones[4].high_bpm == 190.0  # 100% of 190
    assert [z.multiplier for z in zones] == [1, 2, 3, 4, 5]


def test_karvonen_zones_use_heart_rate_reserve() -> None:
    zones = karvonen_zones(hr_max=190.0, resting_hr=50.0)
    # reserve = 140; zone_1 low = 50 + 140*0.50 = 120
    assert zones[0].low_bpm == 120.0
    assert zones[4].high_bpm == 190.0


def test_estimate_hr_max_prefers_override() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 1, 1), hr_max_override=200, observed_max_hr=180,
        as_of=date(2026, 8, 10),
    )
    assert result == 200


def test_estimate_hr_max_uses_age_formula_when_no_override() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 8, 10), hr_max_override=None, observed_max_hr=None,
        as_of=date(2026, 8, 10),
    )
    assert result == 184  # 220 - 36


def test_estimate_hr_max_raises_estimate_to_observed_max_if_higher() -> None:
    result = estimate_hr_max(
        birth_date=date(1990, 8, 10), hr_max_override=None, observed_max_hr=195,
        as_of=date(2026, 8, 10),
    )
    assert result == 195  # observed effort exceeded the age-based estimate


def test_estimate_hr_max_returns_none_without_any_input() -> None:
    result = estimate_hr_max(
        birth_date=None, hr_max_override=None, observed_max_hr=None, as_of=date(2026, 8, 10)
    )
    assert result is None
