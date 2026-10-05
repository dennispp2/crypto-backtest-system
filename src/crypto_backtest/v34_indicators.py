from __future__ import annotations

from typing import Any

import pandas as pd

from .v31_indicators import consecutive_true


def add_v34_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Build V3.4 features from completed daily candles only.

    Every rolling window is backward-looking and includes the current completed
    candle. Stateful facts such as actual L2/L3 executions are deliberately left
    to the engine.
    """
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    close = out["close"].astype(float)

    hysteresis = rules["deep_bear_hysteresis"]
    exit_days = int(hysteresis["exit_to_bear_close_above_sma50_consecutive_days"])
    sma20_lookback = int(hysteresis["exit_to_bear_sma20_slope_lookback_days"])
    out["close_above_sma50_5d"] = consecutive_true(close > out["sma50"], exit_days)
    out["sma20_up_5d"] = out["sma20"] > out["sma20"].shift(sma20_lookback)
    previous_20d_low = close.shift(1).rolling(20, min_periods=20).min()
    out["new_20d_low"] = close.le(previous_20d_low)
    out["no_new_20d_low"] = close.gt(previous_20d_low)
    out["deep_bear_exit_v34_confirmed"] = (
        out["close_above_sma50_5d"] & out["sma20_up_5d"] & out["no_new_20d_low"]
    )

    crash = rules["crash_level_3"]
    peak_7 = close.rolling(7, min_periods=7).max()
    peak_10 = close.rolling(10, min_periods=10).max()
    out["btc_peak_to_close_dd_7d"] = close / peak_7 - 1.0
    out["btc_peak_to_close_dd_10d"] = close / peak_10 - 1.0
    out["crash_level3_price_raw"] = (
        (
            out["btc_peak_to_close_dd_7d"].le(float(crash["drawdown_7_calendar_days"]))
            | out["btc_peak_to_close_dd_10d"].le(float(crash["drawdown_10_calendar_days"]))
        )
        & close.lt(out["sma50"])
        & (close.lt(out["sma200"]) | close.lt(out["bb_lower"]))
    )
    out["close_above_sma50_recovery_5d"] = consecutive_true(
        close > out["sma50"], int(crash["recovery_close_above_sma50_completed_closes"])
    )
    out["crash_recovery_market_raw"] = (
        out["close_above_sma50_recovery_5d"]
        & close.gt(out["sma20"])
        & out["sma10"].gt(out["sma20"])
    )

    req = rules["macro_bull_requalification"]
    above = close.gt(out["sma200"])
    above_count = above.astype(int).rolling(
        int(req["close_above_sma200_window"]),
        min_periods=int(req["close_above_sma200_window"]),
    ).sum()
    out["close_above_sma200_count_30d"] = above_count
    out["sma200_up_30d"] = out["sma200"].gt(
        out["sma200"].shift(int(req["sma200_slope_lookback_days"]))
    )
    out["sma200_not_down_1d"] = out["sma200"].ge(out["sma200"].shift(1))
    out["sma50_up_10d"] = out["sma50"].gt(
        out["sma50"].shift(int(req["sma50_slope_lookback_days"]))
    )
    high_120 = close.rolling(
        int(req["near_high_window_days"]), min_periods=int(req["near_high_window_days"])
    ).max()
    out["btc_high_120d"] = high_120
    out["near_120d_high"] = close.ge(float(req["near_high_fraction"]) * high_120)
    out["macro_bull_requalification_market_candidate"] = (
        above_count.ge(int(req["close_above_sma200_min_count"]))
        & out["sma200_up_30d"]
        & out["sma50"].gt(out["sma200"])
        & out["sma50_up_10d"]
        & close.gt(out["sma50"])
        & out["near_120d_high"]
    )
    out["macro_bull_candidate_confirmation_market"] = (
        close.gt(out["sma200"])
        & out["sma50"].gt(out["sma200"])
        & out["sma200_not_down_1d"]
    )
    out["macro_bull_new_bull_confirmation_market"] = (
        close.gt(out["sma200"])
        & out["sma50"].gt(out["sma200"])
        & out["sma50_up_10d"]
        & out["sma200_up_30d"]
        & out["no_new_20d_low"]
    )
    return out


__all__ = ["add_v34_features"]
