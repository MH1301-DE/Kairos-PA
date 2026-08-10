from __future__ import annotations

from datetime import date, timedelta

from kairos.metrics.formulas.training_load import training_load


def test_training_load_ewma_converges_toward_constant_load() -> None:
    start = date(2026, 1, 1)
    daily_load = {start + timedelta(days=i): 50.0 for i in range(100)}

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    assert len(states) == 100
    # after 100 days of constant load, EWMA converges but doesn't reach equilibrium yet
    # CTL with tau=42: ~91% converged, ATL with tau=7: ~99.9% converged
    assert abs(states[-1].ctl - 50.0) < 5.0
    assert abs(states[-1].atl - 50.0) < 0.1
    assert abs(states[-1].tsb - 0.0) < 5.0


def test_training_load_tsb_is_ctl_minus_atl_same_day() -> None:
    start = date(2026, 1, 1)
    daily_load = {start: 100.0, start + timedelta(days=1): 0.0}

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    for state in states:
        assert state.tsb == state.ctl - state.atl


def test_training_load_fills_gaps_with_zero() -> None:
    start = date(2026, 1, 1)
    daily_load = {start: 100.0, start + timedelta(days=2): 100.0}  # day+1 missing

    states = training_load(daily_load, tau_ctl=42, tau_atl=7)

    assert [s.day for s in states] == [start, start + timedelta(days=1), start + timedelta(days=2)]
    # day+1 had zero load, so ATL should dip between day 0 and day 2
    assert states[1].atl < states[0].atl
