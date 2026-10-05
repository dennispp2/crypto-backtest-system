from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from crypto_backtest.v3_engine import (  # noqa: E402
    V3Scenario,
    V3State,
    _process_signal,
    _record_stage,
    _stage_target,
    _transition,
)
from crypto_backtest.v3_indicators import add_v3_macro_features  # noqa: E402


@pytest.fixture
def rules() -> dict:
    return json.loads((PROJECT / "config" / "config_frozen_v3.json").read_text(encoding="utf-8"))


def test_fsm_rejects_unlisted_transition(rules: dict) -> None:
    state = V3State(macro_regime="BULL")
    with pytest.raises(AssertionError, match="Illegal FSM transition"):
        _transition(state, "BEAR", "unit_test", rules)


def test_stage4_sensitivity_changes_only_floor_target(rules: dict) -> None:
    values = [
        _stage_target(4, V3Scenario(name=f"E{int(100 * floor)}", hard_floor=floor), rules)
        for floor in rules["hard_floors"]
    ]
    assert values == [0.25, 0.35, 0.45]
    for stage, expected in [(1, 0.85), (2, 0.70), (3, 0.55)]:
        assert {
            _stage_target(stage, V3Scenario(name="test", hard_floor=floor), rules)
            for floor in rules["hard_floors"]
        } == {expected}


def _signal_row(**overrides: object) -> pd.Series:
    values: dict[str, object] = {
        "open_time": pd.Timestamp("2024-01-02", tz="UTC"),
        "signal_date": pd.Timestamp("2024-01-01", tz="UTC"),
        "BTC_daily_close": 100.0,
        "BTC_daily_low": 95.0,
        "sma20": 100.0,
        "sma50": 100.0,
        "sma200": 100.0,
        "bb_lower": 80.0,
        "ahr999_fixed_arithmetic": 1.0,
        "peak_to_close_drawdown_90d": -0.10,
        "bull_condition": True,
        "late_bull_condition": False,
        "distribution_confirmed": False,
        "distribution_invalidation_confirmed": False,
        "stage2_confirmed": False,
        "early_bear_repair_confirmed": False,
        "stage3_raw": False,
        "stage3_confirmed": False,
        "deep_bear_raw": False,
        "deep_bear_confirmed": False,
        "deep_bear_exit_confirmed": False,
        "crash_override_raw": False,
        "crash_override_event": False,
        "right_recovery_confirmed": False,
        "new_bull_confirmed": False,
        "failed_new_bull_raw": False,
        "accumulation_failure_raw": False,
        "new_bull_gate_3_sma50_up": True,
        "BTC_weakness_score": 1.0,
        "ETH_weakness_score": 1.0,
        "BNB_weakness_score": 1.0,
    }
    values.update(overrides)
    return pd.Series(values)


def test_crash_override_is_overlay_not_macro_transition(rules: dict) -> None:
    state = V3State(
        qty={"BTC": 4.5, "ETH": 2.7, "BNB": 1.8},
        normal_cash=100.0,
        macro_regime="BULL",
        sell_stage=0,
        active_exposure_target=0.95,
    )
    row = _signal_row(crash_override_raw=True, crash_override_event=True)
    prices = {"BTC": 100.0, "ETH": 100.0, "BNB": 100.0}
    trades: list[dict] = []
    cycles: list[dict] = []
    counters = {
        "crash_override_event_count": 0,
        "tactical_sell_events": 0,
    }
    actions, _ = _process_signal(
        state, row, prices, rules, V3Scenario(name="E20", hard_floor=0.2), trades, cycles, counters
    )
    assert state.macro_regime == "BULL"
    assert state.sell_stage == 0
    assert state.active_cycle_id == 0
    assert cycles == []
    assert state.active_exposure_target == 0.70
    assert any("CRASH_OVERRIDE" in action for action in actions)
    assert trades and all(trade["after_crypto_exposure"] >= 0.2 for trade in trades)


def test_confirmed_cycle_cannot_be_aborted_by_distribution_invalidation(rules: dict) -> None:
    state = V3State(
        macro_regime="DISTRIBUTION",
        sell_stage=1,
        active_cycle_id=7,
        active_exposure_target=0.55,
    )
    cycle = {"cycle_id": 7, "cycle_confirmed": True, "status": "CONFIRMED"}
    row = _signal_row(distribution_invalidation_confirmed=True)
    actions, reason = _process_signal(
        state,
        row,
        {"BTC": 100.0, "ETH": 100.0, "BNB": 100.0},
        rules,
        V3Scenario(name="E20", hard_floor=0.2),
        [],
        [cycle],
        {},
    )
    assert state.macro_regime == "DISTRIBUTION"
    assert state.active_cycle_id == 7
    assert cycle["status"] == "CONFIRMED"
    assert reason == "STATE_PERSISTENCE"
    assert not any("FSM_DISTRIBUTION_TO_BULL" in action for action in actions)


def test_cycle_stage_audit_preserves_first_entry() -> None:
    state = V3State(qty={"BTC": 1.0, "ETH": 1.0, "BNB": 1.0})
    cycle = {"stage_4_date": pd.NaT}
    prices = {"BTC": 100.0, "ETH": 100.0, "BNB": 100.0}
    first = _signal_row(
        signal_date=pd.Timestamp("2022-04-16", tz="UTC"),
        open_time=pd.Timestamp("2022-04-17", tz="UTC"),
        BTC_daily_close=40_000.0,
    )
    later = _signal_row(
        signal_date=pd.Timestamp("2022-11-21", tz="UTC"),
        open_time=pd.Timestamp("2022-11-22", tz="UTC"),
        BTC_daily_close=15_781.29,
    )
    _record_stage(cycle, 4, first, state, prices)
    _record_stage(cycle, 4, later, state, prices)
    assert cycle["stage_4_date"] == first["signal_date"]
    assert cycle["stage_4_execution"] == first["open_time"]
    assert cycle["stage_4_btc_price"] == 40_000.0


def test_v3_features_are_prefix_invariant(rules: dict) -> None:
    path = PROJECT / "data" / "processed" / "btc_primary_daily_signals.csv.gz"
    daily = pd.read_csv(path, compression="gzip")
    for column in ("open_time", "signal_date", "signal_available_at"):
        daily[column] = pd.to_datetime(daily[column], utc=True)
    prefix_n = min(1600, len(daily) - 10)
    full = add_v3_macro_features(daily, rules).iloc[:prefix_n].reset_index(drop=True)
    prefix = add_v3_macro_features(daily.iloc[:prefix_n].copy(), rules).reset_index(drop=True)
    columns = [
        "distribution_confirmed", "stage2_confirmed", "stage3_confirmed", "deep_bear_confirmed",
        "crash_override_event", "right_recovery_confirmed", "new_bull_confirmed",
        "peak_to_close_drawdown_90d",
    ]
    for column in columns:
        if full[column].dtype == bool:
            assert full[column].equals(prefix[column])
        else:
            assert np.allclose(full[column], prefix[column], equal_nan=True)


def test_no_audit_case_dates_in_trading_modules() -> None:
    source = "\n".join(
        (PROJECT / "src" / "crypto_backtest" / filename).read_text(encoding="utf-8")
        for filename in ("v3_engine.py", "v3_indicators.py")
    )
    for forbidden in ("2020-03", "2021-05", "2021-11", "2022-02", "2022-06", "2022-11"):
        assert forbidden not in source
