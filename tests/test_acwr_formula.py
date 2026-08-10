from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.acwr import acwr


def _series(start: date, values: list[float]) -> dict[date, float]:
    return {start + timedelta(days=i): v for i, v in enumerate(values)}


def test_acwr_sweet_spot_when_acute_matches_chronic() -> None:
    start = date(2026, 1, 1)
    load = _series(start, [50.0] * 28)

    result = acwr(load, as_of=start + timedelta(days=27), acute_days=7, chronic_days=28)

    assert result is not None
    assert 0.9 <= result.ratio <= 1.1
    assert result.risk_band == "sweet_spot"


def test_acwr_high_risk_on_load_spike() -> None:
    start = date(2026, 1, 1)
    load = _series(start, [20.0] * 21 + [80.0] * 7)  # 28 days, last 7 spiked

    result = acwr(load, as_of=start + timedelta(days=27), acute_days=7, chronic_days=28)

    assert result is not None
    assert result.ratio > 1.5
    assert result.risk_band == "high_risk"


def test_acwr_returns_none_with_insufficient_history() -> None:
    load = {date(2026, 1, 1): 50.0, date(2026, 1, 2): 50.0}

    result = acwr(load, as_of=date(2026, 1, 2), acute_days=7, chronic_days=28)

    assert result is None
