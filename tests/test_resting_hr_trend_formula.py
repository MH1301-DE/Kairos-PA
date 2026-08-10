from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.resting_hr_trend import resting_hr_trend


def test_resting_hr_trend_detects_improvement() -> None:
    start = date(2026, 1, 1)
    daily = {}
    for i in range(30):  # prior window: days 0-29, all 55 bpm
        daily[start + timedelta(days=i)] = 55.0
    for i in range(30, 37):  # recent window: days 30-36, all 50 bpm
        daily[start + timedelta(days=i)] = 50.0

    result = resting_hr_trend(daily, as_of=start + timedelta(days=36))

    assert result is not None
    assert result.recent_avg == 50.0
    assert result.prior_avg == 55.0
    assert result.delta_bpm == -5.0


def test_resting_hr_trend_returns_none_with_insufficient_recent_coverage() -> None:
    start = date(2026, 1, 1)
    daily = {start + timedelta(days=i): 55.0 for i in range(30)}
    daily[start + timedelta(days=30)] = 50.0  # only 1 of 7 recent days present

    result = resting_hr_trend(daily, as_of=start + timedelta(days=36))

    assert result is None
