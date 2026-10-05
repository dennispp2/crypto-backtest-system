from __future__ import annotations

from typing import Any

import pandas as pd

from .v31_indicators import consecutive_true


def add_v32_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Add V3.2-only features using completed daily rows at t or earlier."""
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    close = out["close"].astype(float)
    buyback = rules["buyback"]
    recovery = rules["bull_recovery"]
    hysteresis = rules["deep_bear_hysteresis"]

    new_low_10 = close.le(
        close.shift(1).rolling(
            int(buyback["right_60_no_new_low_lookback_days"]),
            min_periods=int(buyback["right_60_no_new_low_lookback_days"]),
        ).min()
    )
    out["no_new_10d_low_event_in_last_10d"] = new_low_10.fillna(True).astype(int).rolling(
        int(buyback["right_60_no_new_low_lookback_days"]),
        min_periods=int(buyback["right_60_no_new_low_lookback_days"]),
    ).sum().eq(0)
    out["right_60_v32_confirmed"] = (
        consecutive_true(
            close > out["sma50"],
            int(buyback["right_60_close_above_sma50_consecutive_days"]),
        )
        & out["sma20_slope_up"]
        & out["no_new_10d_low_event_in_last_10d"]
    )

    low_window = int(hysteresis["exit_to_bear_sma20_slope_lookback_days"])
    out["sma20_up_5d"] = out["sma20"] > out["sma20"].shift(low_window)
    out["close_above_sma50_5d"] = consecutive_true(
        close > out["sma50"],
        int(hysteresis["exit_to_bear_close_above_sma50_consecutive_days"]),
    )
    out["new_20d_low"] = close.le(close.shift(1).rolling(20, min_periods=20).min())
    out["no_new_20d_low"] = ~out["new_20d_low"].fillna(True)
    out["deep_bear_exit_v32_confirmed"] = (
        out["close_above_sma50_5d"]
        & out["sma20_up_5d"]
        & out["no_new_20d_low"]
    )

    above_200 = close > out["sma200"]
    above_count = above_200.astype(int).rolling(
        int(recovery["close_above_sma200_window_completed_days"]),
        min_periods=int(recovery["close_above_sma200_window_completed_days"]),
    ).sum()
    sma20_above_50 = consecutive_true(
        out["sma20"] > out["sma50"],
        int(recovery["sma20_above_sma50_consecutive_days"]),
    )
    sma50_up = out["sma50"] > out["sma50"].shift(
        int(recovery["sma50_slope_lookback_days"])
    )
    out["bull_recovery_gate"] = (
        above_count.ge(int(recovery["close_above_sma200_required"]))
        & sma50_up
        & sma20_above_50
        & (close > out["sma50"])
        & out["crash_free_20d"]
    )
    out["recovery_new_bull_daily_condition"] = (
        above_200 & sma50_up & (out["sma20"] > out["sma50"]) & out["no_new_20d_low"]
    )
    return out

