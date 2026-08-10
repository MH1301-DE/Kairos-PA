from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.sleep_debt import sleep_debt


def test_sleep_debt_accumulates_shortfall() -> None:
    start = date(2026, 1, 1)
    nightly = {start + timedelta(days=i): 6.0 for i in range(7)}  # 2h short every night

    result = sleep_debt(nightly, as_of=start + timedelta(days=6), target_hours=8.0)

    assert result == 14.0  # 7 nights * 2h


def test_sleep_debt_surplus_offsets_deficit() -> None:
    start = date(2026, 1, 1)
    nightly = {start + timedelta(days=i): 6.0 for i in range(6)}
    nightly[start + timedelta(days=6)] = 12.0  # one long recovery night

    result = sleep_debt(nightly, as_of=start + timedelta(days=6), target_hours=8.0)

    assert result == 8.0  # 6*2h deficit - 4h surplus


def test_sleep_debt_returns_none_with_no_data_in_window() -> None:
    result = sleep_debt({}, as_of=date(2026, 1, 7), target_hours=8.0)
    assert result is None
