from __future__ import annotations

from typing import Any, Iterable

import numpy as np
import pandas as pd

from .v31_analysis import enriched_summary
from .v31_engine import V31BacktestResult


def daily_last(history: pd.DataFrame) -> pd.DataFrame:
    work = history[["timestamp", "portfolio_value", "crypto_exposure"]].copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    return work.groupby("date", as_index=False).last()


def _value_at(history: pd.DataFrame, timestamp: pd.Timestamp) -> tuple[pd.Timestamp, float]:
    times = pd.DatetimeIndex(pd.to_datetime(history["timestamp"], utc=True))
    position = int(times.searchsorted(timestamp, side="left"))
    position = min(position, len(history) - 1)
    return pd.Timestamp(times[position]), float(history.iloc[position]["portfolio_value"])


def _local_drawdown(history: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    timestamps = pd.to_datetime(history["timestamp"], utc=True)
    values = history.loc[timestamps.between(start, end), "portfolio_value"].to_numpy(dtype=float)
    if len(values) == 0:
        return np.nan
    peaks = np.maximum.accumulate(values)
    return float(np.min(values / peaks - 1.0))


def major_transition_times(shadow: V31BacktestResult, events: pd.DataFrame) -> list[pd.Timestamp]:
    values: set[pd.Timestamp] = set()
    if not shadow.transitions.empty:
        values.update(pd.to_datetime(shadow.transitions["execution_4h_open"], utc=True).tolist())
    history = shadow.history[["timestamp", "cycle_id"]].copy()
    history["timestamp"] = pd.to_datetime(history["timestamp"], utc=True)
    changes = history.loc[history["cycle_id"].ne(history["cycle_id"].shift())]
    values.update(changes["timestamp"].tolist())
    structural = events.loc[
        events["signal_type"].isin(["RIGHT_SIDE_BUY", "NEW_BULL_REDEPLOY"]), "timestamp"
    ]
    values.update(pd.to_datetime(structural, utc=True).tolist())
    return sorted(values)


def next_transition_after(
    timestamp: pd.Timestamp,
    transitions: list[pd.Timestamp],
    sample_end: pd.Timestamp,
) -> pd.Timestamp:
    for value in transitions:
        if value > timestamp:
            return value
    return sample_end


def resynchronization_metrics(
    baseline_history: pd.DataFrame,
    counterfactual_history: pd.DataFrame,
    start: pd.Timestamp,
    tolerance_fraction: float,
    consecutive_closes: int,
) -> dict[str, Any]:
    base = daily_last(baseline_history).rename(columns={
        "portfolio_value": "baseline_value", "crypto_exposure": "baseline_exposure"
    })
    cf = daily_last(counterfactual_history).rename(columns={
        "portfolio_value": "counterfactual_value", "crypto_exposure": "counterfactual_exposure"
    })
    joined = base.merge(cf, on="date", validate="one_to_one")
    joined = joined.loc[joined["date"] >= start.floor("D")].copy()
    joined["exposure_difference"] = joined["counterfactual_exposure"] - joined["baseline_exposure"]
    within = joined["exposure_difference"].abs().le(tolerance_fraction).to_numpy()
    confirm_position: int | None = None
    streak = 0
    for position, flag in enumerate(within):
        streak = streak + 1 if flag else 0
        if streak >= consecutive_closes:
            confirm_position = position
            break
    if confirm_position is None:
        segment = joined
        resync_date: Any = pd.NaT
        status = "NOT_RESYNCED"
        days = np.nan
    else:
        segment = joined.iloc[: confirm_position + 1]
        resync_date = pd.Timestamp(joined.iloc[confirm_position]["date"])
        status = "RESYNCED"
        days = (resync_date - start.floor("D")).total_seconds() / 86_400.0
    return {
        "first_resync_date": resync_date,
        "days_to_resync": days,
        "resync_status": status,
        "net_crypto_exposure_day_difference": float(segment["exposure_difference"].sum()),
        "absolute_crypto_exposure_day_difference": float(segment["exposure_difference"].abs().sum()),
    }


def attribution_record(
    baseline: V31BacktestResult,
    counterfactual: V31BacktestResult,
    audit: pd.DataFrame,
    rules: dict[str, Any],
    audit_rules: dict[str, Any],
    *,
    anchor_timestamp: pd.Timestamp,
    next_transition: pd.Timestamp,
    deleted_event_ids: Iterable[int],
) -> dict[str, Any]:
    base = enriched_summary(baseline, rules)
    cf = enriched_summary(counterfactual, rules)
    base_history = baseline.history
    cf_history = counterfactual.history
    deleted = {int(value) for value in deleted_event_ids}
    record: dict[str, Any] = {
        "baseline_final_value": base["final_portfolio_value"],
        "counterfactual_final_value": cf["final_portfolio_value"],
        "final_wealth_contribution": base["final_portfolio_value"] - cf["final_portfolio_value"],
        "final_wealth_contribution_fraction": (
            (base["final_portfolio_value"] - cf["final_portfolio_value"])
            / base["final_portfolio_value"]
        ),
        "delta_twr_cagr_pp": 100.0 * (base["twr_cagr"] - cf["twr_cagr"]),
        "delta_xirr_pp": 100.0 * (base["xirr"] - cf["xirr"]),
        "delta_sharpe": base["sharpe"] - cf["sharpe"],
        "delta_sortino": base["sortino"] - cf["sortino"],
        "delta_calmar": base["calmar"] - cf["calmar"],
        "baseline_max_dd": base["maximum_drawdown"],
        "counterfactual_max_dd": cf["maximum_drawdown"],
        "dd_protection_contribution_pp": 100.0 * (
            base["maximum_drawdown"] - cf["maximum_drawdown"]
        ),
        "baseline_tactical_events": base["tactical_event_count"],
        "counterfactual_tactical_events": cf["tactical_event_count"],
        "tactical_events_removed_direct": len(deleted),
        "tactical_events_removed_indirect": int(
            audit.loc[~audit["directly_deleted"].astype(bool), "indirect_no_fill"].astype(bool).sum()
        ),
        "tactical_trade_rows_removed": base["tactical_trade_count"] - cf["tactical_trade_count"],
        "gross_notional_saved": (
            baseline.trades.loc[baseline.trades["action"].str.startswith("TACTICAL", na=False), "gross_notional_usd"].sum()
            - counterfactual.trades.loc[counterfactual.trades["action"].str.startswith("TACTICAL", na=False), "gross_notional_usd"].sum()
        ),
        "turnover_saved": base["tactical_turnover"] - cf["tactical_turnover"],
        "fees_saved": base["tactical_fees"] - cf["tactical_fees"],
        "slippage_saved": base["tactical_slippage"] - cf["tactical_slippage"],
        "total_trading_cost_saved": base["tactical_costs"] - cf["tactical_costs"],
        "next_major_transition_date": next_transition,
    }
    horizons = audit_rules["local_attribution"]["portfolio_value_horizons_calendar_days"]
    for days in horizons:
        target = anchor_timestamp + pd.Timedelta(days=int(days))
        observed, base_value = _value_at(base_history, target)
        _, cf_value = _value_at(cf_history, target)
        record[f"observed_date_{days}d"] = observed
        record[f"baseline_value_{days}d"] = base_value
        record[f"counterfactual_value_{days}d"] = cf_value
        record[f"portfolio_value_contribution_{days}d"] = base_value - cf_value
    _, base_transition_value = _value_at(base_history, next_transition)
    _, cf_transition_value = _value_at(cf_history, next_transition)
    record["baseline_value_next_transition"] = base_transition_value
    record["counterfactual_value_next_transition"] = cf_transition_value
    record["portfolio_value_contribution_next_transition"] = base_transition_value - cf_transition_value

    dd_protections: list[float] = []
    for days in audit_rules["local_attribution"]["drawdown_horizons_calendar_days"]:
        end = anchor_timestamp + pd.Timedelta(days=int(days))
        base_dd = _local_drawdown(base_history, anchor_timestamp, end)
        cf_dd = _local_drawdown(cf_history, anchor_timestamp, end)
        protection = 100.0 * (base_dd - cf_dd)
        record[f"baseline_local_dd_{days}d"] = base_dd
        record[f"counterfactual_local_dd_{days}d"] = cf_dd
        record[f"local_dd_protection_{days}d_pp"] = protection
        dd_protections.append(protection)
    base_next_dd = _local_drawdown(base_history, anchor_timestamp, next_transition)
    cf_next_dd = _local_drawdown(cf_history, anchor_timestamp, next_transition)
    next_protection = 100.0 * (base_next_dd - cf_next_dd)
    record["baseline_local_dd_next_transition"] = base_next_dd
    record["counterfactual_local_dd_next_transition"] = cf_next_dd
    record["local_dd_protection_next_transition_pp"] = next_protection
    dd_protections.append(next_protection)
    record["max_local_dd_protection_pp"] = float(np.nanmax(dd_protections))
    record.update(resynchronization_metrics(
        base_history,
        cf_history,
        anchor_timestamp,
        float(audit_rules["resynchronization"]["absolute_exposure_tolerance_percentage_points"]) / 100.0,
        int(audit_rules["resynchronization"]["consecutive_completed_daily_closes"]),
    ))
    return record


def classification_flags(row: pd.Series, thresholds: dict[str, float]) -> dict[str, bool]:
    final_fraction = float(row["final_wealth_contribution_fraction"])
    overall_dd = float(row["dd_protection_contribution_pp"])
    local_dd = float(row["max_local_dd_protection_pp"])
    risk_protection = max(overall_dd, local_dd)
    delete_dd_improvement = max(-overall_dd, -local_dd)
    harmful_gain = -final_fraction
    return {
        "conflict": bool(
            (harmful_gain >= thresholds["harmful_delete_final_gain_min_fraction"]
             and risk_protection >= thresholds["risk_essential_dd_worsening_min_pp"])
            or
            (final_fraction >= thresholds["return_essential_final_loss_min_fraction"]
             and delete_dd_improvement >= thresholds["return_essential_delete_dd_improvement_max_pp"])
        ),
        "risk_essential": risk_protection >= thresholds["risk_essential_dd_worsening_min_pp"],
        "return_essential": bool(
            final_fraction >= thresholds["return_essential_final_loss_min_fraction"]
            and delete_dd_improvement < thresholds["return_essential_delete_dd_improvement_max_pp"]
        ),
        "harmful": bool(
            harmful_gain >= thresholds["harmful_delete_final_gain_min_fraction"]
            and risk_protection < thresholds["harmful_dd_worsening_max_pp"]
        ),
        "redundant": bool(
            abs(final_fraction) <= thresholds["redundant_abs_final_max_fraction"]
            and abs(overall_dd) <= thresholds["redundant_abs_dd_max_pp"]
            and abs(local_dd) <= thresholds["redundant_abs_dd_max_pp"]
        ),
    }


def classify_row(row: pd.Series, thresholds: dict[str, float]) -> str:
    flags = classification_flags(row, thresholds)
    if flags["conflict"]:
        return "MIXED_UNCERTAIN"
    if flags["risk_essential"]:
        return "RISK_ESSENTIAL"
    if flags["return_essential"]:
        return "RETURN_ESSENTIAL"
    if flags["harmful"]:
        return "HARMFUL"
    if flags["redundant"]:
        return "REDUNDANT"
    return "MIXED_UNCERTAIN"


def apply_classifications(frame: pd.DataFrame, audit_rules: dict[str, Any]) -> pd.DataFrame:
    out = frame.copy()
    labels = []
    for name in ("loose", "base", "strict"):
        column = f"classification_{name}"
        out[column] = [
            classify_row(row, audit_rules["classification"][name])
            for _, row in out.iterrows()
        ]
        labels.append(column)
    out["classification"] = out["classification_base"]
    out["robust_classification"] = out[labels].nunique(axis=1).eq(1)
    out["classification_direction_note"] = (
        "Positive final contribution means baseline event helped wealth; positive DD contribution means it protected drawdown"
    )
    return out


def add_whipsaw_labels(events: pd.DataFrame, signal_times: pd.Series) -> pd.DataFrame:
    out = events.copy().sort_values("timestamp").reset_index(drop=True)
    signal_index = {
        pd.Timestamp(timestamp): index
        for index, timestamp in enumerate(pd.to_datetime(signal_times, utc=True))
    }
    flags = {name: np.zeros(len(out), dtype=bool) for name in [
        "opposite_action_within_3_closes", "opposite_action_within_7_days", "opposite_action_within_14_days"
    ]}
    for position in range(len(out) - 1):
        current = out.iloc[position]
        following = out.iloc[position + 1]
        if current["side"] == following["side"]:
            continue
        gap_days = (following["timestamp"] - current["timestamp"]).total_seconds() / 86_400.0
        close_gap = signal_index.get(pd.Timestamp(following["timestamp"]), 10**9) - signal_index.get(
            pd.Timestamp(current["timestamp"]), -10**9
        )
        if 1 <= close_gap <= 3:
            flags["opposite_action_within_3_closes"][position] = True
            flags["opposite_action_within_3_closes"][position + 1] = True
        if gap_days <= 7:
            flags["opposite_action_within_7_days"][position] = True
            flags["opposite_action_within_7_days"][position + 1] = True
        if gap_days <= 14:
            flags["opposite_action_within_14_days"][position] = True
            flags["opposite_action_within_14_days"][position + 1] = True
    for name, values in flags.items():
        out[name] = values
    return out


def identify_round_trip_clusters(events: pd.DataFrame, audit_rules: dict[str, Any]) -> pd.DataFrame:
    ordered = events.sort_values(["timestamp", "tactical_event_id"]).reset_index(drop=True)
    tolerance = float(audit_rules["cluster_identification"]["exposure_return_tolerance_percentage_points"]) / 100.0
    inactivity = float(audit_rules["cluster_identification"]["inactivity_boundary_calendar_days"])
    rows: list[dict[str, Any]] = []
    i = 0
    cluster_id = 0
    while i < len(ordered):
        cluster_id += 1
        start = i
        start_exposure = float(ordered.iloc[start]["exposure_before"])
        start_cycle = int(ordered.iloc[start]["cycle_id"])
        end = start
        boundary = "SAMPLE_END"
        j = start + 1
        while j < len(ordered):
            current = ordered.iloc[j]
            previous = ordered.iloc[j - 1]
            if int(current["cycle_id"]) != start_cycle:
                boundary = "NEW_MACRO_CYCLE_BEFORE_EVENT"
                break
            end = j
            if current["signal_type"] in {"RIGHT_SIDE_BUY", "NEW_BULL_REDEPLOY"}:
                boundary = "STRUCTURAL_TRANSITION_INCLUDED"
                j += 1
                break
            returned = abs(float(current["exposure_after"]) - start_exposure) <= tolerance
            if returned:
                boundary = "RETURN_TO_START_EXPOSURE"
                j += 1
                break
            if j + 1 < len(ordered):
                gap = (ordered.iloc[j + 1]["timestamp"] - current["timestamp"]).total_seconds() / 86_400.0
                if gap > inactivity:
                    boundary = "INACTIVITY_GT_30_DAYS"
                    j += 1
                    break
            j += 1
        else:
            j = len(ordered)
        if end == start and start + 1 < len(ordered):
            gap = (ordered.iloc[start + 1]["timestamp"] - ordered.iloc[start]["timestamp"]).total_seconds() / 86_400.0
            if gap > inactivity:
                boundary = "INACTIVITY_GT_30_DAYS"
                j = start + 1
        cluster = ordered.iloc[start : end + 1]
        rows.append({
            "cluster_id": cluster_id,
            "start_date": cluster.iloc[0]["timestamp"],
            "end_date": cluster.iloc[-1]["timestamp"],
            "duration_days": (cluster.iloc[-1]["timestamp"] - cluster.iloc[0]["timestamp"]).total_seconds() / 86_400.0,
            "events_inside": "|".join(str(int(value)) for value in cluster["tactical_event_id"]),
            "event_count": len(cluster),
            "signal_types": "|".join(cluster["signal_type"].astype(str)),
            "signal_sequence": " -> ".join(cluster["side"].astype(str) + ":" + cluster["signal_type"].astype(str)),
            "start_exposure": start_exposure,
            "max_exposure": float(pd.concat([cluster["exposure_before"], cluster["exposure_after"]]).max()),
            "end_exposure": float(cluster.iloc[-1]["exposure_after"]),
            "gross_notional": float(cluster["gross_notional"].sum()),
            "turnover_notional": float(cluster["gross_notional"].sum()),
            "cost": float(cluster["cost"].sum()),
            "boundary_reason": boundary,
            "opposite_action_within_3_closes": bool(cluster["opposite_action_within_3_closes"].any()),
            "opposite_action_within_7_days": bool(cluster["opposite_action_within_7_days"].any()),
            "opposite_action_within_14_days": bool(cluster["opposite_action_within_14_days"].any()),
        })
        i = max(end + 1, j if j > start else start + 1)
    return pd.DataFrame(rows)


def build_event_features(
    events: pd.DataFrame,
    frame: pd.DataFrame,
    forward_horizons: list[int],
) -> pd.DataFrame:
    rows = frame.copy()
    rows["open_time"] = pd.to_datetime(rows["open_time"], utc=True)
    signal_rows = rows.loc[rows["signal_date"].notna()].drop_duplicates("signal_date", keep="first").copy()
    signal_rows["signal_date"] = pd.to_datetime(signal_rows["signal_date"], utc=True)
    signal_rows = signal_rows.sort_values("signal_date")
    close = signal_rows["BTC_daily_close"].astype(float)
    signal_rows["return_20d"] = close / close.shift(20) - 1.0
    signal_rows["return_60d"] = close / close.shift(60) - 1.0
    signal_rows["sma20_slope_3d"] = signal_rows["sma20"].astype(float) / signal_rows["sma20"].astype(float).shift(3) - 1.0
    signal_rows["distance_to_20d_low"] = close / close.rolling(20).min() - 1.0
    signal_rows["distance_to_60d_low"] = close / close.rolling(60).min() - 1.0
    signal_rows["bb_middle"] = (signal_rows["bb_upper"] + signal_rows["bb_lower"]) / 2.0
    signal_rows["bb_band_width"] = (
        (signal_rows["bb_upper"] - signal_rows["bb_lower"]) / signal_rows["bb_middle"]
    )
    feature_columns = [
        "signal_date", "BTC_daily_close", "ahr999_fixed_arithmetic", "sma10", "sma20", "sma50", "sma200",
        "bb_upper", "bb_middle", "bb_lower", "bb_band_width", "close_sma20_dev", "close_sma50_dev",
        "close_sma200_dev", "return_20d", "return_60d", "rolling_volatility20",
        "distance_to_20d_low", "distance_to_60d_low", "sma20_slope_3d",
    ]
    out = events.merge(signal_rows[feature_columns], on="signal_date", how="left", validate="many_to_one")
    out = out.rename(columns={
        "BTC_daily_close": "btc_completed_daily_close",
        "ahr999_fixed_arithmetic": "ahr999",
        "close_sma20_dev": "distance_to_sma20",
        "close_sma50_dev": "distance_to_sma50",
        "close_sma200_dev": "distance_to_sma200",
        "rolling_volatility20": "realized_volatility_20d",
    })
    open_rows = rows.set_index("open_time")
    out["btc_execution_price"] = [float(open_rows.loc[timestamp, "BTC_open"]) for timestamp in out["timestamp"]]
    out["eth_execution_price"] = [float(open_rows.loc[timestamp, "ETH_open"]) for timestamp in out["timestamp"]]
    times = pd.DatetimeIndex(rows["open_time"])
    for horizon in forward_horizons:
        btc_values: list[float] = []
        eth_values: list[float] = []
        for event in out.itertuples():
            target = pd.Timestamp(event.timestamp) + pd.Timedelta(days=int(horizon))
            position = int(times.searchsorted(target, side="left"))
            if position >= len(rows):
                btc_values.append(np.nan)
                eth_values.append(np.nan)
            else:
                btc_values.append(float(rows.iloc[position]["BTC_close"]) / float(event.btc_execution_price) - 1.0)
                eth_values.append(float(rows.iloc[position]["ETH_close"]) / float(event.eth_execution_price) - 1.0)
        out[f"ex_post_btc_forward_return_{horizon}d"] = btc_values
        out[f"ex_post_eth_forward_return_{horizon}d"] = eth_values
    out["forward_outcome_usage"] = "EX_POST_DIAGNOSTIC_ONLY"
    out["ahr_environment"] = np.select(
        [
            (out["btc_completed_daily_close"] < out["sma20"]) & (out["sma20_slope_3d"] < 0),
            out["btc_completed_daily_close"] < out["sma20"],
            out["distance_to_20d_low"] <= 0.05,
        ],
        ["BELOW_SMA20_FALLING", "BELOW_SMA20_NOT_FALLING", "ABOVE_SMA20_NEAR_20D_LOW"],
        default="ABOVE_SMA20_NOT_NEAR_LOW",
    )
    return out


def signal_type_summary(event_results: pd.DataFrame) -> pd.DataFrame:
    return event_results.groupby("signal_type", as_index=False).agg(
        count=("tactical_event_id", "size"),
        median_final_contribution=("final_wealth_contribution", "median"),
        mean_final_contribution=("final_wealth_contribution", "mean"),
        median_local_30d_contribution=("portfolio_value_contribution_30d", "median"),
        median_turnover_saved=("turnover_saved", "median"),
        median_cost_saved=("total_trading_cost_saved", "median"),
        positive_contribution_fraction=("final_wealth_contribution", lambda x: float((x > 0).mean())),
        negative_contribution_fraction=("final_wealth_contribution", lambda x: float((x < 0).mean())),
        median_dd_protection_pp=("dd_protection_contribution_pp", "median"),
        robust_classification_fraction=("robust_classification", "mean"),
    )


def whipsaw_summary(event_results: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, column in [
        ("3_COMPLETED_CLOSES", "opposite_action_within_3_closes"),
        ("7_CALENDAR_DAYS", "opposite_action_within_7_days"),
        ("14_CALENDAR_DAYS", "opposite_action_within_14_days"),
    ]:
        subset = event_results.loc[event_results[column].astype(bool)]
        rows.append({
            "whipsaw_window": label,
            "count": len(subset),
            "median_final_contribution": float(subset["final_wealth_contribution"].median()) if len(subset) else np.nan,
            "positive_contribution_fraction": float((subset["final_wealth_contribution"] > 0).mean()) if len(subset) else np.nan,
            "median_dd_protection_pp": float(subset["dd_protection_contribution_pp"].median()) if len(subset) else np.nan,
            "median_turnover_saved": float(subset["turnover_saved"].median()) if len(subset) else np.nan,
            "median_cost_saved": float(subset["total_trading_cost_saved"].median()) if len(subset) else np.nan,
        })
    return pd.DataFrame(rows)


__all__ = [
    "add_whipsaw_labels",
    "apply_classifications",
    "attribution_record",
    "build_event_features",
    "daily_last",
    "identify_round_trip_clusters",
    "major_transition_times",
    "next_transition_after",
    "signal_type_summary",
    "whipsaw_summary",
]
