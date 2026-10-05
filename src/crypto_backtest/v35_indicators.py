from __future__ import annotations

from typing import Any

import pandas as pd

from .v31_indicators import consecutive_true
from .v34_indicators import add_v34_features


def add_v35_features(daily: pd.DataFrame, v34_rules: dict[str, Any], rules: dict[str, Any]) -> pd.DataFrame:
    """Add Patch-D features using completed daily candles and backward windows only."""
    out = add_v34_features(daily, v34_rules)
    patch = rules["accumulation_anti_whipsaw"]
    close = out["close"].astype(float)
    new_low = out["new_20d_low"].fillna(False).astype(bool)
    out["no_new_20d_low_5d"] = new_low.astype(int).rolling(5, min_periods=5).sum().eq(0)
    out["no_new_20d_low_10d"] = new_low.astype(int).rolling(10, min_periods=10).sum().eq(0)
    out["patch_d_close_above_sma20_3d"] = consecutive_true(
        close.gt(out["sma20"]), int(patch["right_50_close_above_sma20_completed_closes"])
    )
    out["patch_d_right_50_confirmed"] = (
        out["patch_d_close_above_sma20_3d"]
        & out["sma10"].gt(out["sma20"])
        & out["sma20"].gt(out["sma20"].shift(int(patch["right_50_sma20_slope_lookback_days"])))
        & out["no_new_20d_low_5d"]
    )
    out["patch_d_close_above_sma50_5d"] = consecutive_true(
        close.gt(out["sma50"]), int(patch["right_60_close_above_sma50_completed_closes"])
    )
    out["patch_d_right_60_confirmed"] = (
        out["patch_d_close_above_sma50_5d"]
        & out["sma20"].gt(out["sma20"].shift(5))
        & out["sma10"].gt(out["sma20"])
        & out["no_new_20d_low_10d"]
    )
    out["patch_d_hard_failure_raw"] = (
        new_low
        & close.lt(out["sma50"])
        & out["sma20"].lt(out["sma20"].shift(int(patch["hard_failure_sma20_slope_lookback_days"])))
    )
    out["patch_d_hard_failure_confirmed"] = consecutive_true(
        out["patch_d_hard_failure_raw"], int(patch["hard_failure_confirmation_completed_closes"])
    )
    return out


__all__ = ["add_v35_features"]
