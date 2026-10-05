from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .indicators import build_primary_daily


def consecutive_true(values: pd.Series, days: int) -> pd.Series:
    numeric = values.fillna(False).astype(int)
    return numeric.rolling(days, min_periods=days).sum().eq(days)


def add_v31_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Create only backward-looking FSM/AI features plus an explicitly future label."""
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    macro = rules["macro"]
    crash = rules["crash_brake"]
    buyback = rules["buyback"]
    new_bull = rules["new_bull"]
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)

    out["sma10_slope_down"] = out["sma10"] < out["sma10"].shift(int(macro["sma10_slope_days"]))
    out["sma10_slope_up"] = out["sma10"] > out["sma10"].shift(int(macro["sma10_slope_days"]))
    out["sma20_slope_down"] = out["sma20"] < out["sma20"].shift(int(macro["sma20_slope_days"]))
    out["sma20_slope_up"] = out["sma20"] > out["sma20"].shift(int(macro["sma20_slope_days"]))
    out["sma50_slope_up"] = out["sma50"] > out["sma50"].shift(int(macro["sma50_slope_days"]))
    out["sma50_slope_down"] = out["sma50"] < out["sma50"].shift(int(macro["sma50_slope_days"]))
    out["sma200_slope_up"] = out["sma200"] > out["sma200"].shift(int(macro["sma200_slope_days"]))
    out["sma200_non_rising"] = out["sma200"] <= out["sma200"].shift(int(macro["sma200_slope_days"]))

    for days in (7, 10, 30, 90):
        out[f"peak_to_close_drawdown_{days}d"] = close / close.rolling(days, min_periods=days).max() - 1.0
    out["cycle_peak_90d"] = close.rolling(int(macro["cycle_peak_lookback_days"]), min_periods=int(macro["cycle_peak_lookback_days"])).max()
    out["return_3d"] = close.pct_change(3)

    structure_days = int(macro["market_structure_window_days"])
    range_high = high.rolling(structure_days, min_periods=structure_days).max()
    range_low = low.rolling(structure_days, min_periods=structure_days).min()
    out["lower_high_lower_low"] = (
        (range_high < range_high.shift(structure_days))
        & (range_low < range_low.shift(structure_days))
    )
    major_days = int(macro["previous_major_low_lookback_days"])
    out["previous_major_low"] = low.shift(1).rolling(major_days, min_periods=major_days).min()
    out["previous_major_low_broken"] = close < out["previous_major_low"]

    trend_flags = pd.DataFrame(
        {
            "sma200_up": out["sma200_slope_up"],
            "sma50_above_sma200": out["sma50"] > out["sma200"],
            "sma50_up": out["sma50_slope_up"],
            "sma20_above_sma50": out["sma20"] > out["sma50"],
        }
    )
    out["bull_trend_score"] = trend_flags.sum(axis=1)
    out["bull_condition"] = (
        (close > out["sma200"])
        & (out["bull_trend_score"] >= int(macro["bull_min_trend_conditions"]))
    )
    out["bull_5_confirmed"] = consecutive_true(
        out["bull_condition"], int(rules["temporary_hedge"]["bull_confirmation_days"])
    )

    out["bb_mid_lost_failed_reclaim"] = (
        (close < out["bb_mid"])
        & ((high >= out["bb_mid"]) | (close.shift(1) < out["bb_mid"].shift(1)))
    )
    distribution_extra = (
        (close < out["sma50"])
        | (out["peak_to_close_drawdown_10d"] <= float(macro["drawdown_10d_distribution"]))
        | out["bb_mid_lost_failed_reclaim"]
    )
    out["distribution_raw"] = (close < out["sma20"]) & out["sma10_slope_down"] & distribution_extra
    out["distribution_confirmed"] = consecutive_true(
        out["distribution_raw"], int(macro["distribution_confirmation_days"])
    )
    out["distribution_abort_raw"] = (
        (close > out["sma20"])
        & (close > out["sma50"])
        & out["sma10_slope_up"]
        & (close > out["sma200"])
    )
    out["distribution_abort_confirmed"] = consecutive_true(
        out["distribution_abort_raw"], int(macro["distribution_abort_confirmation_days"])
    )

    out["failed_reclaim_sma20"] = (close < out["sma20"]) & (close.shift(1) < out["sma20"].shift(1))
    out["early_bear_raw"] = (close < out["sma50"]) & out["sma20_slope_down"] & out["failed_reclaim_sma20"]
    out["early_bear_confirmed"] = consecutive_true(
        out["early_bear_raw"], int(macro["early_bear_confirmation_days"])
    )
    out["early_bear_repair_raw"] = (close > out["sma20"]) & out["sma10_slope_up"]
    out["early_bear_repair_confirmed"] = consecutive_true(
        out["early_bear_repair_raw"], int(macro["early_bear_repair_confirmation_days"])
    )

    stage3_flags = pd.DataFrame(
        {
            "below_sma200": close < out["sma200"],
            "sma50_down": out["sma50_slope_down"],
            "sma20_below_sma50": out["sma20"] < out["sma50"],
            "drawdown30": out["peak_to_close_drawdown_30d"] <= float(macro["drawdown_30d_stage3"]),
            "lower_structure": out["lower_high_lower_low"],
        }
    )
    out["stage3_condition_count"] = stage3_flags.sum(axis=1)
    out["stage3_long_cycle_condition"] = (close < out["sma200"]) | out["sma200_non_rising"]
    out["stage3_raw"] = (
        (out["stage3_condition_count"] >= int(macro["stage3_min_conditions"]))
        & out["stage3_long_cycle_condition"]
    )
    out["stage3_confirmed"] = consecutive_true(out["stage3_raw"], int(macro["stage3_confirmation_days"]))

    out["below_sma200_count_7"] = (close < out["sma200"]).astype(int).rolling(
        int(macro["below_sma200_window_days"]),
        min_periods=int(macro["below_sma200_window_days"]),
    ).sum()
    out["bear_acceleration_market_raw"] = (
        (close < out["sma200"])
        & (out["below_sma200_count_7"] >= int(macro["below_sma200_days_required"]))
    )
    deep_core = (
        (close < out["sma200"])
        & (out["sma50"] < out["sma200"])
        & (out["sma200"] < out["sma200"].shift(int(macro["sma200_slope_days"])))
    )
    deep_extra = (
        (close <= float(macro["price_to_sma200_deep_bear"]) * out["sma200"])
        | (out["peak_to_close_drawdown_90d"] <= float(macro["drawdown_90d_deep_bear"]))
        | out["previous_major_low_broken"]
    )
    out["deep_bear_structural_raw"] = deep_core & deep_extra
    out["deep_bear_structural_confirmed"] = consecutive_true(
        out["deep_bear_structural_raw"], int(macro["stage4_structural_confirmation_days"])
    )
    out["deep_bear_exit_confirmed"] = consecutive_true(
        ~out["deep_bear_structural_raw"].fillna(False), int(macro["stage4_exit_confirmation_days"])
    )

    out["crash_level1_raw"] = (
        (out["peak_to_close_drawdown_7d"] <= float(crash["level1_drawdown_7d"]))
        | ((out["return_3d"] <= float(crash["level1_return_3d"])) & (close < out["sma50"]))
    )
    out["crash_level2_market_raw"] = (
        (out["peak_to_close_drawdown_10d"] <= float(crash["level2_drawdown_10d"]))
        & (close < out["sma50"])
    )
    crash_any = out["crash_level1_raw"] | out["crash_level2_market_raw"]
    crash_recent = crash_any.fillna(False).astype(int).rolling(
        int(new_bull["crash_free_days"]), min_periods=int(new_bull["crash_free_days"])
    ).sum()
    out["crash_free_20d"] = crash_recent.eq(0)

    out["right_50_confirmed"] = (
        consecutive_true(close > out["sma20"], int(buyback["right_50_closes_above_sma20"]))
        & (out["sma10"] > out["sma20"])
        & (out["sma20"] > out["sma20"].shift(5))
    )
    out["right_60_confirmed"] = (
        consecutive_true(close > out["sma50"], int(buyback["right_60_closes_above_sma50"]))
        & out["sma20_slope_up"]
    )
    lower_low_raw = (
        (close < low.shift(1).rolling(structure_days, min_periods=structure_days).min())
        & (close < out["sma50"])
        & out["sma20_slope_down"]
    )
    out["confirmed_lower_low"] = consecutive_true(lower_low_raw, int(buyback["lower_low_confirmation_days"]))

    above_sma200 = close > out["sma200"]
    out["above_sma200_count_12"] = above_sma200.astype(int).rolling(
        int(new_bull["closes_above_sma200_window"]),
        min_periods=int(new_bull["closes_above_sma200_window"]),
    ).sum()
    out["sma20_above_sma50_5d"] = consecutive_true(
        out["sma20"] > out["sma50"], int(new_bull["sma20_above_sma50_days"])
    )
    out["new_bull_gate_1"] = out["above_sma200_count_12"] >= int(new_bull["closes_above_sma200_required"])
    out["new_bull_gate_2"] = out["sma200"] >= out["sma200"].shift(int(macro["sma200_slope_days"]))
    out["new_bull_gate_3"] = out["sma50_slope_up"]
    out["new_bull_gate_4"] = (out["sma50"] > out["sma200"]) | out["sma20_above_sma50_5d"]
    out["new_bull_gate_5"] = close > out["sma50"]
    out["new_bull_gate_6"] = out["crash_free_20d"]
    out["new_bull_first_six"] = out[[f"new_bull_gate_{i}" for i in range(1, 7)]].all(axis=1)

    bb_range = (out["bb_upper"] - out["bb_lower"]).replace(0.0, np.nan)
    out["feature_price_sma50"] = close / out["sma50"] - 1.0
    out["feature_price_sma200"] = close / out["sma200"] - 1.0
    out["feature_sma50_slope"] = out["sma50"] / out["sma50"].shift(10) - 1.0
    out["feature_sma200_slope"] = out["sma200"] / out["sma200"].shift(20) - 1.0
    out["feature_drawdown30"] = out["peak_to_close_drawdown_30d"]
    out["feature_bb_position"] = (close - out["bb_mid"]) / bb_range
    out["feature_bb_width"] = bb_range / out["bb_mid"].replace(0.0, np.nan)

    horizon = int(rules["ai"]["label_horizon_completed_daily_closes"])
    future_closes = pd.concat([close.shift(-offset) for offset in range(1, horizon + 1)], axis=1)
    future_min = future_closes.min(axis=1, skipna=False)
    out["future_min_return_60d"] = future_min / close - 1.0
    out["bear_label"] = np.where(
        out["future_min_return_60d"].notna(),
        (out["future_min_return_60d"] <= float(rules["ai"]["label_drawdown_threshold"])).astype(float),
        np.nan,
    )
    out["label_end_date"] = out["signal_date"].shift(-horizon)
    return out


def build_v31_daily(
    bitstamp_daily: pd.DataFrame,
    binance_btc_daily: pd.DataFrame,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, str]:
    primary, switch = build_primary_daily(bitstamp_daily, binance_btc_daily, base_rules)
    return add_v31_features(primary, rules), switch


def merge_v31_features_to_bars(frame: pd.DataFrame, daily: pd.DataFrame) -> pd.DataFrame:
    excluded = {
        "open_time", "close_time", "open", "high", "low", "close", "volume",
        "future_min_return_60d", "bear_label", "label_end_date",
    }
    features = daily[[column for column in daily.columns if column not in excluded]].copy()
    rename = {
        "signal_date": "signal_date",
    }
    features = features.rename(columns=rename)
    for source, target in {
        "daily_source": "daily_source",
    }.items():
        if source not in features:
            features[target] = ""
    daily_prices = daily[["signal_available_at", "open", "high", "low", "close"]].rename(
        columns={
            "open": "BTC_daily_open",
            "high": "BTC_daily_high",
            "low": "BTC_daily_low",
            "close": "BTC_daily_close",
        }
    )
    features = features.merge(daily_prices, on="signal_available_at", how="left", validate="one_to_one")
    return pd.merge_asof(
        frame.sort_values("open_time"),
        features.sort_values("signal_available_at"),
        left_on="open_time",
        right_on="signal_available_at",
        direction="backward",
        allow_exact_matches=True,
    ).sort_values("open_time").reset_index(drop=True)
