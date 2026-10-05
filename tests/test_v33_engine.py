import json
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_backtest.v31_engine import V31Scenario
from crypto_backtest.v33_engine import V33State, _process_accumulation_drift
from crypto_backtest.v33_indicators import add_v33_features


ROOT = Path(__file__).resolve().parents[1]


def _rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_3.json").read_text(encoding="utf-8"))


def _base_rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_1.json").read_text(encoding="utf-8"))


def _daily(n=80):
    x = np.arange(n, dtype=float)
    return pd.DataFrame({
        "signal_date": pd.date_range("2020-01-01", periods=n, tz="UTC"),
        "close": 200.0 + x, "sma20": 180.0 + 0.5 * x,
        "sma50": 150.0 + 0.2 * x, "sma200": 100.0 + 0.05 * x,
    })


def test_config_is_frozen_and_scope_is_exact():
    rules = _rules()
    assert rules["frozen_before_formal_run"] is True
    assert rules["ai_enabled"] is False
    assert rules["dynamic_dca_enabled"] is False
    assert rules["promotion_gates_are_post_backtest_only"] is True
    assert rules["allowed_change_scope"] == [
        "accumulation_exposure_drift_cap",
        "bear_deep_bear_hysteresis",
        "new_bull_cycle_close_reset_audit",
    ]


def test_drawdown_gate_direction_and_boundaries():
    gate = _rules()["promotion_gates"]["maximum_drawdown_minimum"]
    assert -0.25 >= gate
    assert -0.30 >= gate
    assert not (-0.31 >= gate)


def test_v33_features_are_prefix_invariant():
    full = add_v33_features(_daily(), _rules())
    prefix = add_v33_features(_daily().iloc[:60].copy(), _rules())
    columns = [
        "close_above_sma50_5d", "sma20_up_5d", "new_20d_low",
        "no_new_20d_low", "deep_bear_exit_v33_confirmed",
    ]
    pd.testing.assert_frame_equal(
        full.loc[:59, columns].reset_index(drop=True), prefix[columns].reset_index(drop=True)
    )


def test_accumulation_drift_requires_three_completed_observations_and_sells_to_target_plus_5pp():
    base, rules = _base_rules(), _rules()
    scenario = V31Scenario(name="E test", model="E", use_fsm=True, use_ai=False)
    state = V33State(
        qty={"BTC": 3.75, "ETH": 11.25}, normal_cash=40_000.0,
        macro_state="ACCUMULATION", active_target=0.35,
    )
    prices = {"BTC": 10_000.0, "ETH": 2_000.0}
    trades, actions = [], []
    counters = {"accumulation_drift_sell_count": 0}
    audits = []
    for day in range(3):
        row = pd.Series({
            "open_time": pd.Timestamp("2020-01-02", tz="UTC") + pd.Timedelta(days=day),
            "signal_date": pd.Timestamp("2020-01-01", tz="UTC") + pd.Timedelta(days=day),
            "strategy_name": "E test",
        })
        audits.append(_process_accumulation_drift(
            state, row, prices, base, rules, scenario, trades, counters, actions,
            observed_state="ACCUMULATION", observed_target=0.35, observed_exposure=0.60,
        ))
    assert not audits[0]["drift_sell_triggered"]
    assert not audits[1]["drift_sell_triggered"]
    assert audits[2]["drift_sell_triggered"]
    assert audits[2]["days_above_upper_band"] == 3
    assert abs(audits[2]["post_trade_exposure"] - 0.40) < 0.002
    assert counters["accumulation_drift_sell_count"] == 1


def test_accumulation_lock_blocks_ordinary_drift_sell():
    base, rules = _base_rules(), _rules()
    scenario = V31Scenario(name="E test", model="E", use_fsm=True, use_ai=False)
    state = V33State(
        qty={"BTC": 3.75, "ETH": 11.25}, normal_cash=40_000.0,
        macro_state="ACCUMULATION", active_target=0.35,
        accumulation_above_upper_days=2,
        accumulation_lock_until=pd.Timestamp("2020-02-01", tz="UTC"),
    )
    row = pd.Series({
        "open_time": pd.Timestamp("2020-01-10", tz="UTC"),
        "signal_date": pd.Timestamp("2020-01-09", tz="UTC"), "strategy_name": "E test",
    })
    trades, actions = [], []
    audit = _process_accumulation_drift(
        state, row, {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules, scenario,
        trades, {"accumulation_drift_sell_count": 0}, actions,
        observed_state="ACCUMULATION", observed_target=0.35, observed_exposure=0.60,
    )
    assert not audit["drift_sell_triggered"]
    assert audit["lock_active"]
    assert trades == []


def test_v33_engine_has_no_v32_or_promotion_logic():
    source = (ROOT / "src" / "crypto_backtest" / "v33_engine.py").read_text(encoding="utf-8")
    for term in (
        "v32_engine", "v32_indicators", "BULL_RECOVERY_GATE", "right_60_v32",
        "recovery_mode", "promotion_gates", "maximum_drawdown_minimum",
        "twr_cagr_minimum", "calmar_minimum",
    ):
        assert term not in source
    assert "drawdown_cycle_acceleration" in source
    assert "TEN_DAY_NEW_BULL_REDEPLOY" in source
    assert "on_new_bull_confirmed_status" in source
    assert "CLOSING_NEW_BULL_AT_END" in source
