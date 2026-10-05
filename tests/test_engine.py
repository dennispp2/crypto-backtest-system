from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_backtest.engine import Scenario, run_backtest


def rules() -> dict:
    return json.loads((ROOT / "config" / "frozen_rules.json").read_text(encoding="utf-8"))


def synthetic_frame(n: int = 120) -> pd.DataFrame:
    ts = pd.date_range("2020-01-02", periods=n, freq="4h", tz="UTC")
    data: dict[str, object] = {"open_time": ts}
    for asset, price in [("BTC", 100.0), ("ETH", 10.0), ("BNB", 1.0)]:
        data[f"{asset}_open"] = price * (1.0 + np.linspace(0, 0.05, n))
        data[f"{asset}_close"] = price * (1.0 + np.linspace(0.0001, 0.0501, n))
        data[f"{asset}_weakness_score"] = 0
    signal_date = ts.floor("D") - pd.Timedelta(days=1)
    data.update(
        {
            "signal_date": signal_date,
            "signal_available_at": signal_date + pd.Timedelta(days=1),
            "daily_source": "synthetic",
            "BTC_daily_close": 100.0,
            "bb_lower": 80.0,
            "close_sma200_dev": 0.0,
            "ahr999_fixed_arithmetic": 1.0,
            "overheat_gate": False,
            "overheat_count": 0,
            "stage1_condition": False,
            "stage2_condition": False,
            "stage3_condition": False,
            "stage4_condition": False,
            "right_confirmation": False,
            "strong_confirmation": False,
        }
    )
    return pd.DataFrame(data)


def scenario(initial_crypto_fraction: float = 0.0) -> Scenario:
    return Scenario(
        name="Benchmark A - Fixed DCA",
        capital_test="unit",
        initial_capital=100.0,
        initial_crypto_fraction=initial_crypto_fraction,
    )


def test_minimum_order_accumulates_pending_cash() -> None:
    result = run_backtest(synthetic_frame(6), rules(), scenario())
    dca = result.trades[result.trades["action"] == "NORMAL_DCA"]
    assert not dca.empty
    assert dca.iloc[0]["cash_change_usd"] <= -5.0
    assert (dca["ledger"] == "pending").all()


def test_signal_time_is_not_after_execution() -> None:
    result = run_backtest(synthetic_frame(), rules(), scenario(0.7))
    assert (
        pd.to_datetime(result.signals["signal_available_at"], utc=True)
        <= pd.to_datetime(result.signals["execution_4h_open"], utc=True)
    ).all()


def test_prefix_invariance() -> None:
    frame = synthetic_frame(120)
    full = run_backtest(frame, rules(), scenario(0.7))
    prefix = run_backtest(frame.iloc[:60], rules(), scenario(0.7))
    cutoff = frame.iloc[59]["open_time"]
    full_prefix = full.trades[full.trades["timestamp"] <= cutoff].reset_index(drop=True)
    cols = ["timestamp", "action", "side", "asset", "quantity", "ledger"]
    pd.testing.assert_frame_equal(prefix.trades[cols].reset_index(drop=True), full_prefix[cols], check_exact=False, rtol=1e-12)


def test_dca_never_uses_tactical_ledger() -> None:
    result = run_backtest(synthetic_frame(), rules(), scenario(0.7))
    dca = result.trades[result.trades["action"] == "NORMAL_DCA"]
    assert (dca["ledger"] == "pending").all()
    assert result.history["normal_cash"].min() >= -1e-9
    assert result.history["tactical_cash"].min() >= -1e-9


def test_external_contributions_are_deterministic() -> None:
    frame = synthetic_frame(24)
    a = run_backtest(frame, rules(), scenario(0.0))
    b = run_backtest(frame, rules(), scenario(0.7))
    assert a.summary["periodic_external_contributions"] == b.summary["periodic_external_contributions"] == 48.0


def test_missing_market_bar_does_not_skip_four_hour_contribution() -> None:
    frame = synthetic_frame(6).drop(index=2).reset_index(drop=True)
    result = run_backtest(frame, rules(), scenario(0.0))
    assert result.summary["periodic_external_contributions"] == 12.0
    assert int(result.history["elapsed_4h_intervals"].sum()) == 6


def test_right_confirmation_cannot_precede_undervaluation_buyback() -> None:
    frame = synthetic_frame(72)
    # Day 1 records overheat; day 2 enters Stage 1; day 3 has a bullish
    # confirmation but AHR999 is still high.  No right-side buy is eligible.
    day = frame["open_time"].dt.floor("D")
    unique = list(day.drop_duplicates())
    frame.loc[day == unique[0], "overheat_gate"] = True
    frame.loc[day == unique[1], "stage1_condition"] = True
    frame.loc[day == unique[2], "right_confirmation"] = True
    full = Scenario(
        name="Strategy D - Full",
        capital_test="unit",
        initial_capital=1000.0,
        initial_crypto_fraction=0.7,
        dynamic_dca=True,
        tactical=True,
    )
    result = run_backtest(frame, rules(), full)
    assert not result.trades["action"].eq("TACTICAL_BUYBACK_RIGHT_CONFIRMATION").any()
