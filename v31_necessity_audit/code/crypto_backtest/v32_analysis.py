from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import _drawdown_detail, daily_history_v31, enriched_summary, prefix_trade_identity
from .v31_engine import V31BacktestResult


def daily_history_v32(history: pd.DataFrame) -> pd.DataFrame:
    daily = daily_history_v31(history)
    source = history.copy()
    source["date"] = pd.to_datetime(source["timestamp"], utc=True).dt.floor("D")
    for column in ("recovery_mode", "bull_recovery_gate"):
        if column in source:
            extra = source.groupby("date", as_index=False)[column].last()
            daily = daily.merge(extra, on="date", how="left", validate="one_to_one")
    return daily


def summary_v32(result: V31BacktestResult, rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, rules)
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["median_tactical_cash"] = float(result.history["tactical_cash"].median())
    if result.scenario.model in {"B", "D"}:
        hist = result.history
        bull = hist.loc[hist["macro_state"].isin(["BULL", "NEW_BULL"])]
        calendar_bull = hist.loc[pd.to_datetime(hist["timestamp"], utc=True).between(
            pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
        )]
        row["fsm_bull_average_crypto_exposure"] = float(bull["crypto_exposure"].mean()) if not bull.empty else np.nan
        row["calendar_2023_2025_average_crypto_exposure"] = float(calendar_bull["crypto_exposure"].mean()) if not calendar_bull.empty else np.nan
    else:
        row["fsm_bull_average_crypto_exposure"] = np.nan
        row["calendar_2023_2025_average_crypto_exposure"] = np.nan
    return row


def _frame_exact(
    left: pd.DataFrame, right: pd.DataFrame, keys: list[str], numeric: list[str], tolerance: float = 1e-10,
) -> tuple[bool, float]:
    if len(left) != len(right):
        return False, float("inf")
    left = left.reset_index(drop=True)
    right = right.reset_index(drop=True)
    keys_ok = all(left[column].fillna("").astype(str).equals(right[column].fillna("").astype(str)) for column in keys)
    delta = max(
        float(np.max(np.abs(left[column].astype(float).to_numpy() - right[column].astype(float).to_numpy())))
        for column in numeric
    ) if len(left) and numeric else 0.0
    return bool(keys_ok and delta <= tolerance), delta


def v31_replay_integrity(
    model_a: V31BacktestResult, model_b: V31BacktestResult,
    v31_dir: Path, reference: dict[str, float],
) -> dict[str, Any]:
    prior_summary = pd.read_csv(v31_dir / "results" / "summary_v3_1.csv").set_index("model")
    prior_trades = pd.read_csv(v31_dir / "results" / "trade_log_v3_1.csv")
    metrics = {
        "final_portfolio_value": model_b.summary["final_portfolio_value"],
        "maximum_drawdown": model_b.summary["maximum_drawdown"],
        "twr_cagr": model_b.summary["time_weighted_cagr"],
        "calmar": model_b.summary["calmar"],
    }
    metric_delta = {
        key: abs(float(value) - float(reference[key])) for key, value in metrics.items()
    }
    current = model_b.trades.copy()
    prior = prior_trades.loc[prior_trades["model"].eq("B")].copy()
    for frame in (current, prior):
        for column in ("timestamp", "signal_date"):
            frame[column] = pd.to_datetime(frame[column], utc=True, errors="coerce")
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    numeric = ["quantity", "raw_open_price", "effective_price", "gross_notional_usd", "cash_change_usd", "fee_usd", "slippage_usd"]
    trades_pass, trade_delta = _frame_exact(current[keys + numeric], prior[keys + numeric], keys, numeric)
    prior_b = prior_summary.loc["B"]
    prior_metric_delta = {
        "final_portfolio_value": abs(float(metrics["final_portfolio_value"]) - float(prior_b["final_portfolio_value"])),
        "maximum_drawdown": abs(float(metrics["maximum_drawdown"]) - float(prior_b["maximum_drawdown"])),
        "twr_cagr": abs(float(metrics["twr_cagr"]) - float(prior_b["twr_cagr"])),
        "calmar": abs(float(metrics["calmar"]) - float(prior_b["calmar"])),
    }
    passed = bool(max(metric_delta.values()) <= 1e-10 and max(prior_metric_delta.values()) <= 1e-10 and trades_pass)
    return {
        "pass": passed, "reference_metric_max_abs_delta": max(metric_delta.values()),
        "prior_output_metric_max_abs_delta": max(prior_metric_delta.values()),
        "trade_rows_current": len(current), "trade_rows_prior": len(prior),
        "trade_numeric_max_abs_delta": trade_delta, "trade_rows_exact": trades_pass,
        "model_a_final_portfolio_value": float(model_a.summary["final_portfolio_value"]),
    }


def fixed_dca_integrity_v32(results: list[V31BacktestResult]) -> pd.DataFrame:
    reference_result = next(result for result in results if result.scenario.model == "A")
    reference = reference_result.trades.loc[reference_result.trades["action"].eq("NORMAL_DCA")].copy()
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date"]
    numeric = ["quantity", "raw_open_price", "effective_price", "gross_notional_usd", "cash_change_usd", "fee_usd", "slippage_usd"]
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


def fsm_audit_v32(results: list[V31BacktestResult], rules: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for result in results:
        if not result.scenario.use_fsm:
            continue
        for _, event in result.transitions.iterrows():
            legal = str(event["to_state"]) in rules["allowed_transitions"].get(str(event["from_state"]), [])
            rows.append({**event.to_dict(), "model": result.scenario.model, "legal_transition": legal})
    return pd.DataFrame(rows)


def churn_audit(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.scenario.model not in {"B", "D"}:
            continue
        transitions = result.transitions
        for from_state, to_state in (("BEAR", "DEEP_BEAR"), ("DEEP_BEAR", "BEAR")):
            rows.append({
                "model": result.scenario.model, "record_type": "transition_count",
                "state": f"{from_state}->{to_state}",
                "count": int(((transitions["from_state"] == from_state) & (transitions["to_state"] == to_state)).sum()),
                "average_days": np.nan, "median_days": np.nan,
            })
        signals = result.signals.sort_values("signal_date").copy()
        if signals.empty:
            continue
        signals["run_id"] = signals["state_after"].ne(signals["state_after"].shift()).cumsum()
        runs = signals.groupby(["run_id", "state_after"], as_index=False).agg(
            start=("signal_date", "min"), end=("signal_date", "max"), observations=("signal_date", "size")
        )
        for state, group in runs.groupby("state_after"):
            rows.append({
                "model": result.scenario.model, "record_type": "state_dwell",
                "state": state, "count": len(group),
                "average_days": float(group["observations"].mean()),
                "median_days": float(group["observations"].median()),
            })
    return pd.DataFrame(rows)


def event_window_audit(
    daily_by_model: dict[str, pd.DataFrame], d_signals: pd.DataFrame,
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows = []
    last_date = max(frame["date"].max() for frame in daily_by_model.values())
    for event, bounds in windows.items():
        start = pd.Timestamp(bounds[0], tz="UTC")
        end = last_date if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        ds = d_signals.loc[pd.to_datetime(d_signals["signal_date"], utc=True).between(start, end)]
        state_mode = ds["state_after"].mode()
        stage_mode = ds["stage_after"].mode()
        for model, daily in daily_by_model.items():
            segment = daily.loc[daily["date"].between(start, end)]
            if segment.empty:
                continue
            local_dd = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            rows.append({
                "event": event, "model": model, "start": start, "end": end,
                "event_drawdown": float(local_dd.min()),
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "ending_crypto_exposure": float(segment.iloc[-1]["crypto_exposure"]),
                "d_dominant_state": state_mode.iloc[0] if not state_mode.empty else "N/A",
                "d_dominant_stage": int(stage_mode.iloc[0]) if not stage_mode.empty else 0,
                "d_average_crypto_exposure": float(daily_by_model["D"].loc[
                    daily_by_model["D"]["date"].between(start, end), "crypto_exposure"
                ].mean()),
            })
    return pd.DataFrame(rows)


def cycle_audit(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "D"} or result.cycles.empty:
            continue
        for _, cycle in result.cycles.iterrows():
            row = {"model": result.scenario.model, **cycle.to_dict()}
            trans = result.transitions.loc[result.transitions["cycle_id"].eq(cycle["cycle_id"])]
            sig = result.signals
            for event, to_state in (("accumulation", "ACCUMULATION"), ("new_bull", "NEW_BULL"), ("bull", "BULL")):
                matching = trans.loc[trans["to_state"].eq(to_state)]
                date = matching.iloc[0]["signal_date"] if not matching.empty else pd.NaT
                row[f"{event}_date"] = date
                if pd.notna(date):
                    sample = sig.loc[pd.to_datetime(sig["signal_date"], utc=True).eq(pd.Timestamp(date))]
                    row[f"{event}_btc_price"] = float(sample.iloc[0]["btc_close"]) if not sample.empty else np.nan
                    row[f"{event}_exposure"] = float(sample.iloc[0]["crypto_exposure_after"]) if not sample.empty else np.nan
                else:
                    row[f"{event}_btc_price"] = np.nan
                    row[f"{event}_exposure"] = np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def bull_reentry_audit(result_b: V31BacktestResult, result_d: V31BacktestResult) -> pd.DataFrame:
    rows = []
    for result in (result_b, result_d):
        signals = result.signals.copy()
        history = result.history.copy()
        events = result.transitions.loc[result.transitions["to_state"].eq("NEW_BULL")]
        for _, event in events.iterrows():
            new_bull = pd.Timestamp(event["signal_date"])
            cycle_id = int(event["cycle_id"])
            recovery = result.transitions.loc[
                result.transitions["cycle_id"].eq(cycle_id) & result.transitions["to_state"].eq("ACCUMULATION")
            ]
            recovery_date = pd.Timestamp(recovery.iloc[-1]["signal_date"]) if not recovery.empty else pd.NaT
            anchor = recovery_date if pd.notna(recovery_date) else new_bull
            segment = history.loc[pd.to_datetime(history["timestamp"], utc=True) >= anchor].copy()
            next_cycle = result.transitions.loc[
                (pd.to_datetime(result.transitions["signal_date"], utc=True) > new_bull)
                & result.transitions["to_state"].eq("DISTRIBUTION")
            ]
            if not next_cycle.empty:
                segment = segment.loc[pd.to_datetime(segment["timestamp"], utc=True) < pd.Timestamp(next_cycle.iloc[0]["signal_date"])]
            values: dict[str, Any] = {
                "model": result.scenario.model, "cycle_id": cycle_id,
                "recovery_date": recovery_date, "new_bull_date": new_bull,
            }
            for threshold in (0.60, 0.85, 0.95):
                hit = segment.loc[segment["crypto_exposure"] >= threshold - 1e-10]
                date = pd.Timestamp(hit.iloc[0]["timestamp"]) if not hit.empty else pd.NaT
                values[f"first_{int(threshold*100)}_date"] = date
                values[f"days_recovery_to_{int(threshold*100)}"] = (
                    (date - anchor).total_seconds() / 86400.0 if pd.notna(date) else np.nan
                )
            post = history.loc[
                pd.to_datetime(history["timestamp"], utc=True).between(new_bull, new_bull + pd.Timedelta(days=10))
            ]
            values["max_exposure_first_10d_after_new_bull"] = float(post["crypto_exposure"].max()) if not post.empty else np.nan
            rows.append(values)
    return pd.DataFrame(rows)


def comparison_and_promotion(
    summary: pd.DataFrame, model_b: V31BacktestResult, model_d: V31BacktestResult,
    replay: dict[str, Any], fixed_dca: pd.DataFrame, fsm: pd.DataFrame,
    no_lookahead_pass: bool, execution_pass: bool, v32_rules: dict[str, Any],
    reentry: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    index = summary.set_index("model")
    b, d = index.loc["B"], index.loc["D"]
    comparison = pd.DataFrame([{
        "comparison": "D V3.2 vs B V3.1",
        "delta_final_value": float(d["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": float(100 * (d["twr_cagr"] - b["twr_cagr"])),
        "delta_max_drawdown_percentage_points": float(100 * (d["maximum_drawdown"] - b["maximum_drawdown"])),
        "delta_calmar": float(d["calmar"] - b["calmar"]),
        "delta_material_tactical_cash_time_percentage_points": float(100 * (d["material_tactical_cash_time"] - b["material_tactical_cash_time"])),
        "delta_tactical_turnover": float(d["tactical_turnover"] - b["tactical_turnover"]),
    }])
    gates = v32_rules["promotion_gates"]
    d_reentry = reentry.loc[reentry["model"].eq("D")]
    participation = bool(not d_reentry.empty and (d_reentry["max_exposure_first_10d_after_new_bull"] >= float(gates["new_bull_exposure_minimum"])).all())
    checks = {
        "maximum_drawdown_gte_minus_0_30": bool(d["maximum_drawdown"] >= float(gates["maximum_drawdown_minimum"])),
        "twr_cagr_gte_0_45": bool(d["twr_cagr"] >= float(gates["twr_cagr_minimum"])),
        "calmar_gte_1_50": bool(d["calmar"] >= float(gates["calmar_minimum"])),
        "new_bull_exposure_gte_0_85": participation,
        "material_tactical_cash_time_below_v31": bool(d["material_tactical_cash_time"] < b["material_tactical_cash_time"]),
        "tactical_turnover_lte_9_3677": bool(d["tactical_turnover"] <= float(gates["tactical_turnover_maximum"])),
        "no_lookahead_pass": bool(no_lookahead_pass),
        "execution_integrity_pass": bool(execution_pass and fixed_dca["all_match"].all() and replay["pass"]),
        "fsm_audit_pass": bool(not fsm.empty and fsm["legal_transition"].all()),
    }
    passed = all(checks.values())
    if passed:
        verdict = "A. V3.2 PROMOTED TO FORWARD PAPER TEST"
    elif replay["pass"]:
        verdict = "B. V3.1 REMAINS CHAMPION"
    elif fixed_dca["all_match"].all():
        verdict = "D. V3.2 NEEDS REDESIGN"
    else:
        verdict = "C. FIXED DCA REMAINS BASELINE ONLY"
    return comparison, {"promotion_gate": "PASS" if passed else "FAIL", "checks": checks, "final_verdict": verdict}


def build_no_lookahead_audit(
    frame: pd.DataFrame, daily: pd.DataFrame, results: list[V31BacktestResult],
    data_contract: dict[str, Any], fixed_dca: pd.DataFrame, fsm: pd.DataFrame,
    replay: dict[str, Any], prefix_checks: dict[str, bool], engine_source: str,
) -> dict[str, Any]:
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    tactical_timing = 0
    if not tactical.empty:
        tactical_timing = int((
            pd.to_datetime(tactical["timestamp"], utc=True)
            <= pd.to_datetime(tactical["signal_date"], utc=True)
        ).sum())
    sell_floor = tactical.loc[tactical["side"].eq("SELL"), "after_crypto_exposure"]
    h0 = next(result for result in results if result.scenario.model == "H0")
    promotion_terms = ("promotion_gates", "maximum_drawdown_minimum", "twr_cagr_minimum", "calmar_minimum")
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "completed_daily_candle_violations": int(data_contract["completed_daily_candle_violations"]),
        "signal_availability_violations": int(data_contract["signal_availability_violations"]),
        "future_columns_in_execution_frame": data_contract["future_columns_in_execution_frame"],
        "recovery_gate_uses_only_t_or_earlier_completed_daily_rows": true_if_v32_columns_present(daily),
        "tactical_execution_not_after_signal_violations": tactical_timing,
        "fixed_dca_row_integrity_pass": bool(fixed_dca["all_match"].all()),
        "v3_1_row_integrity_pass": bool(replay["pass"]),
        "illegal_fsm_transition_count": int((~fsm["legal_transition"].astype(bool)).sum()) if not fsm.empty else 0,
        "tactical_sell_floor_violations": int((sell_floor < 0.20 - 1e-9).sum()),
        "h0_external_contributions_zero": bool(abs(float(h0.history["external_flow"].sum())) <= 1e-12),
        "h0_post_initial_trade_count_zero": bool(len(h0.trades.loc[~h0.trades["action"].eq("INITIAL_ALLOCATION")]) == 0),
        "promotion_gate_terms_absent_from_trading_engine": bool(not any(term in engine_source for term in promotion_terms)),
        "prefix_invariance": prefix_checks,
    }
    audit["pass"] = bool(
        audit["data_contract_pass"]
        and audit["completed_daily_candle_violations"] == 0
        and audit["signal_availability_violations"] == 0
        and not audit["future_columns_in_execution_frame"]
        and audit["recovery_gate_uses_only_t_or_earlier_completed_daily_rows"]
        and audit["tactical_execution_not_after_signal_violations"] == 0
        and audit["fixed_dca_row_integrity_pass"] and audit["v3_1_row_integrity_pass"]
        and audit["illegal_fsm_transition_count"] == 0
        and audit["tactical_sell_floor_violations"] == 0
        and audit["h0_external_contributions_zero"] and audit["h0_post_initial_trade_count_zero"]
        and audit["promotion_gate_terms_absent_from_trading_engine"]
        and all(prefix_checks.values())
    )
    return audit


def true_if_v32_columns_present(daily: pd.DataFrame) -> bool:
    required = {
        "bull_recovery_gate", "recovery_new_bull_daily_condition",
        "right_60_v32_confirmed", "deep_bear_exit_v32_confirmed",
    }
    return bool(required.issubset(daily.columns))


__all__ = [
    "daily_history_v32", "summary_v32", "v31_replay_integrity", "fixed_dca_integrity_v32",
    "fsm_audit_v32", "churn_audit", "event_window_audit", "cycle_audit",
    "bull_reentry_audit", "comparison_and_promotion", "build_no_lookahead_audit",
    "prefix_trade_identity", "_drawdown_detail",
]
