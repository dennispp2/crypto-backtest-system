from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_backtest.engine import Scenario, run_backtest
from crypto_backtest.v2_analysis import fixed_dca_integrity_audit
from crypto_backtest.v2_engine import HedgeScenario, run_cycle_hedge_backtest


def rules_v1() -> dict:
    return json.loads((ROOT / "config" / "frozen_rules.json").read_text(encoding="utf-8"))


def rules_v2() -> dict:
    return json.loads((ROOT / "config" / "frozen_rules_v2.json").read_text(encoding="utf-8"))


def synthetic_cycle_frame(days: int = 32) -> pd.DataFrame:
    n = days * 6
    timestamps = pd.date_range("2020-01-01", periods=n, freq="4h", tz="UTC")
    execution_day = (timestamps.floor("D") - timestamps[0].floor("D")).days
    signal_date = timestamps.floor("D") - pd.Timedelta(days=1)
    data: dict[str, object] = {"open_time": timestamps}
    for asset, price in (("BTC", 100.0), ("ETH", 10.0), ("BNB", 1.0)):
        # A small common trend avoids exact-zero return corner cases.
        series = price * (1.0 + np.linspace(0.0, 0.03, n))
        data[f"{asset}_open"] = series
        data[f"{asset}_close"] = series * 1.0001
        data[f"{asset}_weakness_score"] = 0
    data.update(
        {
            "signal_date": signal_date,
            "signal_available_at": signal_date + pd.Timedelta(days=1),
            "daily_source": "synthetic",
            "BTC_daily_close": 100.0,
            "sma10": 99.0,
            "sma20": 98.0,
            "sma50": 97.0,
            "sma200": 96.0,
            "bb_upper": 120.0,
            "bb_lower": 80.0,
            "close_sma200_dev": 0.0,
            "ahr999_fixed_arithmetic": np.where((execution_day >= 4) & (execution_day <= 6), 0.29, 1.0),
            "overheat_gate": execution_day == 0,
            "overheat_count": np.where(execution_day == 0, 2, 0),
            "stage1_condition": execution_day == 1,
            "stage2_condition": execution_day == 2,
            "stage3_condition": execution_day == 3,
            "stage4_condition": execution_day == 4,
            "right_confirmation": execution_day >= 5,
            "strong_confirmation": execution_day >= 6,
        }
    )
    return pd.DataFrame(data)


def champion(frame: pd.DataFrame) -> object:
    scenario = Scenario(
        name="A - Fixed DCA Champion",
        capital_test="unit_v2",
        initial_capital=1000.0,
        initial_crypto_fraction=0.7,
        cash_protection=False,
    )
    return run_backtest(frame, rules_v1(), scenario)


def hedge(frame: pd.DataFrame, floor: float = 0.2):
    a = champion(frame)
    scenario = HedgeScenario(
        name=f"E{int(100 * floor)} - test",
        hard_floor=floor,
        initial_capital=1000.0,
        initial_crypto_fraction=0.7,
    )
    local_rules = rules_v2()
    local_rules["initial_capital"] = 1000.0
    local_rules["initial_allocation_usd"] = {"BTC": 350.0, "ETH": 210.0, "BNB": 140.0, "USD": 300.0}
    return a, run_cycle_hedge_backtest(frame, local_rules, scenario, a), local_rules


def test_v2_replays_fixed_dca_exactly() -> None:
    frame = synthetic_cycle_frame()
    a, e, local_rules = hedge(frame)
    a_history = a.history.copy()
    crypto = (
        a_history["portfolio_value"]
        - a_history["normal_cash"]
        - a_history["pending_dca_cash"]
        - a_history["tactical_cash"]
    )
    a_history["btc_value"] = crypto * a_history["BTC_allocation"]
    a_history["eth_value"] = crypto * a_history["ETH_allocation"]
    a_history["bnb_value"] = crypto * a_history["BNB_allocation"]
    a_history["crypto_exposure"] = crypto / a_history["portfolio_value"]
    a_history["intended_dca"] = 2.0 * a_history["elapsed_4h_intervals"]
    audit = fixed_dca_integrity_audit(a_history, a.trades, e)
    assert audit["all_match"].all()
    assert (e.history["theoretical_dca"] == 2.0).all()


def test_v2_sell_never_causes_floor_breach() -> None:
    _, e, _ = hedge(synthetic_cycle_frame(), floor=0.2)
    sells = e.trades[e.trades["action"].str.startswith("TACTICAL_SELL", na=False)]
    assert not sells.empty
    assert (sells["post_trade_crypto_exposure"] >= 0.2 - 1e-10).all()
    assert e.history["tactical_cash"].min() >= -1e-10


def test_v2_buyback_triggers_are_one_shot_per_cycle() -> None:
    _, e, _ = hedge(synthetic_cycle_frame())
    watched = e.trades[e.trades["action"].isin(
        [
            "TACTICAL_BUYBACK_AHR_BELOW_030",
            "TACTICAL_BUYBACK_RIGHT_CONFIRMATION",
        ]
    )]
    events = watched.groupby(["sell_cycle_id", "action"])["timestamp"].nunique()
    assert (events <= 1).all()


def test_v2_new_bull_resets_stage_and_closes_cycle() -> None:
    _, e, _ = hedge(synthetic_cycle_frame())
    assert not e.cycles.empty
    first = e.cycles.iloc[0]
    assert pd.notna(first["NEW_BULL_date"])
    assert first["reset_date"] == first["NEW_BULL_date"]
    assert first["status"] == "CLOSED"
    new_bull_history = e.history[e.history["cycle_regime"].eq("NEW_BULL")]
    assert (new_bull_history["sell_stage"] == 0).all()


def test_v2_signal_executes_no_earlier_than_next_open() -> None:
    _, e, _ = hedge(synthetic_cycle_frame())
    assert (
        pd.to_datetime(e.signals["execution_4h_open"], utc=True)
        >= pd.to_datetime(e.signals["signal_available_at"], utc=True)
    ).all()
    tactical = e.trades[e.trades["action"].str.startswith("TACTICAL", na=False)]
    available = pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    assert (pd.to_datetime(tactical["timestamp"], utc=True) >= available).all()
