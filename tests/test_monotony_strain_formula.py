from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.monotony_strain import monotony_strain


def test_monotony_strain_varied_week() -> None:
    start = date(2026, 1, 1)
    values = [10.0, 20.0, 0.0, 30.0, 10.0, 0.0, 40.0]
    load = {start + timedelta(days=i): v for i, v in enumerate(values)}

    result = monotony_strain(load, as_of=start + timedelta(days=6))

    assert result is not None
    mean = sum(values) / 7
    variance = sum((v - mean) ** 2 for v in values) / 7
    stddev = variance**0.5
    assert result.monotony == mean / stddev
    assert result.strain == sum(values) * result.monotony


def test_monotony_strain_returns_none_for_constant_load() -> None:
    start = date(2026, 1, 1)
    load = {start + timedelta(days=i): 25.0 for i in range(7)}

    result = monotony_strain(load, as_of=start + timedelta(days=6))

    assert result is None


def test_monotony_strain_returns_none_with_insufficient_coverage() -> None:
    load = {date(2026, 1, 1): 10.0, date(2026, 1, 2): 20.0}

    result = monotony_strain(load, as_of=date(2026, 1, 2))

    assert result is None
