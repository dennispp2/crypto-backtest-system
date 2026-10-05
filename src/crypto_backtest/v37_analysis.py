from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import daily_history_v31, enriched_summary
from .v31_engine import V31BacktestResult
from .v37_engine import AHR_ACTION, NEW_BULL_ACTION, RIGHT_ACTIONS


RISK_SELL = "RISK_SELL"


def daily_history_v37(history: pd.DataFrame) -> pd.DataFrame:
    """Collapse 4-hour history to completed UTC days without changing TWR math."""
    daily = daily_history_v31(history)
    source = history.copy()
    source["date"] = pd.to_datetime(source["timestamp"], utc=True).dt.floor("D")
    extras = [
        "actual_crypto_exposure", "macro_state_shadow", "sell_stage_shadow",
        "cycle_id_shadow", "active_target_shadow", "shadow_target_exposure",
        "crash_state_shadow", "new_bull_state_shadow", "desired_action_shadow",
        "desired_signal_type_shadow", "desired_exposure_target_shadow",
        "ahr_rebuy_cooldown_remaining", "pending_ahr_buy",
    ]
    present = [column for column in extras if column in source]
    if present:
        daily = daily.merge(
            source.groupby("date", as_index=False)[present].last(),
            on="date", how="left", validate="one_to_one",
        )
    return daily


def summary_v37(result: V31BacktestResult, base_rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, base_rules)
    tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["tactical_notional_usd"] = float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0
    for name in (
        "requested_ahr_buys", "executed_ahr_buys", "delayed_ahr_buys",
        "cancelled_ahr_buys", "duplicate_ahr_suppressions",
    ):
        row[name] = int(result.counters.get(name, 0))
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
        float(np.max(np.abs(
            left[column].astype(float).to_numpy() - right[column].astype(float).to_numpy()
        )))
        for column in numeric
    ) if len(left) and numeric else 0.0
    return bool(keys_ok and delta <= tolerance), delta


def v31_replay_integrity(
    model_b: V31BacktestResult,
    v31_dir: Path,
    reference: dict[str, float],
) -> dict[str, Any]:
    """Require the untouched current engine to reproduce the frozen V3.1 output."""
    prior_summary = pd.read_csv(v31_dir / "results" / "summary_v3_1.csv").set_index("model")
    prior_trades = pd.read_csv(v31_dir / "results" / "trade_log_v3_1.csv")
    metrics = {
        "final_portfolio_value": float(model_b.summary["final_portfolio_value"]),
        "maximum_drawdown": float(model_b.summary["maximum_drawdown"]),
        "twr_cagr": float(model_b.summary["time_weighted_cagr"]),
        "calmar": float(model_b.summary["calmar"]),
    }
    reference_delta = {key: abs(value - float(reference[key])) for key, value in metrics.items()}
    prior_b = prior_summary.loc["B"]
    prior_delta = {key: abs(value - float(prior_b[key])) for key, value in metrics.items()}
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


def shadow_replay_integrity(model_b: V31BacktestResult, shadow: V31BacktestResult) -> dict[str, Any]:
    """Compare an independently run unmodified V3.1 engine with Model B."""
    history_fields = [
        "timestamp", "macro_state", "sell_stage", "cycle_id", "active_target",
        "crash_level1_active",
    ]
    keys = ["timestamp", "macro_state"]
    numeric = ["sell_stage", "cycle_id", "active_target", "crash_level1_active"]
    history_pass, history_delta = _frame_exact(
        model_b.history[history_fields], shadow.history[history_fields], keys, numeric,
    )
    trade_keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    trade_numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd",
    ]
    trade_pass, trade_delta = _frame_exact(
        model_b.trades[trade_keys + trade_numeric],
        shadow.trades[trade_keys + trade_numeric],
        trade_keys, trade_numeric,
    )
    return {
        "pass": bool(history_pass and trade_pass),
        "history_rows": len(model_b.history), "history_rows_exact": history_pass,
        "history_numeric_max_abs_delta": history_delta,
        "trade_rows": len(model_b.trades), "trade_rows_exact": trade_pass,
        "trade_numeric_max_abs_delta": trade_delta,
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
            "keys_exact": bool(passed if delta <= 1e-10 else False),
            "numeric_max_abs_delta": delta, "all_match": passed,
        })
    return pd.DataFrame(rows)


def fsm_audit(model_b: V31BacktestResult, base_rules: dict[str, Any]) -> pd.DataFrame:
    rows = []
    for event in model_b.transitions.to_dict("records"):
        legal = str(event["to_state"]) in base_rules["allowed_transitions"].get(str(event["from_state"]), [])
        rows.append({"model": "B_AND_J_SHADOW", **event, "legal_transition": legal})
    return pd.DataFrame(rows)


def shadow_state_parity_audit(
    model_b_daily: pd.DataFrame,
    model_j_daily: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    b = model_b_daily[[
        "date", "macro_state", "sell_stage", "cycle_id", "active_target",
        "crash_level1_active",
    ]].copy()
    b["new_bull_state"] = b["macro_state"].eq("NEW_BULL")
    j = model_j_daily[[
        "date", "macro_state_shadow", "sell_stage_shadow", "cycle_id_shadow",
        "active_target_shadow", "crash_state_shadow", "new_bull_state_shadow",
    ]].copy()
    audit = b.merge(j, on="date", how="outer", validate="one_to_one", indicator=True)
    audit = audit.rename(columns={
        "macro_state": "B_macro_state", "macro_state_shadow": "J_shadow_macro_state",
        "sell_stage": "B_stage", "sell_stage_shadow": "J_shadow_stage",
        "cycle_id": "B_cycle_id", "cycle_id_shadow": "J_shadow_cycle_id",
        "active_target": "B_active_target", "active_target_shadow": "J_shadow_active_target",
        "crash_level1_active": "B_crash_state", "crash_state_shadow": "J_shadow_crash_state",
        "new_bull_state": "B_new_bull_state", "new_bull_state_shadow": "J_shadow_new_bull_state",
    })
    present = audit["_merge"].eq("both")
    audit["macro_state_match"] = present & audit["B_macro_state"].eq(audit["J_shadow_macro_state"])
    audit["stage_match"] = present & audit["B_stage"].eq(audit["J_shadow_stage"])
    audit["cycle_match"] = present & audit["B_cycle_id"].eq(audit["J_shadow_cycle_id"])
    audit["target_match"] = present & np.isclose(
        audit["B_active_target"].astype(float), audit["J_shadow_active_target"].astype(float),
        rtol=0.0, atol=1e-12,
    )
    audit["crash_match"] = present & audit["B_crash_state"].astype(bool).eq(audit["J_shadow_crash_state"].astype(bool))
    audit["new_bull_match"] = present & audit["B_new_bull_state"].astype(bool).eq(audit["J_shadow_new_bull_state"].astype(bool))
    columns = {
        "macro_state": "macro_state_match", "stage": "stage_match", "cycle": "cycle_match",
        "target": "target_match", "crash": "crash_match", "new_bull": "new_bull_match",
    }
    summary = {f"{name}_mismatch_days": int((~audit[column]).sum()) for name, column in columns.items()}
    summary["date_alignment_mismatch_days"] = int((~present).sum())
    summary["pass"] = bool(all(value == 0 for key, value in summary.items() if key.endswith("_days")))
    return audit.drop(columns="_merge"), summary


def overlay_scope_audit(overlay: pd.DataFrame, shadow: V31BacktestResult) -> dict[str, Any]:
    restricted = overlay.loc[overlay["restricted_by_overlay"].astype(bool)]
    restricted_non_ahr = restricted.loc[restricted["shadow_signal_type"].ne("AHR_VALUE_BUY")]
    nonexecute = overlay.loc[overlay["overlay_decision"].ne("EXECUTE")]
    risk_suppressed = int(nonexecute["shadow_signal_type"].eq(RISK_SELL).sum())
    right_suppressed = int(nonexecute["shadow_signal_type"].isin({"RIGHT_SIDE_TO_50", "RIGHT_SIDE_TO_60"}).sum())
    new_bull_suppressed = int(nonexecute["shadow_signal_type"].eq("NEW_BULL_REDEPLOY").sum())
    execute_no_fill = overlay.loc[
        overlay["overlay_decision"].eq("EXECUTE")
        & overlay["decision_reason"].astype(str).str.startswith("EXECUTE_NO_FILL")
    ]
    shadow_events = shadow.trades.loc[shadow.trades["action"].str.startswith("TACTICAL", na=False), "tactical_event_id"].nunique()
    original_rows = overlay.loc[overlay["shadow_action"].ne("PENDING_AHR_BUY")]
    represented = original_rows["shadow_event_id"].replace("", np.nan).dropna().nunique()
    return {
        "pass": bool(
            restricted_non_ahr.empty and risk_suppressed == 0 and right_suppressed == 0
            and new_bull_suppressed == 0 and int(represented) == int(shadow_events)
        ),
        "restricted_rows": int(len(restricted)),
        "restricted_non_ahr_rows": int(len(restricted_non_ahr)),
        "risk_sell_suppressed_count": risk_suppressed,
        "right_side_suppressed_count": right_suppressed,
        "new_bull_suppressed_count": new_bull_suppressed,
        "risk_sell_execute_no_fill_at_unchanged_target_count": int(
            execute_no_fill["shadow_signal_type"].eq(RISK_SELL).sum()
        ),
        "other_non_ahr_execute_no_fill_count": int(
            (~execute_no_fill["shadow_signal_type"].isin({RISK_SELL, "AHR_VALUE_BUY"})).sum()
        ),
        "shadow_tactical_event_count": int(shadow_events),
        "shadow_tactical_events_represented": int(represented),
    }


def _actual_tactical_events(result: V31BacktestResult) -> pd.DataFrame:
    trades = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if trades.empty:
        return pd.DataFrame(columns=["model", "timestamp", "action", "side"])
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)
    events = trades.groupby(
        ["tactical_event_id", "timestamp", "action", "side", "reason", "cycle_id"],
        as_index=False, dropna=False,
    ).agg(
        exposure_before=("before_crypto_exposure", "first"),
        exposure_after=("after_crypto_exposure", "last"),
        gross_notional=("gross_notional_usd", "sum"),
        fee=("fee_usd", "sum"), slippage=("slippage_usd", "sum"),
    )
    events.insert(0, "model", result.scenario.model)
    events["signal_type"] = np.where(
        events["action"].eq(AHR_ACTION), "AHR_VALUE_BUY",
        np.where(events["side"].eq("SELL"), RISK_SELL,
                 np.where(events["action"].isin(RIGHT_ACTIONS), "RIGHT_SIDE_BUY", events["action"])),
    )
    events["record_type"] = "ACTUAL_EXECUTED"
    events["overlay_decision"] = "EXECUTE"
    return events


def bottom_whipsaw_audit(
    model_b: V31BacktestResult,
    model_j: V31BacktestResult,
    overlay: pd.DataFrame,
) -> pd.DataFrame:
    actual = pd.concat([_actual_tactical_events(model_b), _actual_tactical_events(model_j)], ignore_index=True, sort=False)
    requests = overlay.copy()
    requests["model"] = "J"
    requests["record_type"] = "SHADOW_REQUEST_OR_PENDING"
    requests["timestamp"] = pd.to_datetime(requests["timestamp"], utc=True)
    requests["action"] = requests["shadow_action"]
    requests["signal_type"] = requests["shadow_signal_type"]
    requests["side"] = np.where(requests["shadow_signal_type"].eq(RISK_SELL), "SELL", "BUY")
    requests["exposure_before"] = requests["actual_exposure_before"]
    requests["exposure_after"] = requests["actual_exposure_after"]
    requests["gross_notional"] = np.nan
    requests["fee"] = np.nan
    requests["slippage"] = np.nan
    keep = [
        "model", "timestamp", "record_type", "action", "signal_type", "side",
        "overlay_decision", "decision_reason", "exposure_before", "exposure_after",
        "gross_notional", "fee", "slippage", "cooldown_remaining", "pending_ahr_buy",
    ]
    for column in keep:
        if column not in actual:
            actual[column] = np.nan
        if column not in requests:
            requests[column] = np.nan
    return pd.concat([actual[keep], requests[keep]], ignore_index=True).sort_values(["timestamp", "model", "record_type"])


def whipsaw_pairs(result: V31BacktestResult) -> pd.DataFrame:
    events = _actual_tactical_events(result).sort_values("timestamp")
    relevant = events.loc[
        events["signal_type"].eq(RISK_SELL) | events["signal_type"].eq("AHR_VALUE_BUY")
    ].copy()
    rows = []
    previous: dict[str, tuple[pd.Timestamp, Any]] = {}
    for event in relevant.itertuples():
        kind = "AHR" if event.signal_type == "AHR_VALUE_BUY" else "SELL"
        opposite = "SELL" if kind == "AHR" else "AHR"
        prior = previous.get(opposite)
        if prior is not None:
            days = (event.timestamp - prior[0]).total_seconds() / 86400.0
            if 0.0 <= days <= 7.0 + 1e-12:
                rows.append({
                    "model": result.scenario.model,
                    "first_event_id": prior[1], "second_event_id": event.tactical_event_id,
                    "first_type": opposite, "second_type": kind,
                    "first_timestamp": prior[0], "second_timestamp": event.timestamp,
                    "elapsed_calendar_days": days,
                })
        previous[kind] = (event.timestamp, event.tactical_event_id)
    return pd.DataFrame(rows)


def _bounds(bounds: list[str], cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(bounds[0], tz="UTC")
    end = cutoff if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
    return start, end


def bottom_whipsaw_summary(
    model_b: V31BacktestResult,
    model_j: V31BacktestResult,
    daily_by_model: dict[str, pd.DataFrame],
    windows: dict[str, list[str]],
    pair_frames: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    cutoff = max(pd.Timestamp(daily_by_model[m]["date"].max()) for m in ("B", "J"))
    periods = {"FULL": ["2020-01-01", "end"], "BOTTOM_2022": windows["BOTTOM_2022"], "BOTTOM_2026": windows["BOTTOM_2026"]}
    events = {"B": _actual_tactical_events(model_b), "J": _actual_tactical_events(model_j)}
    rows = []
    for period, bounds in periods.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "J"):
            segment = events[model].loc[events[model]["timestamp"].between(start, end)].sort_values("timestamp")
            days = segment["timestamp"].diff().dt.total_seconds().div(86400).dropna()
            daily = daily_by_model[model].loc[lambda x: x["date"].between(start, end)]
            pairs = pair_frames[model]
            pair_count = int(pd.to_datetime(pairs.get("second_timestamp", pd.Series(dtype="datetime64[ns, UTC]")), utc=True).between(start, end).sum()) if not pairs.empty else 0
            notional = float(segment["gross_notional"].sum())
            average_value = float(daily["portfolio_value"].mean()) if not daily.empty else np.nan
            rows.append({
                "period": period, "model": model, "start": start, "end": end,
                "tactical_event_count": int(len(segment)),
                "tactical_trade_rows": int(2 * len(segment)),
                "tactical_notional_usd": notional,
                "tactical_turnover": notional / average_value if average_value else np.nan,
                "whipsaw_pair_count": pair_count,
                "average_days_between_events": float(days.mean()) if len(days) else np.nan,
                "median_days_between_events": float(days.median()) if len(days) else np.nan,
            })
    return pd.DataFrame(rows)


def tactical_statistics(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "J"}:
            continue
        tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
        events = tactical.drop_duplicates("tactical_event_id").sort_values("timestamp")
        days = pd.to_datetime(events["timestamp"], utc=True).diff().dt.total_seconds().div(86400).dropna()
        average_value = float(result.history["portfolio_value"].mean())
        notional = float(tactical["gross_notional_usd"].sum())
        rows.append({
            "model": result.scenario.model,
            "total_tactical_events": int(tactical["tactical_event_id"].nunique()),
            "total_tactical_trade_rows": int(len(tactical)),
            "tactical_notional_usd": notional,
            "tactical_turnover": notional / average_value,
            "average_days_between_events": float(days.mean()) if len(days) else np.nan,
            "median_days_between_events": float(days.median()) if len(days) else np.nan,
        })
    return pd.DataFrame(rows)


def event_drawdown_audit(
    daily_by_model: dict[str, pd.DataFrame],
    results: list[V31BacktestResult],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    result_map = {result.scenario.model: result for result in results}
    cutoff = max(pd.Timestamp(daily_by_model[m]["date"].max()) for m in ("B", "J"))
    rows = []
    for event, bounds in windows.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "J"):
            segment = daily_by_model[model].loc[lambda x: x["date"].between(start, end)].copy()
            if segment.empty:
                continue
            drawdown = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            tactical = result_map[model].trades.loc[
                result_map[model].trades["action"].str.startswith("TACTICAL", na=False)
                & pd.to_datetime(result_map[model].trades["timestamp"], utc=True).between(start, end)
            ]
            rows.append({
                "event": event, "model": model, "start": start, "end": end,
                "peak_to_trough_drawdown": float(drawdown.min()),
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
    parity: dict[str, Any],
    scope: dict[str, Any],
    *,
    integrity_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    perf = summary.set_index("model")
    b, j = perf.loc["B"], perf.loc["J"]
    bottom_index = bottom.set_index(["period", "model"])
    event_index = events.set_index(["event", "model"])
    tactical_index = tactical.set_index("model")

    def reduction(period: str, column: str) -> float:
        base = float(bottom_index.loc[(period, "B"), column])
        challenger = float(bottom_index.loc[(period, "J"), column])
        return 1.0 - challenger / base if base else (1.0 if challenger == 0 else -np.inf)

    def dd_regression(event: str) -> float:
        return 100.0 * (
            float(event_index.loc[(event, "B"), "peak_to_trough_drawdown"])
            - float(event_index.loc[(event, "J"), "peak_to_trough_drawdown"])
        )

    r2022 = reduction("BOTTOM_2022", "tactical_event_count")
    r2026 = reduction("BOTTOM_2026", "tactical_event_count")
    rpair = reduction("FULL", "whipsaw_pair_count")
    turnover_reduction = 1.0 - float(tactical_index.loc["J", "tactical_turnover"]) / float(tactical_index.loc["B", "tactical_turnover"])
    dd2022 = dd_regression("BEAR_2021NOV_2022JUN")
    dd2025 = dd_regression("CORRECTION_2025_2026")
    overall_dd_regression = 100.0 * (float(b["maximum_drawdown"]) - float(j["maximum_drawdown"]))
    gates = rules["promotion_gates"]
    checks = {
        "G0_SHADOW_STATE_PARITY_ALL_ZERO": bool(parity["pass"]),
        "G1_OVERLAY_RESTRICTED_ACTIONS_AHR_ONLY": bool(scope["pass"]),
        "G2_2022_BOTTOM_EVENTS_REDUCTION_GTE_40PCT": r2022 >= gates["bottom_2022_event_reduction_min_fraction"],
        "G3_2026_BOTTOM_EVENTS_REDUCTION_GTE_40PCT": r2026 >= gates["bottom_2026_event_reduction_min_fraction"],
        "G4_WHIPSAW_PAIRS_REDUCTION_GTE_50PCT": rpair >= gates["whipsaw_pair_reduction_min_fraction"],
        "G5_OVERALL_TURNOVER_REDUCTION_GTE_15PCT": turnover_reduction >= gates["overall_tactical_turnover_reduction_min_fraction"],
        "G6_2022_BEAR_DD_REGRESSION_LTE_2PP": dd2022 <= gates["bear_2021nov_2022jun_dd_regression_max_pp"],
        "G7_2025_2026_DD_REGRESSION_LTE_2PP": dd2025 <= gates["correction_2025_2026_dd_regression_max_pp"],
        "G8_OVERALL_MAX_DD_REGRESSION_LTE_2PP": overall_dd_regression <= gates["overall_max_dd_regression_max_pp"],
        "G9_TWR_CAGR_GTE_45PCT": float(j["twr_cagr"]) >= gates["twr_cagr_minimum"],
        "G10_FINAL_VALUE_GTE_95PCT_OF_B": float(j["final_portfolio_value"]) >= gates["final_value_min_fraction_of_v31_b"] * float(b["final_portfolio_value"]),
        "G11_ALL_INTEGRITY_PASS": bool(integrity_pass),
    }
    promoted = all(checks.values())
    if not parity["pass"]:
        final = "C. V3.7 INVALID — STATE CONTAMINATION"
    elif not scope["pass"] or not integrity_pass:
        final = "D. V3.7 OVERLAY REJECTED"
    elif promoted:
        final = "A. V3.7 EXECUTION OVERLAY PROMOTED"
    else:
        final = "B. V3.1 REMAINS CHAMPION"
    comparison = pd.DataFrame([{
        "comparison": "J V3.7 vs B V3.1",
        "delta_final_value": float(j["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": 100.0 * float(j["twr_cagr"] - b["twr_cagr"]),
        "delta_max_drawdown_percentage_points": 100.0 * float(j["maximum_drawdown"] - b["maximum_drawdown"]),
        "delta_calmar": float(j["calmar"] - b["calmar"]),
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
        "final_verdict": final,
    }


def no_lookahead_audit(
    frame: pd.DataFrame,
    daily_features: pd.DataFrame,
    results: list[V31BacktestResult],
    data_contract: dict[str, Any],
    fixed_dca: pd.DataFrame,
    fsm: pd.DataFrame,
    replay: dict[str, Any],
    shadow_replay: dict[str, Any],
    parity: dict[str, Any],
    scope: dict[str, Any],
    prefix_checks: dict[str, bool],
    engine_source: str,
) -> dict[str, Any]:
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    timing_violations = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    j = next(result for result in results if result.scenario.model == "J")
    jt = j.trades.loc[j.trades["action"].str.startswith("TACTICAL", na=False)]
    direction = jt.groupby("timestamp")["side"].nunique() if not jt.empty else pd.Series(dtype=int)
    opposite_violations = int((direction > 1).sum())
    forbidden = [token for token in ("v32_", "v33_", "v34_", "v35_", "v36_", "requalification", "level3") if token in engine_source.lower()]
    future_tokens = [token for token in ("shift(-", "future_min_return", "bear_label", "label_end_date") if token in engine_source]
    completed_violations = int((daily_features["close_time"] >= daily_features["signal_available_at"]).sum())
    checks = {
        "data_contract_pass": bool(data_contract["pass"]),
        "signal_available_no_later_than_execution": int((frame["signal_available_at"] > frame["open_time"]).sum()) == 0,
        "completed_daily_features_only": completed_violations == 0,
        "tactical_execution_next_4h_or_later": timing_violations == 0,
        "no_future_columns_in_execution_frame": not data_contract["future_label_columns_in_execution_frame"],
        "fixed_dca_row_integrity": bool(fixed_dca["all_match"].all()),
        "fsm_legal": bool(not fsm.empty and fsm["legal_transition"].all()),
        "v31_replay_exact": bool(replay["pass"]),
        "independent_shadow_replay_exact": bool(shadow_replay["pass"]),
        "shadow_state_parity": bool(parity["pass"]),
        "overlay_scope": bool(scope["pass"]),
        "prefix_invariance": bool(all(prefix_checks.values())),
        "no_same_timestamp_opposite_tactical_action": opposite_violations == 0,
        "v37_engine_has_no_later_version_inheritance": not forbidden,
        "no_future_tokens_in_execution_source": not future_tokens,
    }
    return {
        "no_lookahead_pass": bool(all(checks.values())),
        "execution_integrity_pass": bool(
            checks["fixed_dca_row_integrity"] and checks["fsm_legal"]
            and checks["v31_replay_exact"] and checks["independent_shadow_replay_exact"]
            and checks["shadow_state_parity"] and checks["overlay_scope"]
            and checks["no_same_timestamp_opposite_tactical_action"]
        ),
        "checks": checks,
        "timing_violations": timing_violations,
        "completed_feature_violations": completed_violations,
        "same_timestamp_opposite_tactical_action_violations": opposite_violations,
        "forbidden_inheritance_tokens": forbidden,
        "future_tokens": future_tokens,
    }


__all__ = [
    "bottom_whipsaw_audit", "bottom_whipsaw_summary", "daily_history_v37",
    "event_drawdown_audit", "fixed_dca_integrity", "fsm_audit",
    "no_lookahead_audit", "overlay_scope_audit", "promotion_evaluation",
    "shadow_replay_integrity", "shadow_state_parity_audit", "summary_v37",
    "tactical_statistics", "v31_replay_integrity", "whipsaw_pairs",
]
