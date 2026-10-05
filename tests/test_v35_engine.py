import json
from pathlib import Path

import numpy as np
import pandas as pd

from crypto_backtest.v31_engine import V31Scenario
from crypto_backtest.v35_engine import (
    V35State,
    _end_episode_on_new_bull,
    _hard_failure_one_rung,
    _update_value_rearm,
    _value_base_buyback,
)
from crypto_backtest.v35_indicators import add_v35_features


ROOT = Path(__file__).resolve().parents[1]


def _rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_5.json").read_text(encoding="utf-8"))


def _v34_rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_4.json").read_text(encoding="utf-8"))


def _base_rules():
    return json.loads((ROOT / "config" / "config_frozen_v3_1.json").read_text(encoding="utf-8"))


def _scenario():
    return V31Scenario(name="G test", model="G", use_fsm=True, use_ai=False)


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


def _row(timestamp="2022-06-20", **updates):
    row = {
        "open_time": pd.Timestamp(timestamp, tz="UTC"),
        "signal_date": pd.Timestamp(timestamp, tz="UTC") - pd.Timedelta(days=1),
        "strategy_name": "G test",
        "BTC_daily_close": 20_000.0,
        "new_20d_low": False,
    }
    row.update(updates)
    return pd.Series(row)


def test_config_frozen_scope_and_patch_d_is_a_separate_version():
    rules = _rules()
    assert rules["frozen_before_formal_run"] is True
    assert rules["schema_version"] == "3.5"
    assert rules["allowed_change_scope"] == ["accumulation_anti_whipsaw_patch_d"]
    assert rules["evaluation_gates_are_post_backtest_only"] is True
    assert rules["base_config_sha256"] == "8782f23a9edd30b8bb8d22cd06accb8f91675f08d2d63542dc65c84fe504aa85"


def test_v35_features_are_prefix_invariant():
    full = add_v35_features(_daily(), _v34_rules(), _rules())
    prefix = add_v35_features(_daily().iloc[:220].copy(), _v34_rules(), _rules())
    columns = [
        "no_new_20d_low_5d",
        "no_new_20d_low_10d",
        "patch_d_right_50_confirmed",
        "patch_d_right_60_confirmed",
        "patch_d_hard_failure_confirmed",
    ]
    pd.testing.assert_frame_equal(
        full.loc[:219, columns].reset_index(drop=True),
        prefix[columns].reset_index(drop=True),
    )


def test_value_base_buy_is_one_time_within_cooldown_and_episode():
    base, rules = _base_rules(), _rules()
    state = V35State(
        qty={"BTC": 0.5, "ETH": 5.0},
        normal_cash=10_000.0,
        tactical_bear_cash=50_000.0,
        macro_state="DEEP_BEAR",
        active_target=0.25,
    )
    counters = {"value_buyback_count": 0, "patch_d_bottom_buy_count": 0}
    trades, transitions, cycles, actions = [], [], [], []
    first = _value_base_buyback(
        state, _row(), {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules,
        _scenario(), trades, transitions, cycles, counters, actions,
    )
    assert first
    assert state.active_target == 0.35
    assert state.accumulation_episode_id == 1
    trade_count = len(trades)
    second = _value_base_buyback(
        state, _row("2022-06-21"), {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules,
        _scenario(), trades, transitions, cycles, counters, actions,
    )
    assert not second
    assert len(trades) == trade_count
    assert "VALUE_BASE_BUYBACK_BLOCKED_COOLDOWN" in actions


def test_hard_failure_can_move_only_one_ladder_rung():
    base, rules = _base_rules(), _rules()
    state = V35State(
        qty={"BTC": 6.0, "ETH": 15.0},
        normal_cash=10_000.0,
        macro_state="ACCUMULATION",
        active_target=0.50,
        accumulation_episode_active=True,
        accumulation_episode_id=1,
    )
    counters = {"patch_d_bottom_sell_count": 0}
    trades, transitions, cycles, actions = [], [], [], []
    _hard_failure_one_rung(
        state, _row(), {"BTC": 10_000.0, "ETH": 2_000.0}, base, rules,
        _scenario(), trades, transitions, cycles, counters, actions,
    )
    assert state.active_target == 0.35
    assert state.macro_state == "ACCUMULATION"
    assert counters["patch_d_bottom_sell_count"] == 1
    assert {trade["action"] for trade in trades} == {"TACTICAL_SELL_PATCH_D_HARD_FAILURE_TO_35"}


def test_value_rearm_needs_wait_new_low_and_three_following_closes():
    state = V35State(
        macro_state="DEEP_BEAR",
        active_target=0.25,
        accumulation_episode_active=True,
        accumulation_episode_id=1,
        value_base_buyback_used=True,
        last_value_buyback_at=pd.Timestamp("2022-06-01", tz="UTC"),
    )
    actions = []
    _update_value_rearm(state, _row("2022-06-14", new_20d_low=True), _rules(), actions)
    assert not state.value_rearm_new_low_seen
    _update_value_rearm(state, _row("2022-06-15", new_20d_low=True), _rules(), actions)
    assert state.value_rearm_new_low_seen
    for day in (16, 17):
        _update_value_rearm(state, _row(f"2022-06-{day:02d}"), _rules(), actions)
        assert not state.value_buyback_rearmed
    _update_value_rearm(state, _row("2022-06-18"), _rules(), actions)
    assert state.value_buyback_rearmed


def test_new_bull_closes_episode_and_allows_a_fresh_future_episode():
    state = V35State(
        accumulation_episode_active=True,
        accumulation_episode_id=4,
        value_base_buyback_used=True,
        deep_value_confidence=True,
        sticky_accumulation_base=True,
        hard_failure_confirmed=True,
        last_value_buyback_at=pd.Timestamp("2022-06-01", tz="UTC"),
        last_accumulation_action_at=pd.Timestamp("2022-06-01", tz="UTC"),
    )
    _end_episode_on_new_bull(state)
    assert not state.accumulation_episode_active
    assert not state.value_base_buyback_used
    assert not state.sticky_accumulation_base
    assert state.last_value_buyback_at is None
    assert state.last_accumulation_action_at is None


def test_engine_has_no_audit_dates_or_performance_aware_trade_gate():
    source = (ROOT / "src" / "crypto_backtest" / "v35_engine.py").read_text(encoding="utf-8")
    for term in (
        "2022-06-01",
        "2026-02-01",
        "evaluation_gates",
        "bottom_whipsaw_pair_reduction",
        "final_value_minimum_fraction",
        "maximum_drawdown_minimum",
        "twr_cagr_minimum",
        "calmar_minimum",
    ):
        assert term not in source
    assert "TACTICAL_BUYBACK_PATCH_D_VALUE_BASE_35" in source
    assert "TACTICAL_SELL_PATCH_D_HARD_FAILURE" in source
