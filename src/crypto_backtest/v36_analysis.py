from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import daily_history_v31, enriched_summary
from .v31_engine import V31BacktestResult


BOTTOM_BUY_ACTIONS = {
    "B": {
        "TACTICAL_BUYBACK_AHR999_TO_35",
        "TACTICAL_BUYBACK_RIGHT_TO_50",
        "TACTICAL_BUYBACK_RIGHT_TO_60",
    },
    "H": {
        "TACTICAL_BUYBACK_V36_AHR999_TO_35",
        "TACTICAL_BUYBACK_V36_RIGHT_TO_50",
        "TACTICAL_BUYBACK_V36_RIGHT_TO_60",
    },
}


def daily_history_v36(history: pd.DataFrame) -> pd.DataFrame:
    daily = daily_history_v31(history)
    source = history.copy()
    source["date"] = pd.to_datetime(source["timestamp"], utc=True).dt.floor("D")
    extra_columns = [
        "accumulation_episode_id", "accumulation_episode_active", "value_base_buy_used",
        "value_buy_rearmed", "last_accumulation_sell_at", "last_accumulation_buy_at",
        "new_20d_closing_low", "no_new_20d_closing_low_recent3",
    ]
    present = [column for column in extra_columns if column in source]
    if present:
        daily = daily.merge(
            source.groupby("date", as_index=False)[present].last(),
            on="date", how="left", validate="one_to_one",
        )
    return daily


def summary_v36(result: V31BacktestResult, base_rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, base_rules)
    tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["tactical_notional_usd"] = float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0
    row["anti_whipsaw_buy_suppressed_count"] = int(result.counters.get("anti_whipsaw_buy_suppressed_count", 0))
    return row


def _frame_exact(
    left: pd.DataFrame, right: pd.DataFrame, keys: list[str], numeric: list[str], tolerance: float = 1e-10,
) -> tuple[bool, float]:
    if len(left) != len(right):
        return False, float("inf")
    left, right = left.reset_index(drop=True), right.reset_index(drop=True)
    keys_ok = all(
        left[column].fillna("").astype(str).equals(right[column].fillna("").astype(str))
        for column in keys
    )
    delta = max(
        float(np.max(np.abs(left[column].astype(float).to_numpy() - right[column].astype(float).to_numpy())))
        for column in numeric
    ) if len(left) and numeric else 0.0
    return bool(keys_ok and delta <= tolerance), delta


def v31_replay_integrity(
    model_b: V31BacktestResult, v31_dir: Path, reference: dict[str, float],
) -> dict[str, Any]:
    prior_summary = pd.read_csv(v31_dir / "results" / "summary_v3_1.csv").set_index("model")
    prior_trades = pd.read_csv(v31_dir / "results" / "trade_log_v3_1.csv")
    metrics = {
        "final_portfolio_value": float(model_b.summary["final_portfolio_value"]),
        "maximum_drawdown": float(model_b.summary["maximum_drawdown"]),
        "twr_cagr": float(model_b.summary["time_weighted_cagr"]),
        "calmar": float(model_b.summary["calmar"]),
    }
    reference_delta = {key: abs(metrics[key] - float(reference[key])) for key in metrics}
    prior_b = prior_summary.loc["B"]
    prior_delta = {
        key: abs(metrics[key] - float(prior_b[key if key != "twr_cagr" else "twr_cagr"]))
        for key in metrics
    }
    current = model_b.trades.copy()
    prior = prior_trades.loc[prior_trades["model"].eq("B")].copy()
    for data in (current, prior):
        for column in ("timestamp", "signal_date"):
            data[column] = pd.to_datetime(data[column], utc=True, errors="coerce")
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd",
    ]
    trades_pass, trade_delta = _frame_exact(current[keys + numeric], prior[keys + numeric], keys, numeric)
    tactical = current.loc[current["action"].str.startswith("TACTICAL", na=False)]
    event_count = int(tactical["tactical_event_id"].nunique()) if not tactical.empty else 0
    event_pass = event_count == int(reference["tactical_event_count"])
    passed = bool(
        max(reference_delta.values()) <= 1e-9
        and max(prior_delta.values()) <= 1e-9
        and trades_pass and event_pass
    )
    return {
        "pass": passed,
        "reference_metric_max_abs_delta": max(reference_delta.values()),
        "prior_output_metric_max_abs_delta": max(prior_delta.values()),
        "trade_rows_current": len(current), "trade_rows_prior": len(prior),
        "trade_numeric_max_abs_delta": trade_delta, "trade_rows_exact": trades_pass,
        "tactical_event_count": event_count, "tactical_event_count_exact": event_pass,
    }


def fixed_dca_integrity(results: list[V31BacktestResult]) -> pd.DataFrame:
    reference = next(result for result in results if result.scenario.model == "A")
    base = reference.trades.loc[reference.trades["action"].eq("NORMAL_DCA")].copy()
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date"]
    numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd",
    ]
    rows = []
    for result in results:
        if result.scenario.model == "H0":
            continue
        current = result.trades.loc[result.trades["action"].eq("NORMAL_DCA")].copy()
        passed, delta = _frame_exact(current[keys + numeric], base[keys + numeric], keys, numeric)
        rows.append({
            "model": result.scenario.model, "reference_rows": len(base), "rows": len(current),
            "keys_exact": passed if delta <= 1e-10 else False,
            "numeric_max_abs_delta": delta, "all_match": passed,
        })
    return pd.DataFrame(rows)


def fsm_audit(results: list[V31BacktestResult], base_rules: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "H"}:
            continue
        for event in result.transitions.to_dict("records"):
            legal = str(event["to_state"]) in base_rules["allowed_transitions"].get(str(event["from_state"]), [])
            rows.append({"model": result.scenario.model, **event, "legal_transition": legal})
    return pd.DataFrame(rows)


def _bottom_scope(trades: pd.DataFrame, model: str) -> pd.Series:
    action = trades["action"].fillna("")
    reason = trades["reason"].fillna("")
    return action.isin(BOTTOM_BUY_ACTIONS[model]) | reason.eq("ACCUMULATION_BEARISH_REBREAK")


def _signal_type(action: str, reason: str) -> str:
    mapping = {
        "TACTICAL_BUYBACK_AHR999_TO_35": "AHR_BASE_BUY",
        "TACTICAL_BUYBACK_V36_AHR999_TO_35": "AHR_BASE_BUY",
        "TACTICAL_BUYBACK_RIGHT_TO_50": "RIGHT_SIDE_TO50",
        "TACTICAL_BUYBACK_V36_RIGHT_TO_50": "RIGHT_SIDE_TO50",
        "TACTICAL_BUYBACK_RIGHT_TO_60": "RIGHT_SIDE_TO60",
        "TACTICAL_BUYBACK_V36_RIGHT_TO_60": "RIGHT_SIDE_TO60",
    }
    return mapping.get(action, "ACCUMULATION_RISK_SELL" if reason == "ACCUMULATION_BEARISH_REBREAK" else action)


def bottom_whipsaw_audit(
    results: list[V31BacktestResult], feature_daily: pd.DataFrame,
) -> pd.DataFrame:
    feature_map = feature_daily.drop_duplicates("signal_date", keep="last").set_index("signal_date")
    rows: list[dict[str, Any]] = []
    for result in results:
        model = result.scenario.model
        if model not in {"B", "H"}:
            continue
        scoped = result.trades.loc[_bottom_scope(result.trades, model)].copy()
        if scoped.empty:
            continue
        scoped["timestamp"] = pd.to_datetime(scoped["timestamp"], utc=True)
        scoped["signal_date"] = pd.to_datetime(scoped["signal_date"], utc=True)
        events = scoped.groupby(
            ["tactical_event_id", "timestamp", "signal_date", "action", "side", "reason", "cycle_id"],
            dropna=False, as_index=False,
        ).agg(
            exposure_before=("before_crypto_exposure", "first"),
            exposure_after=("after_crypto_exposure", "last"),
            gross_notional=("gross_notional_usd", "sum"),
            fee=("fee_usd", "sum"), slippage=("slippage_usd", "sum"),
        ).sort_values("timestamp")
        signals = result.signals.copy()
        signals["signal_date"] = pd.to_datetime(signals["signal_date"], utc=True)
        signal_map = signals.drop_duplicates("signal_date", keep="last").set_index("signal_date")
        previous_time: pd.Timestamp | None = None
        last_by_side: dict[str, pd.Timestamp] = {}
        for event in events.itertuples():
            sig = signal_map.loc[event.signal_date] if event.signal_date in signal_map.index else pd.Series(dtype=object)
            feature = feature_map.loc[event.signal_date] if event.signal_date in feature_map.index else pd.Series(dtype=object)
            previous_opposite = last_by_side.get("SELL" if event.side == "BUY" else "BUY")
            since_previous = (
                (event.timestamp - previous_time).total_seconds() / 86400.0
                if previous_time is not None else np.nan
            )
            since_opposite = (
                (event.timestamp - previous_opposite).total_seconds() / 86400.0
                if previous_opposite is not None else np.nan
            )
            episode = sig.get("accumulation_episode_id", event.cycle_id)
            rows.append({
                "timestamp": event.timestamp, "model": model, "cycle_id": event.cycle_id,
                "accumulation_episode_id": episode, "action": event.action,
                "signal_type": _signal_type(event.action, event.reason), "reason": event.reason,
                "side": event.side, "exposure_before": event.exposure_before,
                "exposure_after": event.exposure_after,
                "days_since_previous_tactical_action": since_previous,
                "days_since_previous_opposite_action": since_opposite,
                "whipsaw_pair": bool(pd.notna(since_opposite) and since_opposite <= 7.0 + 1e-12),
                "ahr999": sig.get("ahr999", feature.get("ahr999_fixed_arithmetic", np.nan)),
                "btc_close": sig.get("btc_close", feature.get("close", np.nan)),
                "sma20": sig.get("sma20", feature.get("sma20", np.nan)),
                "sma50": sig.get("sma50", feature.get("sma50", np.nan)),
                "sma200": sig.get("sma200", feature.get("sma200", np.nan)),
                "new_20d_closing_low": feature.get("new_20d_closing_low", np.nan),
                "rearm_status": sig.get("rearm_status", "N/A_BASELINE"),
                "rebuy_cooldown": sig.get("rebuy_cooldown", False),
                "gross_notional": event.gross_notional, "fee": event.fee, "slippage": event.slippage,
            })
            previous_time = event.timestamp
            last_by_side[event.side] = event.timestamp
    return pd.DataFrame(rows)


def _bounds(bounds: list[str], cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(bounds[0], tz="UTC")
    end = cutoff if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
    return start, end


def bottom_whipsaw_summary(
    audit: pd.DataFrame, daily_by_model: dict[str, pd.DataFrame], windows: dict[str, list[str]],
) -> pd.DataFrame:
    cutoff = max(pd.Timestamp(daily["date"].max()) for daily in daily_by_model.values())
    periods = {"FULL": ["2020-01-01", "end"], **windows}
    rows = []
    for period, bounds in periods.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "H"):
            segment = audit.loc[
                audit["model"].eq(model)
                & pd.to_datetime(audit["timestamp"], utc=True).between(start, end)
            ]
            ordered_times = pd.to_datetime(segment.sort_values("timestamp")["timestamp"], utc=True)
            days = ordered_times.diff().dt.total_seconds().div(86400).dropna()
            daily = daily_by_model[model]
            daily_segment = daily.loc[daily["date"].between(start, end)]
            notional = float(segment["gross_notional"].sum())
            average_value = float(daily_segment["portfolio_value"].mean()) if not daily_segment.empty else np.nan
            rows.append({
                "period": period, "model": model, "start": start, "end": end,
                "bottom_tactical_event_count": int(len(segment)),
                "bottom_tactical_trade_rows": int(2 * len(segment)),
                "bottom_tactical_notional_usd": notional,
                "bottom_turnover": notional / average_value if average_value else np.nan,
                "whipsaw_pair_count": int(segment["whipsaw_pair"].sum()),
                "average_days_between_events": float(days.mean()) if len(days) else np.nan,
                "median_days_between_events": float(days.median()) if len(days) else np.nan,
            })
    return pd.DataFrame(rows)


def tactical_statistics(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "H"}:
            continue
        tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
        events = tactical.drop_duplicates("tactical_event_id").sort_values("timestamp")
        days = pd.to_datetime(events["timestamp"], utc=True).diff().dt.total_seconds().div(86400).dropna()
        average_value = float(result.history["portfolio_value"].mean())
        notional = float(tactical["gross_notional_usd"].sum())
        rows.append({
            "model": result.scenario.model, "total_tactical_events": int(tactical["tactical_event_id"].nunique()),
            "total_tactical_trade_rows": int(len(tactical)), "tactical_notional_usd": notional,
            "tactical_turnover": notional / average_value,
            "average_days_between_events": float(days.mean()) if len(days) else np.nan,
            "median_days_between_events": float(days.median()) if len(days) else np.nan,
        })
    return pd.DataFrame(rows)


def event_drawdown_audit(
    daily_by_model: dict[str, pd.DataFrame], results: list[V31BacktestResult], windows: dict[str, list[str]],
) -> pd.DataFrame:
    result_map = {result.scenario.model: result for result in results}
    cutoff = max(pd.Timestamp(daily_by_model[model]["date"].max()) for model in ("B", "H"))
    rows = []
    for event, bounds in windows.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "H"):
            segment = daily_by_model[model].loc[lambda x: x["date"].between(start, end)].copy()
            if segment.empty:
                continue
            dd = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            trades = result_map[model].trades
            tactical = trades.loc[
                trades["action"].str.startswith("TACTICAL", na=False)
                & pd.to_datetime(trades["timestamp"], utc=True).between(start, end)
            ]
            rows.append({
                "event": event, "model": model, "start": start, "end": end,
                "peak_to_trough_drawdown": float(dd.min()),
                "average_crypto_exposure": float(segment["crypto_exposure"].mean()),
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "tactical_event_count": int(tactical["tactical_event_id"].nunique()) if not tactical.empty else 0,
                "tactical_notional_usd": float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0,
            })
    return pd.DataFrame(rows)


def promotion_evaluation(
    summary: pd.DataFrame,
    bottom: pd.DataFrame,
    events: pd.DataFrame,
    tactical: pd.DataFrame,
    rules: dict[str, Any],
    *,
    integrity_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    perf = summary.set_index("model")
    b, h = perf.loc["B"], perf.loc["H"]
    bottom_index = bottom.set_index(["period", "model"])
    event_index = events.set_index(["event", "model"])
    tactical_index = tactical.set_index("model")

    def reduction(period: str, column: str) -> float:
        base = float(bottom_index.loc[(period, "B"), column])
        challenger = float(bottom_index.loc[(period, "H"), column])
        return 1.0 - challenger / base if base else (1.0 if challenger == 0 else -np.inf)

    def dd_regression(event: str) -> float:
        return 100.0 * (
            float(event_index.loc[(event, "B"), "peak_to_trough_drawdown"])
            - float(event_index.loc[(event, "H"), "peak_to_trough_drawdown"])
        )

    r2022 = reduction("BOTTOM_2022", "bottom_tactical_event_count")
    r2026 = reduction("BOTTOM_2026", "bottom_tactical_event_count")
    rpair = reduction("FULL", "whipsaw_pair_count")
    turnover_reduction = 1.0 - float(tactical_index.loc["H", "tactical_turnover"]) / float(tactical_index.loc["B", "tactical_turnover"])
    dd2022 = dd_regression("BEAR_2021NOV_2022JUN")
    dd2025 = dd_regression("CORRECTION_2025_2026")
    overall_dd_regression = 100.0 * (float(b["maximum_drawdown"]) - float(h["maximum_drawdown"]))
    gates = rules["promotion_gates"]
    checks = {
        "G1_2022_BOTTOM_EVENTS_REDUCTION_GTE_50PCT": r2022 >= gates["bottom_2022_event_reduction_min_fraction"],
        "G2_2026_BOTTOM_EVENTS_REDUCTION_GTE_50PCT": r2026 >= gates["bottom_2026_event_reduction_min_fraction"],
        "G3_WHIPSAW_PAIRS_REDUCTION_GTE_50PCT": rpair >= gates["whipsaw_pair_reduction_min_fraction"],
        "G4_OVERALL_TURNOVER_REDUCTION_GTE_15PCT": turnover_reduction >= gates["overall_tactical_turnover_reduction_min_fraction"],
        "G5_2022_BEAR_DD_REGRESSION_LTE_2PP": dd2022 <= gates["bear_2021nov_2022jun_dd_regression_max_pp"],
        "G6_2025_2026_DD_REGRESSION_LTE_2PP": dd2025 <= gates["correction_2025_2026_dd_regression_max_pp"],
        "G7_OVERALL_MAX_DD_REGRESSION_LTE_2PP": overall_dd_regression <= gates["overall_max_dd_regression_max_pp"],
        "G8_TWR_CAGR_GTE_45PCT": float(h["twr_cagr"]) >= gates["twr_cagr_minimum"],
        "G9_FINAL_VALUE_GTE_95PCT_OF_B": float(h["final_portfolio_value"]) >= gates["final_value_min_fraction_of_v31_b"] * float(b["final_portfolio_value"]),
        "G10_ALL_INTEGRITY_PASS": bool(integrity_pass),
    }
    promoted = all(checks.values())
    verdict = (
        "A. V3.6 PROMOTED TO FORWARD PAPER TEST"
        if promoted else "B. V3.1 REMAINS CHAMPION" if integrity_pass else "C. V3.6 ANTI-WHIPSAW PATCH REJECTED"
    )
    comparison = pd.DataFrame([{
        "comparison": "H V3.6 vs B V3.1",
        "delta_final_value": float(h["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": 100 * float(h["twr_cagr"] - b["twr_cagr"]),
        "delta_max_drawdown_percentage_points": 100 * float(h["maximum_drawdown"] - b["maximum_drawdown"]),
        "delta_calmar": float(h["calmar"] - b["calmar"]),
        "bottom_2022_event_reduction_fraction": r2022,
        "bottom_2026_event_reduction_fraction": r2026,
        "whipsaw_pair_reduction_fraction": rpair,
        "overall_turnover_reduction_fraction": turnover_reduction,
        "2022_bear_dd_regression_percentage_points": dd2022,
        "2025_2026_dd_regression_percentage_points": dd2025,
        "overall_max_dd_regression_percentage_points": overall_dd_regression,
    }])
    return comparison, {
        "promotion_gate": "PASS" if promoted else "FAIL",
        "checks": {key: bool(value) for key, value in checks.items()},
        "final_verdict": verdict,
    }


def no_lookahead_audit(
    frame: pd.DataFrame,
    daily_features: pd.DataFrame,
    results: list[V31BacktestResult],
    data_contract: dict[str, Any],
    fixed_dca: pd.DataFrame,
    fsm: pd.DataFrame,
    replay: dict[str, Any],
    prefix_checks: dict[str, bool],
    engine_source: str,
    indicator_source: str,
) -> dict[str, Any]:
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    timing_violations = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    h = next(result for result in results if result.scenario.model == "H")
    ht = h.trades.loc[h.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    direction = ht.groupby("timestamp")["side"].nunique() if not ht.empty else pd.Series(dtype=int)
    same_timestamp_opposite_violations = int((direction > 1).sum())
    engine_forbidden = [token for token in ("v32_", "v33_", "v34_", "v35_", "requalification", "level3") if token in engine_source.lower()]
    future_tokens = [token for token in ("shift(-", "future_min_return", "bear_label", "label_end_date") if token in (engine_source + indicator_source)]
    completed_feature_violations = int((daily_features["close_time"] >= daily_features["signal_available_at"]).sum())
    checks = {
        "data_contract_pass": bool(data_contract["pass"]),
        "signal_available_no_later_than_execution": int((frame["signal_available_at"] > frame["open_time"]).sum()) == 0,
        "completed_daily_features_only": completed_feature_violations == 0,
        "tactical_execution_next_4h_or_later": timing_violations == 0,
        "no_future_columns_in_execution_frame": not data_contract["future_label_columns_in_execution_frame"],
        "fixed_dca_row_integrity": bool(fixed_dca["all_match"].all()),
        "fsm_legal": bool(not fsm.empty and fsm["legal_transition"].all()),
        "v31_replay_exact": bool(replay["pass"]),
        "prefix_invariance": bool(all(prefix_checks.values())),
        "no_same_timestamp_opposite_tactical_action": same_timestamp_opposite_violations == 0,
        "v36_engine_has_no_v32_v35_inheritance": not engine_forbidden,
        "no_future_tokens_in_execution_sources": not future_tokens,
    }
    return {
        "no_lookahead_pass": bool(all(checks.values())),
        "execution_integrity_pass": bool(
            checks["fixed_dca_row_integrity"] and checks["fsm_legal"]
            and checks["v31_replay_exact"] and checks["no_same_timestamp_opposite_tactical_action"]
        ),
        "checks": checks, "timing_violations": timing_violations,
        "completed_feature_violations": completed_feature_violations,
        "same_timestamp_opposite_tactical_action_violations": same_timestamp_opposite_violations,
        "forbidden_inheritance_tokens": engine_forbidden, "future_tokens": future_tokens,
    }


__all__ = [
    "bottom_whipsaw_audit", "bottom_whipsaw_summary", "daily_history_v36",
    "event_drawdown_audit", "fixed_dca_integrity", "fsm_audit", "no_lookahead_audit",
    "promotion_evaluation", "summary_v36", "tactical_statistics", "v31_replay_integrity",
]
