from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _consecutive_true(values: pd.Series, days: int) -> pd.Series:
    numeric = values.fillna(False).astype(int)
    return numeric.rolling(days, min_periods=days).sum().eq(days)


def _rearmed_events(raw: pd.Series, clear_days: int) -> pd.Series:
    events: list[bool] = []
    armed = True
    clear_count = clear_days
    for value in raw.fillna(False).astype(bool):
        if value and armed:
            events.append(True)
            armed = False
            clear_count = 0
        else:
            events.append(False)
            if value:
                clear_count = 0
            else:
                clear_count += 1
                if clear_count >= clear_days:
                    armed = True
    return pd.Series(events, index=raw.index, dtype=bool)


def add_v3_macro_features(daily: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    """Build strictly backward-looking V3 features on completed BTC daily candles."""
    out = daily.copy().sort_values("signal_date").reset_index(drop=True)
    macro = rules["macro"]
    close = out["close"].astype(float)
    high = out["high"].astype(float)
    low = out["low"].astype(float)

    for days in (3, 10, 20):
        out[f"sma10_change_{days}d"] = out["sma10"] / out["sma10"].shift(days) - 1.0
        out[f"sma20_change_{days}d"] = out["sma20"] / out["sma20"].shift(days) - 1.0
        out[f"sma50_change_{days}d"] = out["sma50"] / out["sma50"].shift(days) - 1.0
        out[f"sma200_change_{days}d"] = out["sma200"] / out["sma200"].shift(days) - 1.0

    for days in (7, 10, 30, 60, 90):
        out[f"peak_to_close_drawdown_{days}d"] = close / close.rolling(days, min_periods=days).max() - 1.0
        out[f"return_{days}d"] = close.pct_change(days)
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
            "sma200_up_20d": out["sma200"] > out["sma200"].shift(int(macro["sma200_slope_days"])),
            "sma50_above_sma200": out["sma50"] > out["sma200"],
            "sma50_up_10d": out["sma50"] > out["sma50"].shift(int(macro["sma50_slope_days"])),
            "sma20_above_sma50": out["sma20"] > out["sma50"],
        }
    )
    out["bull_trend_score"] = trend_flags.sum(axis=1)
    out["bull_condition"] = (
        (close > out["sma200"])
        & (out["bull_trend_score"] >= int(macro["bull_min_trend_conditions"]))
    )

    late_raw = out["overheat_gate"].fillna(False).astype(bool)
    late_window = int(macro["late_bull_window_days"])
    late_required = int(macro["late_bull_confirm_days_in_window"])
    out["late_bull_condition"] = (
        late_raw.astype(int).rolling(late_window, min_periods=late_window).sum() >= late_required
    ) & out["bull_condition"]

    sma10_down = out["sma10"] < out["sma10"].shift(int(macro["sma10_slope_days"]))
    sma20_down = out["sma20"] < out["sma20"].shift(int(macro["sma20_slope_days"]))
    out["bb_mid_lost_failed_reclaim"] = (
        (close < out["bb_mid"])
        & (
            (high >= out["bb_mid"])
            | (close.shift(1) < out["bb_mid"].shift(1))
        )
    )
    distribution_extra = (
        (close < out["sma50"])
        | (out["peak_to_close_drawdown_10d"] <= float(macro["drawdown_10d"]))
        | out["bb_mid_lost_failed_reclaim"]
    )
    out["distribution_raw"] = (close < out["sma20"]) & sma10_down & distribution_extra
    out["distribution_confirmed"] = _consecutive_true(
        out["distribution_raw"], int(macro["distribution_confirmation_days"])
    )
    out["distribution_invalidation_raw"] = (
        (close > out["sma20"])
        & (close > out["sma50"])
        & (out["sma10"] > out["sma10"].shift(int(macro["sma10_slope_days"])))
        & (close > out["sma200"])
    )
    out["distribution_invalidation_confirmed"] = _consecutive_true(
        out["distribution_invalidation_raw"], int(macro["distribution_invalidation_days"])
    )

    out["failed_reclaim_sma20"] = (close < out["sma20"]) & (
        close.shift(1) < out["sma20"].shift(1)
    )
    out["stage2_raw"] = (close < out["sma50"]) & sma20_down & out["failed_reclaim_sma20"]
    out["stage2_confirmed"] = _consecutive_true(
        out["stage2_raw"], int(macro["stage2_confirmation_days"])
    )
    out["early_bear_repair_raw"] = (
        (close > out["sma20"])
        & (out["sma10"] > out["sma10"].shift(int(macro["sma10_slope_days"])))
    )
    out["early_bear_repair_confirmed"] = _consecutive_true(
        out["early_bear_repair_raw"], int(macro["early_bear_repair_days"])
    )

    stage3_flags = pd.DataFrame(
        {
            "below_sma200": close < out["sma200"],
            "sma50_down": out["sma50"] < out["sma50"].shift(int(macro["sma50_slope_days"])),
            "sma20_below_sma50": out["sma20"] < out["sma50"],
            "drawdown_30d": out["peak_to_close_drawdown_30d"] <= float(macro["drawdown_30d"]),
            "lower_high_lower_low": out["lower_high_lower_low"],
        }
    )
    out["stage3_condition_count"] = stage3_flags.sum(axis=1)
    out["stage3_raw"] = out["stage3_condition_count"] >= int(macro["stage3_min_conditions"])
    out["stage3_confirmed"] = _consecutive_true(
        out["stage3_raw"], int(macro["stage3_confirmation_days"])
    )

    deep_core = (
        (close < out["sma200"])
        & (out["sma50"] < out["sma200"])
        & (out["sma200"] < out["sma200"].shift(int(macro["sma200_slope_days"])))
    )
    deep_extra = (
        (close <= float(macro["price_to_sma200_deep_bear"]) * out["sma200"])
        | (out["peak_to_close_drawdown_90d"] <= float(macro["drawdown_90d"]))
        | out["previous_major_low_broken"]
    )
    out["deep_bear_raw"] = deep_core & deep_extra
    out["deep_bear_confirmed"] = _consecutive_true(
        out["deep_bear_raw"], int(macro["deep_bear_confirmation_days"])
    )
    out["deep_bear_exit_confirmed"] = _consecutive_true(
        ~out["deep_bear_raw"].fillna(False), int(macro["deep_bear_exit_confirmation_days"])
    )

    out["crash_rule_a"] = out["peak_to_close_drawdown_7d"] <= float(macro["drawdown_7d"])
    out["crash_rule_b"] = (out["return_3d"] <= float(macro["return_3d"])) & (close < out["sma50"])
    out["crash_rule_c"] = (
        (close < out["bb_lower"])
        & (close <= float(macro["price_to_sma20_crash"]) * out["sma20"])
        & (close < out["sma50"])
    )
    out["crash_override_raw"] = out[["crash_rule_a", "crash_rule_b", "crash_rule_c"]].any(axis=1)
    out["crash_override_event"] = _rearmed_events(
        out["crash_override_raw"], int(macro["crash_rearm_clear_days"])
    )

    buyback = rules["buyback"]
    right = buyback["right_recovery"]
    above_sma20 = close > out["sma20"]
    above_confirm = _consecutive_true(above_sma20, int(right["closes_above_sma20"]))
    local_low = low.rolling(
        int(right["local_low_lookback_days"]),
        min_periods=int(right["local_low_lookback_days"]),
    ).min()
    out["rebound_from_30d_low"] = close / local_low - 1.0
    out["right_recovery_confirmed"] = (
        above_confirm
        & (out["sma10"] > out["sma20"])
        & (out["sma20"] > out["sma20"].shift(int(right["sma20_slope_days"])))
        & (out["rebound_from_30d_low"] >= float(right["minimum_rebound_from_local_low"]))
    )

    new_bull = rules["new_bull"]
    above_sma200 = close > out["sma200"]
    out["above_sma200_count_12"] = above_sma200.astype(int).rolling(
        int(new_bull["closes_above_sma200_window"]),
        min_periods=int(new_bull["closes_above_sma200_window"]),
    ).sum()
    out["sma20_above_sma50_5d"] = _consecutive_true(
        out["sma20"] > out["sma50"], int(new_bull["sma20_above_sma50_days"])
    )
    crash_recent = out["crash_override_raw"].fillna(False).astype(int).rolling(
        int(new_bull["crash_free_days"]),
        min_periods=int(new_bull["crash_free_days"]),
    ).sum()
    out["crash_free_20d"] = crash_recent.eq(0)
    out["new_bull_gate_1_above_sma200"] = (
        out["above_sma200_count_12"] >= int(new_bull["closes_above_sma200_required"])
    )
    out["new_bull_gate_2_sma200_flat"] = (
        out["sma200"] / out["sma200"].shift(int(macro["sma200_slope_days"])) - 1.0
        >= float(new_bull["sma200_near_flat_20d_return"])
    )
    out["new_bull_gate_3_sma50_up"] = (
        out["sma50"] > out["sma50"].shift(int(new_bull["sma50_slope_days"]))
    )
    out["new_bull_gate_4_alignment"] = (out["sma50"] > out["sma200"]) | out["sma20_above_sma50_5d"]
    out["new_bull_gate_5_close_above_sma50"] = close > out["sma50"]
    out["new_bull_gate_6_crash_free"] = out["crash_free_20d"]
    new_bull_gates = [f"new_bull_gate_{i}_{name}" for i, name in [
        (1, "above_sma200"),
        (2, "sma200_flat"),
        (3, "sma50_up"),
        (4, "alignment"),
        (5, "close_above_sma50"),
        (6, "crash_free"),
    ]]
    out["new_bull_confirmed"] = out[new_bull_gates].all(axis=1)

    out["failed_new_bull_raw"] = (
        (close < out["sma50"])
        & sma20_down
        & (
            (close < out["sma200"])
            | (out["peak_to_close_drawdown_10d"] <= float(macro["failed_new_bull_drawdown_10d"]))
            | out["crash_override_event"]
        )
    )

    out["accumulation_failure_raw"] = (
        (close < low.shift(1).rolling(structure_days, min_periods=structure_days).min())
        & (close < out["sma50"])
        & sma20_down
    )

    clear_days = int(macro["bearish_rebreak_clear_days"])
    prior_stage3 = out["stage3_confirmed"].shift(1).fillna(False).astype(int).rolling(
        clear_days, min_periods=clear_days
    ).sum()
    prior_deep = out["deep_bear_confirmed"].shift(1).fillna(False).astype(int).rolling(
        clear_days, min_periods=clear_days
    ).sum()
    out["stage3_rebreak_event"] = out["stage3_confirmed"] & prior_stage3.eq(0)
    out["deep_bear_rebreak_event"] = out["deep_bear_confirmed"] & prior_deep.eq(0)
    return out


def merge_v3_features(frame: pd.DataFrame, daily_features: pd.DataFrame) -> pd.DataFrame:
    feature_columns = [
        "signal_date",
        "bull_trend_score",
        "bull_condition",
        "late_bull_condition",
        "distribution_raw",
        "distribution_confirmed",
        "distribution_invalidation_raw",
        "distribution_invalidation_confirmed",
        "stage2_raw",
        "stage2_confirmed",
        "early_bear_repair_raw",
        "early_bear_repair_confirmed",
        "stage3_condition_count",
        "stage3_raw",
        "stage3_confirmed",
        "deep_bear_raw",
        "deep_bear_confirmed",
        "deep_bear_exit_confirmed",
        "crash_rule_a",
        "crash_rule_b",
        "crash_rule_c",
        "crash_override_raw",
        "crash_override_event",
        "right_recovery_confirmed",
        "rebound_from_30d_low",
        "new_bull_gate_1_above_sma200",
        "new_bull_gate_2_sma200_flat",
        "new_bull_gate_3_sma50_up",
        "new_bull_gate_4_alignment",
        "new_bull_gate_5_close_above_sma50",
        "new_bull_gate_6_crash_free",
        "new_bull_confirmed",
        "failed_new_bull_raw",
        "accumulation_failure_raw",
        "stage3_rebreak_event",
        "deep_bear_rebreak_event",
        "peak_to_close_drawdown_7d",
        "peak_to_close_drawdown_10d",
        "peak_to_close_drawdown_30d",
        "peak_to_close_drawdown_90d",
        "return_3d",
        "lower_high_lower_low",
        "previous_major_low_broken",
    ]
    features = daily_features[feature_columns].drop_duplicates("signal_date", keep="last")
    overlap = sorted((set(features.columns) - {"signal_date"}) & set(frame.columns))
    base = frame.drop(columns=overlap)
    return base.merge(features, on="signal_date", how="left", validate="many_to_one")
