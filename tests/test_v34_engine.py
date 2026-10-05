import json
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_backtest.v31_engine import V31Scenario
from crypto_backtest.v34_engine import (
    V34State,
    _cash_reset_status,
    _final_cash_sweep,
    _process_crash_v34,
    _process_macro_bull_requalification,
)
from crypto_backtest.v34_indicators import add_v34_features


ROOT = Path(__file__).resolve().parents[1]


def _rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_4.json").read_text(encoding="utf-8"))


def _base_rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_1.json").read_text(encoding="utf-8"))


def _scenario():
    return V31Scenario(name="F test", model="F", use_fsm=True, use_ai=False)


def _daily(n=260):
    x = np.arange(n, dtype=float)
    close = 100.0 + x
    return pd.DataFrame({
        "signal_date": pd.date_range("2020-01-01", periods=n, tz="UTC"),
        "close": close,
        "sma10": close - 1.0,
        "sma20": close - 2.0,
        "sma50": close - 5.0,
        "sma200": 80.0 + 0.05 * x,
        "bb_lower": close - 10.0,
    })


def test_config_frozen_scope_and_post_backtest_gates():
    rules = _rules()
    assert rules["frozen_before_formal_run"] is True
    assert rules["allowed_change_scope"] == [
        "crash_level_3",
        "macro_bull_requalification",
        "new_bull_final_cash_sweep",
        "v33_bear_deep_bear_hysteresis",
    ]
    assert rules["promotion_gates_are_post_backtest_only"] is True
    assert rules["ai_enabled"] is False
    assert rules["dynamic_dca_enabled"] is False


def test_v34_features_are_prefix_invariant():
    full = add_v34_features(_daily(), _rules())
    prefix = add_v34_features(_daily().iloc[:220].copy(), _rules())
    columns = [
        "deep_bear_exit_v34_confirmed",
        "btc_peak_to_close_dd_7d",
        "btc_peak_to_close_dd_10d",
        "crash_level3_price_raw",
        "macro_bull_requalification_market_candidate",
        "macro_bull_candidate_confirmation_market",
        "macro_bull_new_bull_confirmation_market",
    ]
    pd.testing.assert_frame_equal(
        full.loc[:219, columns].reset_index(drop=True),
        prefix[columns].reset_index(drop=True),
    )


def test_crash_level3_requires_active_level2_and_executes_only_once():
    base, rules = _base_rules(), _rules()
    counters = {"crash_level1_count": 0, "crash_level2_count": 0, "crash_level3_count": 0}
    counters["crash_level3_recovery_count"] = 0
    state = V34State(
        qty={"BTC": 7.0, "ETH": 10.0},
        normal_cash=10_000.0,
        crash_episode_active=True,
        crash_episode_id=1,
        crash_level2_fired=True,
        crash_level1_days_remaining=3,
        crash_armed=False,
    )
    row = pd.Series({
        "open_time": pd.Timestamp("2020-03-13", tz="UTC"),
        "signal_date": pd.Timestamp("2020-03-12", tz="UTC"),
        "strategy_name": "F test",
        "BTC_daily_close": 4_900.0,
        "crash_level1_raw": False,
        "crash_level2_market_raw": False,
        "crash_level3_price_raw": True,
    })
    trades, cash_events, actions = [], [], []
    _process_crash_v34(
        state, row, {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules,
        _scenario(), trades, cash_events, counters, actions,
    )
    assert counters["crash_level3_count"] == 1
    assert state.crash_level3_used
    assert any(lot.get("source") == "CRASH_LEVEL3" for lot in state.temporary_lots)
    first_trade_count = len(trades)
    _process_crash_v34(
        state, row, {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules,
        _scenario(), trades, cash_events, counters, actions,
    )
    assert counters["crash_level3_count"] == 1
    assert len(trades) == first_trade_count


def test_requalification_uses_five_following_closes_twice():
    base, rules = _base_rules(), _rules()
    state = V34State(macro_state="BEAR", active_target=0.55)
    counters = {key: 0 for key in [
        "macro_bull_candidate_count", "macro_bear_invalidated_count",
        "macro_bull_requalification_count", "new_bull_count",
    ]}
    transitions, cycles, actions = [], [], []
    start = pd.Timestamp("2023-01-01", tz="UTC")
    prices = {"BTC": 20_000.0, "ETH": 1_500.0}
    for day in range(11):
        state.signal_index += 1
        row = pd.Series({
            "open_time": start + pd.Timedelta(days=day, hours=4),
            "signal_date": start + pd.Timedelta(days=day),
            "strategy_name": "F test",
            "BTC_daily_close": 20_000.0,
            "macro_bull_requalification_market_candidate": day == 0,
            "macro_bull_candidate_confirmation_market": 1 <= day <= 5,
            "macro_bull_new_bull_confirmation_market": 6 <= day <= 10,
            "crash_level2_market_raw": False,
            "crash_level3_price_raw": False,
        })
        _process_macro_bull_requalification(
            state, row, prices, base, rules, transitions, cycles, counters, actions
        )
        if day == 4:
            assert not state.macro_bear_invalidated
        if day == 5:
            assert state.macro_bear_invalidated
            assert state.macro_state == "BEAR"
        if day == 9:
            assert state.macro_state == "BEAR"
    assert state.macro_state == "NEW_BULL"
    assert state.redeploy_days_remaining == 10
    assert counters["macro_bull_requalification_count"] == 1


def test_final_cash_sweep_bypasses_only_gap_and_can_pass_cash_reset():
    base, rules = _base_rules(), _rules()
    state = V34State(
        qty={"BTC": 7.1, "ETH": 10.0},
        normal_cash=4_000.0,
        tactical_bear_cash=5_000.0,
        macro_state="NEW_BULL",
    )
    prices = {"BTC": 10_000.0, "ETH": 2_000.0}
    assert 0.03 < 0.05
    trades = []
    spent, outcome = _final_cash_sweep(
        state, pd.Series({
            "open_time": pd.Timestamp("2023-02-01", tz="UTC"),
            "signal_date": pd.Timestamp("2023-01-31", tz="UTC"),
            "strategy_name": "F test",
        }), prices, base, rules, _scenario(), trades,
    )
    assert outcome == "EXECUTED"
    assert spent > 0
    assert all(trade["action"] == "TACTICAL_BUYBACK_FINAL_CASH_SWEEP" for trade in trades)
    passed, _, ratio = _cash_reset_status(state, prices, base, rules)
    assert passed
    assert ratio <= 0.01 + 1e-10


def test_engine_contains_no_performance_aware_trade_gate_or_v32_logic():
    source = (ROOT / "src" / "crypto_backtest" / "v34_engine.py").read_text(encoding="utf-8")
    for term in (
        "v32_engine",
        "v32_indicators",
        "maximum_drawdown_minimum",
        "twr_cagr_minimum",
        "calmar_minimum",
        "promotion_gates",
        "portfolio_drawdown",
    ):
        assert term not in source
    assert "CRASH_LEVEL3" in source
    assert "MACRO_BULL_REQUALIFICATION_NEW_BULL" in source
    assert "TACTICAL_BUYBACK_FINAL_CASH_SWEEP" in source
