from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import _drawdown_detail, daily_history_v31, enriched_summary, prefix_trade_identity
from .v31_engine import V31BacktestResult


def daily_history_v33(history: pd.DataFrame) -> pd.DataFrame:
    return daily_history_v31(history)


def summary_v33(result: V31BacktestResult, rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, rules)
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["median_tactical_cash"] = float(result.history["tactical_cash"].median())
    row["accumulation_drift_sell_count"] = int(result.counters.get("accumulation_drift_sell_count", 0))
    return row


def _frame_exact(
    left: pd.DataFrame,
    right: pd.DataFrame,
    keys: list[str],
    numeric: list[str],
    tolerance: float = 1e-10,
) -> tuple[bool, float]:
    if len(left) != len(right):
        return False, float("inf")
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
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
    model_b: V31BacktestResult,
    v31_dir: Path,
    reference: dict[str, float],
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
        "final_portfolio_value": abs(metrics["final_portfolio_value"] - float(prior_b["final_portfolio_value"])),
        "maximum_drawdown": abs(metrics["maximum_drawdown"] - float(prior_b["maximum_drawdown"])),
        "twr_cagr": abs(metrics["twr_cagr"] - float(prior_b["twr_cagr"])),
        "calmar": abs(metrics["calmar"] - float(prior_b["calmar"])),
    }
    current = model_b.trades.copy()
    prior = prior_trades.loc[prior_trades["model"].eq("B")].copy()
    for frame in (current, prior):
        for column in ("timestamp", "signal_date"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd",
    ]
    trades_pass, trade_delta = _frame_exact(current[keys + numeric], prior[keys + numeric], keys, numeric)
    passed = bool(max(reference_delta.values()) <= 1e-10 and max(prior_delta.values()) <= 1e-10 and trades_pass)
    return {
        "pass": passed,
        "reference_metric_max_abs_delta": max(reference_delta.values()),
        "prior_output_metric_max_abs_delta": max(prior_delta.values()),
        "trade_rows_current": len(current),
        "trade_rows_prior": len(prior),
        "trade_numeric_max_abs_delta": trade_delta,
        "trade_rows_exact": trades_pass,
    }


def fixed_dca_integrity(results: list[V31BacktestResult]) -> pd.DataFrame:
    reference_result = next(result for result in results if result.scenario.model == "A")
    reference = reference_result.trades.loc[reference_result.trades["action"].eq("NORMAL_DCA")].copy()
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
        passed, delta = _frame_exact(current[keys + numeric], reference[keys + numeric], keys, numeric)
        rows.append({
            "model": result.scenario.model, "reference_rows": len(reference), "rows": len(current),
            "numeric_max_abs_delta": delta, "all_match": passed,
        })
    return pd.DataFrame(rows)


def fsm_audit(results: list[V31BacktestResult], rules: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for result in results:
        if not result.scenario.use_fsm:
            continue
        for _, event in result.transitions.iterrows():
            legal = str(event["to_state"]) in rules["allowed_transitions"].get(str(event["from_state"]), [])
            rows.append({"model": result.scenario.model, **event.to_dict(), "legal_transition": legal})
    return pd.DataFrame(rows)


def churn_audit(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.scenario.model not in {"B", "E"}:
            continue
        transitions = result.transitions.copy()
        for from_state, to_state in (("BEAR", "DEEP_BEAR"), ("DEEP_BEAR", "BEAR")):
            count = int(((transitions["from_state"] == from_state) & (transitions["to_state"] == to_state)).sum())
            rows.append({
                "model": result.scenario.model, "record_type": "transition_count",
                "state": f"{from_state}->{to_state}", "count": count,
                "average_dwell_days": np.nan, "median_dwell_days": np.nan,
            })
        signals = result.signals.sort_values("signal_date").copy()
        if signals.empty:
            continue
        signals["signal_date"] = pd.to_datetime(signals["signal_date"], utc=True)
        signals["run_id"] = signals["state_after"].ne(signals["state_after"].shift()).cumsum()
        runs = signals.groupby(["run_id", "state_after"], as_index=False).agg(
            start=("signal_date", "min"), end=("signal_date", "max"), observations=("signal_date", "size")
        )
        runs["dwell_days"] = (runs["end"] - runs["start"]).dt.total_seconds().div(86400.0) + 1.0
        for state in ("BEAR", "DEEP_BEAR"):
            group = runs.loc[runs["state_after"].eq(state)]
            rows.append({
                "model": result.scenario.model, "record_type": "state_dwell", "state": state,
                "count": len(group),
                "average_dwell_days": float(group["dwell_days"].mean()) if not group.empty else np.nan,
                "median_dwell_days": float(group["dwell_days"].median()) if not group.empty else np.nan,
            })
    return pd.DataFrame(rows)


def accumulation_exposure_audit(result_e: V31BacktestResult) -> tuple[pd.DataFrame, pd.DataFrame]:
    signals = result_e.signals.copy()
    work = signals.loc[signals["accumulation_observed_state"].eq("ACCUMULATION")].copy()
    audit = pd.DataFrame({
        "date": pd.to_datetime(work["signal_date"], utc=True),
        "state": work["accumulation_observed_state"],
        "active_target_exposure": work["accumulation_observed_target"].astype(float),
        "actual_crypto_exposure": work["accumulation_observed_exposure"].astype(float),
        "upper_band": work["accumulation_upper_band"].astype(float),
        "days_above_upper_band": work["accumulation_days_above_upper"].astype(int),
        "drift_sell_triggered": work["accumulation_drift_sell_triggered"].astype(bool),
        "post_trade_exposure": work["accumulation_post_trade_exposure"].astype(float),
        "cooldown_active": work["accumulation_drift_cooldown_active"].astype(bool),
        "accumulation_lock_active": work["accumulation_lock_active"].astype(bool),
    })
    over_80 = ((audit["active_target_exposure"] <= 0.60) & (audit["actual_crypto_exposure"] > 0.80))
    run_id = over_80.ne(over_80.shift()).cumsum() if not audit.empty else pd.Series(dtype=int)
    longest_over_80 = int(over_80.groupby(run_id).sum().max()) if not audit.empty else 0
    stats = pd.DataFrame([{
        "maximum_accumulation_exposure": float(audit["actual_crypto_exposure"].max()) if not audit.empty else np.nan,
        "average_accumulation_exposure": float(audit["actual_crypto_exposure"].mean()) if not audit.empty else np.nan,
        "days_exposure_above_target_plus_10pp": int((audit["actual_crypto_exposure"] > audit["active_target_exposure"] + 0.10).sum()),
        "days_exposure_above_target_plus_20pp": int((audit["actual_crypto_exposure"] > audit["active_target_exposure"] + 0.20).sum()),
        "days_exposure_above_80pct_with_target_lte_60pct": int(((audit["active_target_exposure"] <= 0.60) & (audit["actual_crypto_exposure"] > 0.80)).sum()),
        "days_exposure_above_90pct_with_target_lte_60pct": int(((audit["active_target_exposure"] <= 0.60) & (audit["actual_crypto_exposure"] > 0.90)).sum()),
        "longest_consecutive_days_above_80pct_with_target_lte_60pct": longest_over_80,
        "drift_sell_signal_days": int(audit["drift_sell_triggered"].sum()),
    }])
    return audit, stats


def _event_from_transitions(result: V31BacktestResult, cycle_id: int, to_state: str) -> pd.Timestamp | pd.NaT:
    matching = result.transitions.loc[
        result.transitions["cycle_id"].eq(cycle_id) & result.transitions["to_state"].eq(to_state)
    ]
    return pd.Timestamp(matching.iloc[0]["signal_date"]) if not matching.empty else pd.NaT


def cycle_duration_audit(results: list[V31BacktestResult], rules: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    long_days = float(rules["diagnostic_guardrails"]["cycle_long_warning_days"])
    extreme_days = float(rules["diagnostic_guardrails"]["cycle_extreme_warning_days"])
    for result in results:
        if result.scenario.model not in {"B", "E"} or result.cycles.empty:
            continue
        for _, cycle in result.cycles.loc[result.cycles["confirmed"].astype(bool)].iterrows():
            cycle_id = int(cycle["cycle_id"])
            start = pd.Timestamp(cycle["start"])
            end = pd.Timestamp(cycle["end"]) if pd.notna(cycle["end"]) else pd.NaT
            duration = (end - start).total_seconds() / 86400.0 if pd.notna(end) else np.nan
            accumulation = cycle.get("accumulation_date", pd.NaT)
            new_bull = cycle.get("new_bull_date", pd.NaT)
            bull = cycle.get("bull_date", pd.NaT)
            if pd.isna(accumulation):
                accumulation = _event_from_transitions(result, cycle_id, "ACCUMULATION")
            if pd.isna(new_bull):
                new_bull = _event_from_transitions(result, cycle_id, "NEW_BULL")
            if pd.isna(bull):
                bull = _event_from_transitions(result, cycle_id, "BULL")
            status = str(cycle["status"])
            closed = bool(cycle.get("cycle_closed", status in {"COMPLETED_NEW_BULL", "ABORTED_DISTRIBUTION"}))
            warning = (
                "EXTREME_CYCLE_WARNING" if pd.notna(duration) and duration > extreme_days else
                "LONG_CYCLE_WARNING" if pd.notna(duration) and duration > long_days else "NONE"
            )
            reason = (
                "cycle remains open at the formal cutoff" if status in {"OPEN_AT_END", "CLOSING_NEW_BULL_AT_END"}
                else "cycle closed by the recorded NEW_BULL-to-BULL redeploy completion"
            )
            rows.append({
                "model": result.scenario.model, "cycle_id": cycle_id,
                "start_date": start, "confirmed_date": cycle.get("confirmed_date"),
                "stage1": cycle.get("stage1_date"), "stage2": cycle.get("stage2_date"),
                "stage3": cycle.get("stage3_date"), "stage4": cycle.get("stage4_date"),
                "accumulation_date": accumulation, "new_bull_date": new_bull,
                "bull_date": bull, "end_date": end, "duration_days": duration,
                "status": status, "cycle_closed": closed, "warning": warning,
                "warning_reason": reason, "cash_reset_audit": cycle.get("cash_reset_audit", "NOT_RECORDED"),
                "cash_reset_reason": cycle.get("cash_reset_reason", ""),
                "tactical_bear_cash_ratio_at_close": cycle.get("tactical_bear_cash_ratio_at_close", np.nan),
            })
    return pd.DataFrame(rows)


def cycle_reset_integrity(result_e: V31BacktestResult, cycle_audit: pd.DataFrame) -> dict[str, Any]:
    transitions = result_e.transitions.sort_values("signal_date").copy()
    completions = transitions.loc[
        transitions["from_state"].eq("NEW_BULL") & transitions["to_state"].eq("BULL")
    ]
    lifecycle_issues: list[str] = []
    cash_issues: list[str] = []
    completed_ids: list[int] = []
    for _, event in completions.iterrows():
        cycle_id = int(event["cycle_id"])
        completed_ids.append(cycle_id)
        match = cycle_audit.loc[(cycle_audit["model"] == "E") & (cycle_audit["cycle_id"] == cycle_id)]
        if len(match) != 1:
            lifecycle_issues.append(f"cycle_{cycle_id}_missing_or_duplicate")
            continue
        row = match.iloc[0]
        if str(row["status"]) != "COMPLETED_NEW_BULL" or not bool(row["cycle_closed"]):
            lifecycle_issues.append(f"cycle_{cycle_id}_not_closed")
        if str(row.get("cash_reset_audit", "FAIL")) != "PASS":
            cash_issues.append(f"cycle_{cycle_id}_cash_reset_fail")
        if pd.Timestamp(row["end_date"]) != pd.Timestamp(event["signal_date"]):
            lifecycle_issues.append(f"cycle_{cycle_id}_end_date_mismatch")
        post = result_e.history.loc[
            pd.to_datetime(result_e.history["timestamp"], utc=True)
            >= pd.Timestamp(event["execution_4h_open"])
        ]
        if post.empty or int(post.iloc[0]["cycle_id"]) != 0 or int(post.iloc[0]["sell_stage"]) != 0:
            lifecycle_issues.append(f"cycle_{cycle_id}_active_reference_not_reset")
        later_distribution = transitions.loc[
            (pd.to_datetime(transitions["signal_date"], utc=True) > pd.Timestamp(event["signal_date"]))
            & transitions["to_state"].eq("DISTRIBUTION")
        ]
        if not later_distribution.empty and int(later_distribution.iloc[0]["cycle_id"]) <= cycle_id:
            lifecycle_issues.append(f"cycle_{cycle_id}_next_id_not_new")
    if len(completed_ids) != len(set(completed_ids)):
        lifecycle_issues.append("duplicate_completed_cycle_id")
    lifecycle_pass = len(lifecycle_issues) == 0
    cash_reset_pass = len(cash_issues) == 0
    return {
        "pass": lifecycle_pass and cash_reset_pass,
        "cycle_lifecycle_reset_pass": lifecycle_pass,
        "cash_reset_pass": cash_reset_pass,
        "new_bull_to_bull_completion_count": len(completions),
        "completed_cycle_ids": completed_ids,
        "lifecycle_issues": lifecycle_issues,
        "cash_issues": cash_issues,
    }


def cash_persistence_audit(
    results: list[V31BacktestResult],
    daily_by_model: dict[str, pd.DataFrame],
    horizons: list[int],
) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "E"}:
            continue
        daily = daily_by_model[result.scenario.model]
        events = result.transitions.loc[result.transitions["to_state"].eq("NEW_BULL")]
        for _, event in events.iterrows():
            event_date = pd.Timestamp(event["signal_date"])
            for days in horizons:
                target_date = event_date + pd.Timedelta(days=days)
                sample = daily.loc[daily["date"] >= target_date]
                row = sample.iloc[0] if not sample.empty else None
                rows.append({
                    "model": result.scenario.model, "cycle_id": int(event["cycle_id"]),
                    "new_bull_date": event_date, "days_after_new_bull": days,
                    "observation_date": row["date"] if row is not None else pd.NaT,
                    "tactical_bear_cash_ratio": float(row["tactical_bear_cash_ratio"]) if row is not None else np.nan,
                    "tactical_cash_ratio": float(row["tactical_cash_ratio"]) if row is not None else np.nan,
                    "crypto_exposure": float(row["crypto_exposure"]) if row is not None else np.nan,
                    "state": row["macro_state"] if row is not None else "DATA_UNAVAILABLE",
                })
    return pd.DataFrame(rows)


def bull_reentry_audit(
    results: list[V31BacktestResult], daily_by_model: dict[str, pd.DataFrame]
) -> pd.DataFrame:
    rows = []
    start_2023 = pd.Timestamp("2023-01-01", tz="UTC")
    for result in results:
        if result.scenario.model not in {"B", "E"}:
            continue
        events = result.transitions.loc[
            result.transitions["to_state"].eq("NEW_BULL")
            & (pd.to_datetime(result.transitions["signal_date"], utc=True) >= start_2023)
        ].sort_values("signal_date")
        if events.empty:
            rows.append({"model": result.scenario.model, "cycle_id": np.nan, "new_bull_date": pd.NaT})
            continue
        event = events.iloc[0]
        date = pd.Timestamp(event["signal_date"])
        cycle_id = int(event["cycle_id"])
        next_distribution = result.transitions.loc[
            (pd.to_datetime(result.transitions["signal_date"], utc=True) > date)
            & result.transitions["to_state"].eq("DISTRIBUTION")
        ].sort_values("signal_date")
        segment = daily_by_model[result.scenario.model].loc[
            daily_by_model[result.scenario.model]["date"] >= date
        ].copy()
        if not next_distribution.empty:
            segment = segment.loc[segment["date"] < pd.Timestamp(next_distribution.iloc[0]["signal_date"])]
        values: dict[str, Any] = {"model": result.scenario.model, "cycle_id": cycle_id, "new_bull_date": date}
        for threshold in (0.60, 0.85, 0.90, 0.95):
            hit = segment.loc[segment["crypto_exposure"] >= threshold - 1e-10]
            hit_date = pd.Timestamp(hit.iloc[0]["date"]) if not hit.empty else pd.NaT
            tag = int(threshold * 100)
            values[f"first_{tag}_date"] = hit_date
            values[f"days_new_bull_to_{tag}"] = (
                (hit_date - date).total_seconds() / 86400.0 if pd.notna(hit_date) else np.nan
            )
        rows.append(values)
    return pd.DataFrame(rows)


def event_window_audit(
    daily_by_model: dict[str, pd.DataFrame],
    results: list[V31BacktestResult],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows = []
    result_map = {result.scenario.model: result for result in results}
    for event, bounds in windows.items():
        start = pd.Timestamp(bounds[0], tz="UTC")
        end = pd.Timestamp(bounds[1], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        for model in ("B", "E"):
            daily = daily_by_model[model]
            segment = daily.loc[daily["date"].between(start, end)].copy()
            if segment.empty:
                continue
            local_dd = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            trades = result_map[model].trades
            tactical = trades.loc[
                trades["action"].str.startswith("TACTICAL", na=False)
                & pd.to_datetime(trades["signal_date"], utc=True).between(start, end)
            ]
            stage_dates = result_map[model].transitions.loc[
                pd.to_datetime(result_map[model].transitions["signal_date"], utc=True).between(start, end)
            ]
            rows.append({
                "event": event, "model": model, "start": start, "end": end,
                "peak_to_trough_dd": float(local_dd.min()),
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "average_crypto_exposure": float(segment["crypto_exposure"].mean()),
                "maximum_tactical_cash_ratio": float(segment["tactical_cash_ratio"].max()),
                "ending_tactical_cash_ratio": float(segment.iloc[-1]["tactical_cash_ratio"]),
                "tactical_trade_notional": float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0,
                "transition_dates": "|".join(
                    f"{pd.Timestamp(row.signal_date).date()}:{row.from_state}->{row.to_state}"
                    for row in stage_dates.itertuples()
                ),
            })
    return pd.DataFrame(rows)


def may_2021_daily_audit(daily_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    start = pd.Timestamp("2021-05-01", tz="UTC")
    end = pd.Timestamp("2021-07-31", tz="UTC")
    b = daily_by_model["B"].loc[daily_by_model["B"]["date"].between(start, end)].copy()
    e = daily_by_model["E"].loc[daily_by_model["E"]["date"].between(start, end)].copy()
    columns = ["date", "BTC_close", "macro_state", "active_target", "crypto_exposure", "sell_stage", "cycle_id", "tactical_cash_ratio"]
    return b[columns].merge(e[columns], on="date", suffixes=("_B", "_E"), validate="one_to_one")


def comparison_and_promotion(
    summary: pd.DataFrame,
    churn: pd.DataFrame,
    events: pd.DataFrame,
    reentry: pd.DataFrame,
    accumulation_stats: pd.DataFrame,
    rules: dict[str, Any],
    *,
    replay_pass: bool,
    fixed_dca_pass: bool,
    no_lookahead_pass: bool,
    execution_pass: bool,
    fsm_pass: bool,
    cycle_reset_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    index = summary.set_index("model")
    b, e = index.loc["B"], index.loc["E"]
    counts = churn.loc[churn["record_type"].eq("transition_count")].groupby("model")["count"].sum()
    b_churn, e_churn = int(counts.get("B", 0)), int(counts.get("E", 0))
    churn_reduction = 1.0 - e_churn / b_churn if b_churn > 0 else np.nan
    bear = events.loc[events["event"].eq("2021_NOV_TO_2022_JUN")].set_index("model")
    bear_regression_pp = 100.0 * (float(bear.loc["B", "peak_to_trough_dd"]) - float(bear.loc["E", "peak_to_trough_dd"]))
    reentry_index = reentry.set_index("model")
    if pd.notna(reentry_index.loc["B", "new_bull_date"]) and pd.notna(reentry_index.loc["E", "new_bull_date"]):
        reentry_delay = (
            pd.Timestamp(reentry_index.loc["E", "new_bull_date"])
            - pd.Timestamp(reentry_index.loc["B", "new_bull_date"])
        ).total_seconds() / 86400.0
    else:
        reentry_delay = float("inf")
    comparison = pd.DataFrame([{
        "comparison": "E V3.3 vs B V3.1",
        "delta_final_value": float(e["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": float(100 * (e["twr_cagr"] - b["twr_cagr"])),
        "delta_max_drawdown_percentage_points": float(100 * (e["maximum_drawdown"] - b["maximum_drawdown"])),
        "delta_calmar": float(e["calmar"] - b["calmar"]),
        "delta_material_tactical_cash_time_percentage_points": float(100 * (e["material_tactical_cash_time"] - b["material_tactical_cash_time"])),
        "delta_turnover": float(e["tactical_turnover"] - b["tactical_turnover"]),
        "delta_state_churn_count": e_churn - b_churn,
        "state_churn_reduction_fraction": churn_reduction,
        "delta_2021nov_2022jun_dd_percentage_points": float(100 * (bear.loc["E", "peak_to_trough_dd"] - bear.loc["B", "peak_to_trough_dd"])),
        "2023_new_bull_delay_calendar_days": reentry_delay,
        "delta_2023_exposure_60_date_days": _date_delta(reentry_index, "first_60_date"),
        "delta_2023_exposure_85_date_days": _date_delta(reentry_index, "first_85_date"),
        "delta_2023_exposure_90_date_days": _date_delta(reentry_index, "first_90_date"),
        "delta_2023_exposure_95_date_days": _date_delta(reentry_index, "first_95_date"),
        "maximum_accumulation_exposure_E": float(accumulation_stats.iloc[0]["maximum_accumulation_exposure"]),
    }])
    gates = rules["promotion_gates"]
    checks = {
        "maximum_drawdown_gte_minus_0_30": bool(e["maximum_drawdown"] >= float(gates["maximum_drawdown_minimum"])),
        "twr_cagr_gte_0_45": bool(e["twr_cagr"] >= float(gates["twr_cagr_minimum"])),
        "calmar_gte_1_50": bool(e["calmar"] >= float(gates["calmar_minimum"])),
        "final_value_gte_95pct_of_v31_b": bool(e["final_portfolio_value"] >= float(gates["final_value_minimum_fraction_of_v31_b"]) * b["final_portfolio_value"]),
        "material_tactical_cash_time_strictly_below_v31_b": bool(e["material_tactical_cash_time"] < b["material_tactical_cash_time"]),
        "tactical_turnover_lte_9_3677": bool(e["tactical_turnover"] <= float(gates["tactical_turnover_maximum"])),
        "bear_deep_bear_churn_reduced_at_least_50pct": bool(pd.notna(churn_reduction) and churn_reduction >= float(gates["bear_deep_bear_churn_minimum_reduction_fraction"])),
        "no_lookahead_pass": bool(no_lookahead_pass),
        "execution_integrity_pass": bool(execution_pass and replay_pass and fixed_dca_pass),
        "fsm_audit_pass": bool(fsm_pass),
        "cycle_reset_audit_pass": bool(cycle_reset_pass),
    }
    guardrails = rules["diagnostic_guardrails"]
    regression = {
        "bear_protection_regression_pass": bool(bear_regression_pp <= float(guardrails["bear_protection_maximum_regression_percentage_points"])),
        "bull_reentry_regression_pass": bool(reentry_delay <= float(guardrails["bull_reentry_maximum_delay_calendar_days"])),
        "bear_protection_regression_pp": bear_regression_pp,
        "bull_reentry_delay_calendar_days": reentry_delay,
    }
    hard_integrity = all([
        replay_pass, fixed_dca_pass, no_lookahead_pass, execution_pass, fsm_pass, cycle_reset_pass,
    ])
    promoted = all(checks.values()) and regression["bear_protection_regression_pass"] and regression["bull_reentry_regression_pass"]
    verdict = (
        "A. V3.3 PROMOTED TO FORWARD PAPER TEST" if promoted else
        "B. V3.1 REMAINS CHAMPION" if hard_integrity else
        "C. V3.3 NEEDS REDESIGN"
    )
    return comparison, {
        "promotion_gate": "PASS" if promoted else "FAIL",
        "checks": checks,
        "diagnostic_regression_guardrails": regression,
        "final_verdict": verdict,
    }


def _date_delta(index: pd.DataFrame, column: str) -> float:
    left, right = index.loc["E", column], index.loc["B", column]
    if pd.isna(left) or pd.isna(right):
        return np.nan
    return (pd.Timestamp(left) - pd.Timestamp(right)).total_seconds() / 86400.0


def build_no_lookahead_audit(
    frame: pd.DataFrame,
    daily_features: pd.DataFrame,
    results: list[V31BacktestResult],
    data_contract: dict[str, Any],
    fixed_dca: pd.DataFrame,
    fsm: pd.DataFrame,
    replay: dict[str, Any],
    cycle_reset: dict[str, Any],
    prefix_checks: dict[str, bool],
    engine_source: str,
    indicator_source: str,
) -> dict[str, Any]:
    result_e = next(result for result in results if result.scenario.model == "E")
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    timing_violations = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    sell_floor = tactical.loc[tactical["side"].eq("SELL"), "after_crypto_exposure"]
    h0 = next(result for result in results if result.scenario.model == "H0")
    exits = result_e.transitions.loc[
        result_e.transitions["from_state"].eq("DEEP_BEAR")
        & result_e.transitions["to_state"].eq("BEAR")
    ].copy()
    signal_index = result_e.signals.set_index(pd.to_datetime(result_e.signals["signal_date"], utc=True))
    hysteresis_violations = 0
    for _, event in exits.iterrows():
        date = pd.Timestamp(event["signal_date"])
        sample = signal_index.loc[date]
        if isinstance(sample, pd.DataFrame):
            sample = sample.iloc[0]
        if int(sample["deep_bear_dwell_days"]) < 10 or not bool(sample["deep_bear_exit_v33_confirmed"]):
            hysteresis_violations += 1
    drift_signals = result_e.signals.loc[result_e.signals["accumulation_drift_sell_triggered"].astype(bool)]
    drift_trigger_violations = int((drift_signals["accumulation_observed_state"] != "ACCUMULATION").sum())
    drift_trigger_violations += int((drift_signals["accumulation_days_above_upper"] < 3).sum())
    drift_trigger_violations += int(drift_signals["accumulation_lock_active"].astype(bool).sum())
    drift_trigger_violations += int(drift_signals["accumulation_drift_cooldown_active"].astype(bool).sum())
    promotion_terms = ("promotion_gates", "maximum_drawdown_minimum", "twr_cagr_minimum", "calmar_minimum")
    forbidden_v32 = ("v32_engine", "v32_indicators", "BULL_RECOVERY_GATE", "right_60_v32", "recovery_mode")
    future_tokens = ("shift(-", "future_min_return", "bear_label", "label_end_date")
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "completed_daily_candle_violations": int(data_contract["completed_daily_candle_violations"]),
        "signal_availability_violations": int(data_contract["signal_availability_violations"]),
        "future_columns_in_execution_frame": data_contract["future_columns_in_execution_frame"],
        "tactical_execution_before_next_bar_violations": timing_violations,
        "fixed_dca_row_integrity_pass": bool(fixed_dca["all_match"].all()),
        "v3_1_replay_integrity_pass": bool(replay["pass"]),
        "illegal_fsm_transition_count": int((~fsm["legal_transition"].astype(bool)).sum()) if not fsm.empty else 0,
        "tactical_sell_floor_violations": int((sell_floor < 0.20 - 1e-9).sum()),
        "hysteresis_exit_rule_violations": hysteresis_violations,
        "accumulation_drift_trigger_rule_violations": drift_trigger_violations,
        "cycle_reset_integrity_pass": bool(cycle_reset["pass"]),
        "h0_external_contributions_zero": bool(abs(float(h0.history["external_flow"].sum())) <= 1e-12),
        "h0_post_initial_trade_count_zero": bool(len(h0.trades.loc[~h0.trades["action"].eq("INITIAL_ALLOCATION")]) == 0),
        "promotion_gate_terms_absent_from_trading_engine": bool(not any(term in engine_source for term in promotion_terms)),
        "v32_trading_logic_absent_from_v33_engine": bool(not any(term in engine_source for term in forbidden_v32)),
        "future_reference_tokens_absent_from_v33_indicator_source": bool(not any(term in indicator_source for term in future_tokens)),
        "prefix_invariance": prefix_checks,
    }
    audit["no_lookahead_pass"] = bool(
        audit["data_contract_pass"]
        and audit["completed_daily_candle_violations"] == 0
        and audit["signal_availability_violations"] == 0
        and not audit["future_columns_in_execution_frame"]
        and audit["tactical_execution_before_next_bar_violations"] == 0
        and audit["future_reference_tokens_absent_from_v33_indicator_source"]
        and all(prefix_checks.values())
    )
    audit["execution_integrity_pass"] = bool(
        audit["fixed_dca_row_integrity_pass"] and audit["v3_1_replay_integrity_pass"]
        and audit["illegal_fsm_transition_count"] == 0
        and audit["tactical_sell_floor_violations"] == 0
        and audit["hysteresis_exit_rule_violations"] == 0
        and audit["accumulation_drift_trigger_rule_violations"] == 0
        and audit["h0_external_contributions_zero"] and audit["h0_post_initial_trade_count_zero"]
        and audit["promotion_gate_terms_absent_from_trading_engine"]
        and audit["v32_trading_logic_absent_from_v33_engine"]
        and all(prefix_checks.values())
    )
    audit["combined_hard_integrity_pass"] = bool(
        audit["no_lookahead_pass"]
        and audit["execution_integrity_pass"]
        and audit["cycle_reset_integrity_pass"]
    )
    audit["pass"] = audit["no_lookahead_pass"]
    return audit


__all__ = [
    "daily_history_v33", "summary_v33", "v31_replay_integrity", "fixed_dca_integrity",
    "fsm_audit", "churn_audit", "accumulation_exposure_audit", "cycle_duration_audit",
    "cycle_reset_integrity", "cash_persistence_audit", "bull_reentry_audit",
    "event_window_audit", "may_2021_daily_audit", "comparison_and_promotion",
    "build_no_lookahead_audit", "prefix_trade_identity", "_drawdown_detail",
]
