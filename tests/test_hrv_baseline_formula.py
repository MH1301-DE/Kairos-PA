from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.hrv_baseline import hrv_baseline


def test_hrv_baseline_flags_today_within_normal_band() -> None:
    start = date(2026, 1, 1)
    # 59 history nights alternating 55/65 (mean 60, real stddev ~4.96 pop-wide) —
    # a perfectly flat history makes any nonzero "today" the sole source of
    # variance, so it is *always* >1 stddev out; real variance is required for
    # a "normal" classification to be reachable at all.
    series = {
        start + timedelta(days=i): (55.0 if i % 2 == 0 else 65.0) for i in range(59)
    }
    series[start + timedelta(days=59)] = 60.0  # today, dead center of history spread

    result = hrv_baseline(series, as_of=start + timedelta(days=59))

    assert result is not None
    assert result.band == "normal"


def test_hrv_baseline_flags_today_low() -> None:
    start = date(2026, 1, 1)
    series = {
        start + timedelta(days=i): (55.0 if i % 2 == 0 else 65.0) for i in range(59)
    }
    series[start + timedelta(days=59)] = 20.0  # sharp drop, well below the history spread

    result = hrv_baseline(series, as_of=start + timedelta(days=59))

    assert result is not None
    assert result.band == "low"


def test_hrv_baseline_returns_none_with_insufficient_coverage() -> None:
    start = date(2026, 1, 1)
    series = {start + timedelta(days=i): 60.0 for i in range(10)}

    result = hrv_baseline(series, as_of=start + timedelta(days=9), min_coverage_days=20)

    assert result is None
