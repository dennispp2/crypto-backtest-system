from __future__ import annotations

from typing import Any

import pandas as pd


def add_v36_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Add point-in-time fields used only by the V3.6 buy-frequency guard."""
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    close_column = "close" if "close" in out.columns else "BTC_daily_close"
    close = out[close_column].astype(float)
    lookback = int(rules["anti_whipsaw"]["new_closing_low_lookback_completed_daily_closes"])
    recent = int(rules["anti_whipsaw"]["no_new_low_recent_completed_closes"])
    prior_floor = close.shift(1).rolling(lookback, min_periods=lookback).min()
    out["new_20d_closing_low"] = (close <= prior_floor).fillna(False)
    out["no_new_20d_closing_low_recent3"] = (
        out["new_20d_closing_low"].astype(int).rolling(recent, min_periods=recent).sum().eq(0)
    ).fillna(False)
    return out


__all__ = ["add_v36_features"]
