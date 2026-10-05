import json
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_backtest.v32_indicators import add_v32_features


ROOT = Path(__file__).resolve().parents[1]


def _rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_2.json").read_text(encoding="utf-8"))


def _daily(n=80):
    x = np.arange(n, dtype=float)
    return pd.DataFrame({
        "signal_date": pd.date_range("2020-01-01", periods=n, tz="UTC"),
        "close": 200.0 + x,
        "sma20": 180.0 + 0.5*x,
        "sma50": 150.0 + 0.2*x,
        "sma200": 100.0 + 0.05*x,
        "sma20_slope_up": True,
        "crash_free_20d": True,
    })


def test_config_is_frozen_and_ai_disabled():
    rules = _rules()
    assert rules["frozen_before_formal_run"] is True
    assert rules["ai_enabled"] is False
    assert rules["promotion_gates_are_post_backtest_only"] is True


def test_drawdown_gate_has_correct_direction():
    gate = _rules()["promotion_gates"]["maximum_drawdown_minimum"]
    assert -0.25 >= gate
    assert -0.30 >= gate
    assert not (-0.31 >= gate)


def test_v32_features_are_prefix_invariant():
    full = add_v32_features(_daily(), _rules())
    prefix = add_v32_features(_daily().iloc[:60].copy(), _rules())
    columns = [
        "right_60_v32_confirmed", "deep_bear_exit_v32_confirmed",
        "bull_recovery_gate", "recovery_new_bull_daily_condition",
    ]
    pd.testing.assert_frame_equal(
        full.loc[:59, columns].reset_index(drop=True), prefix[columns].reset_index(drop=True)
    )


def test_recovery_gate_uses_requested_trend_conditions():
    out = add_v32_features(_daily(), _rules())
    assert bool(out.iloc[-1]["bull_recovery_gate"])
    assert bool(out.iloc[-1]["recovery_new_bull_daily_condition"])


def test_promotion_terms_absent_from_trading_engine():
    source = (ROOT / "src" / "crypto_backtest" / "v32_engine.py").read_text(encoding="utf-8")
    for term in ("promotion_gates", "maximum_drawdown_minimum", "twr_cagr_minimum", "calmar_minimum"):
        assert term not in source

