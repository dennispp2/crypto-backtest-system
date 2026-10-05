from __future__ import annotations

from typing import Any

import pandas as pd

from .v31_indicators import consecutive_true


def add_v33_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Add only the completed-daily features explicitly authorized for V3.3 hysteresis."""
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    close = out["close"].astype(float)
    hysteresis = rules["deep_bear_hysteresis"]
    lookback = int(hysteresis["exit_to_bear_sma20_slope_lookback_days"])
    required = int(hysteresis["exit_to_bear_close_above_sma50_consecutive_days"])
    out["close_above_sma50_5d"] = consecutive_true(close > out["sma50"], required)
    out["sma20_up_5d"] = out["sma20"] > out["sma20"].shift(lookback)
    previous_20d_low = close.shift(1).rolling(20, min_periods=20).min()
    out["new_20d_low"] = close.le(previous_20d_low)
    out["no_new_20d_low"] = close.gt(previous_20d_low)
    out["deep_bear_exit_v33_confirmed"] = (
        out["close_above_sma50_5d"]
        & out["sma20_up_5d"]
        & out["no_new_20d_low"]
    )
    return out


__all__ = ["add_v33_features"]
