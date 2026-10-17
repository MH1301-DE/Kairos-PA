from __future__ import annotations

from datetime import date

from kairos.metrics.hr_zones import (
    hr_max_warning,
    karvonen_zones,
    percent_max_zones,
    resolve_hr_max,
)


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


def test_hr_max_override_wins_over_measured_and_age() -> None:
    assert resolve_hr_max(date(1990, 1, 1), 214, as_of=date(2026, 8, 10)) == (214, "eingetragen")


def test_hr_max_from_birth_date_only() -> None:
    # Tanaka: 208 - 0.7 x 36 = 182.8
    assert resolve_hr_max(date(1990, 8, 10), None, as_of=date(2026, 8, 10)) == (183, "aus Alter")


def test_hr_max_without_inputs_is_none() -> None:
    assert resolve_hr_max(None, None, as_of=date(2026, 8, 10)) == (None, None)


def test_hr_max_warning_when_measured_exceeds_used() -> None:
    assert hr_max_warning(214, "eingetragen", 219) == "gemessen 219 bpm, eingetragen 214 – prüfen"
    assert hr_max_warning(214, "eingetragen", 214) is None
    assert hr_max_warning(None, None, 219) is None
    assert hr_max_warning(214, "eingetragen", None) is None
