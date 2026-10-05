from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import daily_history_v31, enriched_summary
from .v31_engine import V31BacktestResult
from .v37_analysis import (
    fixed_dca_integrity,
    fsm_audit,
    shadow_replay_integrity,
    shadow_state_parity_audit,
    v31_replay_integrity,
    whipsaw_pairs,
)
from .v38_engine import AHR_ACTION, RIGHT_ACTIONS


RISK_SELL = "RISK_SELL"


def daily_history_v38(history: pd.DataFrame) -> pd.DataFrame:
    daily = daily_history_v31(history)
    source = history.copy()
    source["date"] = pd.to_datetime(source["timestamp"], utc=True).dt.floor("D")
    extras = [
        "actual_crypto_exposure", "macro_state_shadow", "sell_stage_shadow",
        "cycle_id_shadow", "active_target_shadow", "shadow_target_exposure",
        "crash_state_shadow", "new_bull_state_shadow", "desired_action_shadow",
        "desired_signal_type_shadow", "desired_exposure_target_shadow",
        "cooldown_completed_closes", "cooldown_remaining_closes", "pending_ahr_buy",
    ]
    present = [column for column in extras if column in source]
    if present:
        daily = daily.merge(
            source.groupby("date", as_index=False)[present].last(),
            on="date", how="left", validate="one_to_one",
        )
    return daily


def summary_v38(result: V31BacktestResult, base_rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, base_rules)
    tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["tactical_notional_usd"] = float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0
    for name in (
        "requested_ahr_buys", "delayed_ahr_buys", "executed_ahr_buys",
        "executed_after_delay", "cancelled_ahr_buys",
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


def v37_replay_integrity(
    model_j7: V31BacktestResult,
    v37_dir: Path,
    reference: dict[str, float],
    base_rules: dict[str, Any],
) -> dict[str, Any]:
    prior_summary = pd.read_csv(v37_dir / "results" / "summary_v3_7.csv").set_index("model")
    prior_trades = pd.read_csv(v37_dir / "results" / "trade_log_v3_7.csv")
    current_enriched = enriched_summary(model_j7, base_rules)
    metrics = {
        "final_portfolio_value": float(model_j7.summary["final_portfolio_value"]),
        "maximum_drawdown": float(model_j7.summary["maximum_drawdown"]),
        "twr_cagr": float(model_j7.summary["time_weighted_cagr"]),
        "calmar": float(model_j7.summary["calmar"]),
        "tactical_turnover": float(current_enriched["tactical_turnover"]),
        "tactical_event_count": int(current_enriched["tactical_event_count"]),
    }
    reference_delta = {key: abs(float(value) - float(reference[key])) for key, value in metrics.items()}
    prior = prior_summary.loc["J"]
    prior_delta = {key: abs(float(value) - float(prior[key])) for key, value in metrics.items()}
    current_trades = model_j7.trades.copy()
    prior_trade_rows = prior_trades.loc[prior_trades["model"].eq("J")].copy()
    for data in (current_trades, prior_trade_rows):
        for column in ("timestamp", "signal_date"):
            data[column] = pd.to_datetime(data[column], utc=True, errors="coerce")
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd",
    ]
    trades_pass, trade_delta = _frame_exact(
        current_trades[keys + numeric], prior_trade_rows[keys + numeric], keys, numeric,
    )
    return {
        "pass": bool(max(reference_delta.values()) <= 1e-9 and max(prior_delta.values()) <= 1e-9 and trades_pass),
        "reference_metric_max_abs_delta": max(reference_delta.values()),
        "prior_output_metric_max_abs_delta": max(prior_delta.values()),
        "trade_rows_current": len(current_trades), "trade_rows_prior": len(prior_trade_rows),
        "trade_numeric_max_abs_delta": trade_delta, "trade_rows_exact": trades_pass,
        "tactical_event_count": metrics["tactical_event_count"],
    }


def overlay_scope_audit(overlay: pd.DataFrame, shadow: V31BacktestResult) -> dict[str, Any]:
    restricted = overlay.loc[overlay["restricted_by_overlay"].astype(bool)]
    restricted_non_ahr = restricted.loc[restricted["shadow_signal_type"].ne("AHR_VALUE_BUY")]
    nonexecute = overlay.loc[overlay["overlay_decision"].ne("EXECUTE")]
    risk_restricted = int(nonexecute["shadow_signal_type"].eq(RISK_SELL).sum())
    right_restricted = int(nonexecute["shadow_signal_type"].isin({"RIGHT_SIDE_TO_50", "RIGHT_SIDE_TO_60"}).sum())
    new_bull_restricted = int(nonexecute["shadow_signal_type"].eq("NEW_BULL_REDEPLOY").sum())
    shadow_events = int(shadow.trades.loc[
        shadow.trades["action"].str.startswith("TACTICAL", na=False), "tactical_event_id"
    ].nunique())
    original = overlay.loc[overlay["shadow_action"].ne("PENDING_AHR_BUY")]
    represented = int(original["shadow_event_id"].replace("", np.nan).dropna().nunique())
    risk_no_trade = int((
        overlay["shadow_signal_type"].eq(RISK_SELL)
        & overlay["actual_action"].eq("NO_TRADE_ALREADY_BELOW_TARGET")
        & overlay["overlay_decision"].eq("EXECUTE")
    ).sum())
    passed = bool(
        restricted_non_ahr.empty and risk_restricted == 0 and right_restricted == 0
        and new_bull_restricted == 0 and represented == shadow_events
    )
    return {
        "pass": passed, "restricted_rows": int(len(restricted)),
        "restricted_non_ahr_rows": int(len(restricted_non_ahr)),
        "risk_sell_restricted_count": risk_restricted,
        "right_side_restricted_count": right_restricted,
        "new_bull_restricted_count": new_bull_restricted,
        "risk_sell_no_trade_already_below_target_count": risk_no_trade,
        "shadow_tactical_event_count": shadow_events,
        "shadow_tactical_events_represented": represented,
    }


def enrich_opportunity_cost(
    delay_records: pd.DataFrame,
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    records = delay_records.copy()
    if records.empty:
        return records, {
            "delayed_record_count": 0, "executed_record_count": 0,
            "cancelled_record_count": 0, "pending_record_count": 0,
            "average_delay_completed_closes": np.nan,
            "median_delay_completed_closes": np.nan,
            "average_btc_price_cost_fraction": np.nan,
            "average_eth_price_cost_fraction": np.nan,
        }
    records["original_shadow_execution_date"] = pd.to_datetime(records["original_shadow_execution_date"], utc=True)
    records["actual_execution_date"] = pd.to_datetime(records["actual_execution_date"], utc=True)
    market = frame[["open_time", "BTC_close"]].sort_values("open_time").reset_index(drop=True)
    times = pd.DatetimeIndex(pd.to_datetime(market["open_time"], utc=True))
    closes = market["BTC_close"].astype(float).to_numpy()

    def forward_return(row: pd.Series, days: int) -> float:
        target = row["original_shadow_execution_date"] + pd.Timedelta(days=days)
        index = int(times.searchsorted(target, side="left"))
        if index >= len(times):
            return np.nan
        return float(closes[index] / float(row["btc_price_original"]) - 1.0)

    records["30d_btc_return_after_original_signal"] = records.apply(lambda row: forward_return(row, 30), axis=1)
    records["60d_btc_return_after_original_signal"] = records.apply(lambda row: forward_return(row, 60), axis=1)
    executed = records["executed_or_cancelled"].astype(str).str.startswith("EXECUTED")
    records["btc_price_cost_fraction"] = np.where(
        executed, records["btc_price_actual"] / records["btc_price_original"] - 1.0, np.nan
    )
    records["eth_price_cost_fraction"] = np.where(
        executed, records["eth_price_actual"] / records["eth_price_original"] - 1.0, np.nan
    )
    cancelled = records["executed_or_cancelled"].eq("CANCELLED")
    pending = records["executed_or_cancelled"].eq("PENDING_AT_END")
    stats = {
        "delayed_record_count": int(len(records)),
        "executed_record_count": int(executed.sum()),
        "cancelled_record_count": int(cancelled.sum()),
        "pending_record_count": int(pending.sum()),
        "average_delay_completed_closes": float(records.loc[executed, "delay_completed_closes"].mean()),
        "median_delay_completed_closes": float(records.loc[executed, "delay_completed_closes"].median()),
        "average_btc_price_cost_fraction": float(records.loc[executed, "btc_price_cost_fraction"].mean()),
        "average_eth_price_cost_fraction": float(records.loc[executed, "eth_price_cost_fraction"].mean()),
        "average_30d_btc_return_after_original_signal": float(records["30d_btc_return_after_original_signal"].mean()),
        "average_60d_btc_return_after_original_signal": float(records["60d_btc_return_after_original_signal"].mean()),
    }
    return records, stats


def actual_tactical_events(result: V31BacktestResult) -> pd.DataFrame:
    trades = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if trades.empty:
        return pd.DataFrame(columns=["model", "timestamp", "action", "side", "signal_type"])
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
    return events.sort_values("timestamp")


def short_whipsaw_pairs(
    result: V31BacktestResult,
    signal_index: dict[pd.Timestamp, int],
) -> pd.DataFrame:
    events = actual_tactical_events(result)
    last_sell: Any = None
    rows = []
    for event in events.itertuples():
        if event.signal_type == RISK_SELL:
            last_sell = event
            continue
        if event.signal_type != "AHR_VALUE_BUY" or last_sell is None:
            continue
        current_index = signal_index.get(pd.Timestamp(event.timestamp))
        sell_index = signal_index.get(pd.Timestamp(last_sell.timestamp))
        if current_index is None or sell_index is None:
            continue
        gap = int(current_index - sell_index)
        if 1 <= gap <= 3:
            rows.append({
                "model": result.scenario.model,
                "sell_event_id": last_sell.tactical_event_id,
                "ahr_event_id": event.tactical_event_id,
                "sell_timestamp": last_sell.timestamp,
                "ahr_timestamp": event.timestamp,
                "completed_daily_closes_between": gap,
            })
    return pd.DataFrame(rows)


def _overlay_records(model: str, overlay: pd.DataFrame) -> pd.DataFrame:
    work = overlay.copy()
    work["model"] = model
    work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
    work["record_type"] = "SHADOW_REQUEST_OR_PENDING"
    work["action"] = work["shadow_action"]
    work["signal_type"] = work["shadow_signal_type"]
    work["side"] = np.where(work["shadow_signal_type"].eq(RISK_SELL), "SELL", "BUY")
    work["exposure_before"] = work["actual_exposure_before"]
    work["exposure_after"] = work["actual_exposure_after"]
    work["gross_notional"] = np.nan
    return work


def bottom_whipsaw_audit(
    results: list[V31BacktestResult],
    j7_overlay: pd.DataFrame,
    k_overlay: pd.DataFrame,
    signal_index: dict[pd.Timestamp, int],
) -> pd.DataFrame:
    actual = pd.concat([actual_tactical_events(result) for result in results], ignore_index=True, sort=False)
    actual["record_type"] = "ACTUAL_EXECUTED"
    actual["overlay_decision"] = "EXECUTE"
    actual["decision_reason"] = actual["reason"]
    actual["cooldown_completed_closes"] = np.nan
    actual["cooldown_remaining_closes"] = np.nan
    actual["pending_ahr_buy"] = False
    overlay_rows = pd.concat([
        _overlay_records("J7", j7_overlay), _overlay_records("K", k_overlay)
    ], ignore_index=True, sort=False)
    combined = pd.concat([actual, overlay_rows], ignore_index=True, sort=False)
    combined["execution_signal_index"] = combined["timestamp"].map(signal_index)
    keep = [
        "model", "timestamp", "record_type", "action", "signal_type", "side",
        "overlay_decision", "decision_reason", "exposure_before", "exposure_after",
        "gross_notional", "cooldown_completed_closes", "cooldown_remaining_closes",
        "pending_ahr_buy", "execution_signal_index",
    ]
    for column in keep:
        if column not in combined:
            combined[column] = np.nan
    return combined[keep].sort_values(["timestamp", "model", "record_type"])


def _bounds(bounds: list[str], cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(bounds[0], tz="UTC")
    end = cutoff if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
    return start, end


def bottom_summary(
    results: list[V31BacktestResult],
    daily_by_model: dict[str, pd.DataFrame],
    windows: dict[str, list[str]],
    short_pairs: dict[str, pd.DataFrame],
    seven_pairs: dict[str, pd.DataFrame],
    overlays: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    cutoff = max(pd.Timestamp(daily_by_model[model]["date"].max()) for model in ("B", "J7", "K"))
    periods = {
        "FULL": ["2020-01-01", "end"],
        "BOTTOM_2022": windows["BOTTOM_2022"],
        "BOTTOM_2026": windows["BOTTOM_2026"],
    }
    event_map = {result.scenario.model: actual_tactical_events(result) for result in results}
    rows = []
    for period, bounds in periods.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "J7", "K"):
            events = event_map[model]
            segment = events.loc[events["timestamp"].between(start, end)].sort_values("timestamp")
            days = segment["timestamp"].diff().dt.total_seconds().div(86400).dropna()
            daily = daily_by_model[model].loc[lambda x: x["date"].between(start, end)]
            drawdown = daily["unit_nav"] / daily["unit_nav"].cummax() - 1.0
            short = short_pairs[model]
            short_count = int(pd.to_datetime(
                short.get("ahr_timestamp", pd.Series(dtype="datetime64[ns, UTC]")), utc=True
            ).between(start, end).sum()) if not short.empty else 0
            seven = seven_pairs[model]
            seven_count = int(pd.to_datetime(
                seven.get("second_timestamp", pd.Series(dtype="datetime64[ns, UTC]")), utc=True
            ).between(start, end).sum()) if not seven.empty else 0
            overlay = overlays.get(model, pd.DataFrame())
            if overlay.empty:
                delayed = cancelled = executed_pending = 0
            else:
                scoped = overlay.loc[pd.to_datetime(overlay["timestamp"], utc=True).between(start, end)]
                delayed = int((
                    scoped["shadow_action"].ne("PENDING_AHR_BUY")
                    & scoped["overlay_decision"].eq("DELAY")
                    & scoped["shadow_signal_type"].eq("AHR_VALUE_BUY")
                ).sum())
                cancelled = int(scoped["overlay_decision"].eq("CANCEL").sum())
                executed_pending = int((
                    scoped["shadow_action"].eq("PENDING_AHR_BUY")
                    & scoped["overlay_decision"].eq("EXECUTE")
                ).sum())
            notional = float(segment["gross_notional"].sum())
            average_value = float(daily["portfolio_value"].mean()) if not daily.empty else np.nan
            rows.append({
                "period": period, "model": model, "start": start, "end": end,
                "tactical_event_count": int(len(segment)),
                "tactical_notional_usd": notional,
                "tactical_turnover": notional / average_value if average_value else np.nan,
                "short_three_close_whipsaw_count": short_count,
                "seven_calendar_day_whipsaw_count": seven_count,
                "ahr_delayed_shadow_requests": delayed,
                "ahr_cancelled_pending_orders": cancelled,
                "ahr_executed_after_delay": executed_pending,
                "portfolio_drawdown": float(drawdown.min()),
                "average_days_between_events": float(days.mean()) if len(days) else np.nan,
                "median_days_between_events": float(days.median()) if len(days) else np.nan,
            })
    return pd.DataFrame(rows)


def tactical_statistics(
    results: list[V31BacktestResult],
    short_pairs: dict[str, pd.DataFrame],
    seven_pairs: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    rows = []
    for result in results:
        if result.scenario.model not in {"B", "J7", "K"}:
            continue
        tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
        events = tactical.drop_duplicates("tactical_event_id").sort_values("timestamp")
        days = pd.to_datetime(events["timestamp"], utc=True).diff().dt.total_seconds().div(86400).dropna()
        notional = float(tactical["gross_notional_usd"].sum())
        average_value = float(result.history["portfolio_value"].mean())
        model = result.scenario.model
        rows.append({
            "model": model,
            "total_tactical_events": int(tactical["tactical_event_id"].nunique()),
            "total_tactical_trade_rows": int(len(tactical)),
            "tactical_notional_usd": notional,
            "tactical_turnover": notional / average_value,
            "short_three_close_whipsaw_count": int(len(short_pairs[model])),
            "seven_calendar_day_whipsaw_count": int(len(seven_pairs[model])),
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
    cutoff = max(pd.Timestamp(daily_by_model[model]["date"].max()) for model in ("B", "J7", "K"))
    rows = []
    for event, bounds in windows.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "J7", "K"):
            segment = daily_by_model[model].loc[lambda x: x["date"].between(start, end)].copy()
            if segment.empty:
                continue
            drawdown = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            trades = result_map[model].trades
            tactical = trades.loc[
                trades["action"].str.startswith("TACTICAL", na=False)
                & pd.to_datetime(trades["timestamp"], utc=True).between(start, end)
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
    tactical: pd.DataFrame,
    events: pd.DataFrame,
    rules: dict[str, Any],
    parity: dict[str, Any],
    scope: dict[str, Any],
    *,
    integrity_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    perf = summary.set_index("model")
    stats = tactical.set_index("model")
    event_index = events.set_index(["event", "model"])
    b, k = perf.loc["B"], perf.loc["K"]

    def reduction(column: str) -> float:
        baseline = float(stats.loc["B", column])
        challenger = float(stats.loc["K", column])
        return 1.0 - challenger / baseline if baseline else (1.0 if challenger == 0 else -np.inf)

    def dd_regression(event: str) -> float:
        return 100.0 * (
            float(event_index.loc[(event, "B"), "peak_to_trough_drawdown"])
            - float(event_index.loc[(event, "K"), "peak_to_trough_drawdown"])
        )

    short_reduction = reduction("short_three_close_whipsaw_count")
    seven_reduction = reduction("seven_calendar_day_whipsaw_count")
    turnover_reduction = reduction("tactical_turnover")
    event_reduction = reduction("total_tactical_events")
    dd2022 = dd_regression("BEAR_2021NOV_2022JUN")
    dd2025 = dd_regression("CORRECTION_2025_2026")
    overall_dd_regression = 100.0 * (float(b["maximum_drawdown"]) - float(k["maximum_drawdown"]))
    calmar_shortfall = float(b["calmar"] - k["calmar"])
    gates = rules["promotion_gates"]
    checks = {
        "G0_SHADOW_STATE_PARITY_ALL_ZERO": bool(parity["pass"]),
        "G1_OVERLAY_RESTRICTED_ACTIONS_AHR_ONLY": bool(scope["pass"]),
        "G2_SHORT_3_CLOSE_WHIPSAW_REDUCTION_GTE_50PCT": short_reduction >= gates["short_three_close_whipsaw_reduction_min_fraction"],
        "G3_7_DAY_WHIPSAW_REDUCTION_GTE_25PCT": seven_reduction >= gates["seven_calendar_day_whipsaw_reduction_min_fraction"],
        "G4_OVERALL_TURNOVER_REDUCTION_GTE_7_5PCT": turnover_reduction >= gates["overall_tactical_turnover_reduction_min_fraction"],
        "G5_TACTICAL_EVENT_REDUCTION_GTE_10PCT_AND_COUNT_LTE_95": (
            event_reduction >= gates["overall_tactical_event_reduction_min_fraction"]
            and int(stats.loc["K", "total_tactical_events"]) <= int(gates["overall_tactical_event_count_maximum"])
        ),
        "G6_2022_BEAR_DD_REGRESSION_LTE_2PP": dd2022 <= gates["bear_2021nov_2022jun_dd_regression_max_pp"],
        "G7_2025_2026_DD_REGRESSION_LTE_2PP": dd2025 <= gates["correction_2025_2026_dd_regression_max_pp"],
        "G8_OVERALL_MAX_DD_REGRESSION_LTE_1PP": overall_dd_regression <= gates["overall_max_dd_regression_max_pp"],
        "G9_TWR_CAGR_GTE_46_5PCT": float(k["twr_cagr"]) >= gates["twr_cagr_minimum"],
        "G10_FINAL_VALUE_GTE_98PCT_OF_B": float(k["final_portfolio_value"]) >= gates["final_value_min_fraction_of_v31_b"] * float(b["final_portfolio_value"]),
        "G11_CALMAR_SHORTFALL_LTE_0_05": calmar_shortfall <= gates["calmar_shortfall_maximum"],
        "G12_ALL_INTEGRITY_PASS": bool(integrity_pass),
    }
    promoted = all(checks.values())
    if not parity["pass"]:
        final = "C. V3.8 INVALID — STATE CONTAMINATION"
    elif not scope["pass"] or not integrity_pass:
        final = "D. V3.8 OVERLAY REJECTED"
    elif promoted:
        final = "A. V3.8 EXECUTION OVERLAY PROMOTED"
    else:
        final = "B. V3.1 REMAINS CHAMPION"
    comparison = pd.DataFrame([{
        "comparison": "K V3.8 vs B V3.1",
        "delta_final_value": float(k["final_portfolio_value"] - b["final_portfolio_value"]),
        "final_value_fraction_of_b": float(k["final_portfolio_value"] / b["final_portfolio_value"]),
        "delta_cagr_percentage_points": 100.0 * float(k["twr_cagr"] - b["twr_cagr"]),
        "delta_max_drawdown_percentage_points": 100.0 * float(k["maximum_drawdown"] - b["maximum_drawdown"]),
        "delta_calmar": float(k["calmar"] - b["calmar"]),
        "short_three_close_whipsaw_reduction_fraction": short_reduction,
        "seven_calendar_day_whipsaw_reduction_fraction": seven_reduction,
        "overall_turnover_reduction_fraction": turnover_reduction,
        "overall_tactical_event_reduction_fraction": event_reduction,
        "2022_bear_dd_regression_percentage_points": dd2022,
        "2025_2026_dd_regression_percentage_points": dd2025,
        "overall_max_dd_regression_percentage_points": overall_dd_regression,
        "calmar_shortfall": calmar_shortfall,
    }])
    verdict = {
        "promotion_gate": "PASS" if promoted else "FAIL",
        "checks": {key: bool(value) for key, value in checks.items()},
        "final_verdict": final,
    }
    j_law = {
        "Champion": "V3.1 Model B",
        "Challenger": "V3.8 Model K",
        "State Isolation Integrity": "PASS" if parity["pass"] else "FAIL",
        "Return Edge": "PASS" if checks["G9_TWR_CAGR_GTE_46_5PCT"] and checks["G10_FINAL_VALUE_GTE_98PCT_OF_B"] else "FAIL",
        "Drawdown Edge": "PASS" if checks["G8_OVERALL_MAX_DD_REGRESSION_LTE_1PP"] else "FAIL",
        "2022 Bear Protection": "PASS" if checks["G6_2022_BEAR_DD_REGRESSION_LTE_2PP"] else "FAIL",
        "2026 Bear Protection": "PASS" if checks["G7_2025_2026_DD_REGRESSION_LTE_2PP"] else "FAIL",
        "Short Whipsaw Reduction": "PASS" if checks["G2_SHORT_3_CLOSE_WHIPSAW_REDUCTION_GTE_50PCT"] else "FAIL",
        "Turnover Reduction": "PASS" if checks["G4_OVERALL_TURNOVER_REDUCTION_GTE_7_5PCT"] else "FAIL",
        "AHR Delay Opportunity Cost": float(b["final_portfolio_value"] - k["final_portfolio_value"]),
        "Execution Efficiency": "PASS" if checks["G4_OVERALL_TURNOVER_REDUCTION_GTE_7_5PCT"] and checks["G5_TACTICAL_EVENT_REDUCTION_GTE_10PCT_AND_COUNT_LTE_95"] else "FAIL",
        "Bull Re-entry Integrity": "PASS" if scope["new_bull_restricted_count"] == 0 else "FAIL",
        "Risk Sell Integrity": "PASS" if scope["risk_sell_restricted_count"] == 0 else "FAIL",
        "No Look Ahead": "PASS" if integrity_pass else "FAIL",
        "Overfit Risk": "ELEVATED_SINGLE_REALIZED_PATH",
        "Final Verdict": final,
    }
    return comparison, verdict, j_law


def original_order_violations(model_k: V31BacktestResult) -> int:
    trades = model_k.trades.reset_index(drop=True).copy()
    violations = 0
    for _, group in trades.groupby("timestamp", sort=False):
        tactical = group.index[group["action"].str.startswith("TACTICAL", na=False)]
        dca = group.index[group["action"].eq("NORMAL_DCA")]
        if len(tactical) and len(dca) and int(tactical.max()) > int(dca.min()):
            violations += 1
    return violations


def no_lookahead_audit(
    frame: pd.DataFrame,
    daily_features: pd.DataFrame,
    results: list[V31BacktestResult],
    data_contract: dict[str, Any],
    fixed_dca: pd.DataFrame,
    fsm: pd.DataFrame,
    replay_b: dict[str, Any],
    replay_j7: dict[str, Any],
    shadow_replay: dict[str, Any],
    parity: dict[str, Any],
    scope: dict[str, Any],
    opportunity_stats: dict[str, Any],
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
    k = next(result for result in results if result.scenario.model == "K")
    kt = k.trades.loc[k.trades["action"].str.startswith("TACTICAL", na=False)]
    direction = kt.groupby("timestamp")["side"].nunique() if not kt.empty else pd.Series(dtype=int)
    opposite_violations = int((direction > 1).sum())
    order_violations = original_order_violations(k)
    future_tokens = [
        token for token in ("shift(-", "future_min_return", "bear_label", "label_end_date", "30d_btc_return", "60d_btc_return")
        if token in engine_source
    ]
    reporting_date_tokens = [
        token for token in ("2022-06-01", "2022-07-31", "2026-02-01", "2026-06-30", "promotion_gates")
        if token in engine_source
    ]
    completed_violations = int((daily_features["close_time"] >= daily_features["signal_available_at"]).sum())
    checks = {
        "data_contract_pass": bool(data_contract["pass"]),
        "signal_available_no_later_than_execution": int((frame["signal_available_at"] > frame["open_time"]).sum()) == 0,
        "completed_daily_features_only": completed_violations == 0,
        "tactical_execution_next_4h_or_later": timing_violations == 0,
        "no_future_columns_in_execution_frame": not data_contract["future_label_columns_in_execution_frame"],
        "fixed_dca_row_integrity": bool(fixed_dca["all_match"].all()),
        "fsm_legal": bool(not fsm.empty and fsm["legal_transition"].all()),
        "v31_replay_exact": bool(replay_b["pass"]),
        "v37_j7_replay_exact": bool(replay_j7["pass"]),
        "independent_shadow_replay_exact": bool(shadow_replay["pass"]),
        "shadow_state_parity": bool(parity["pass"]),
        "overlay_scope": bool(scope["pass"]),
        "prefix_invariance": bool(all(prefix_checks.values())),
        "original_v31_tactical_before_dca_order": order_violations == 0,
        "no_same_timestamp_opposite_tactical_action": opposite_violations == 0,
        "opportunity_lifecycle_complete": opportunity_stats["pending_record_count"] == 0,
        "no_future_tokens_in_execution_source": not future_tokens,
        "no_audit_dates_or_promotion_gates_in_execution_source": not reporting_date_tokens,
    }
    return {
        "no_lookahead_pass": bool(all(checks.values())),
        "execution_integrity_pass": bool(
            checks["fixed_dca_row_integrity"] and checks["fsm_legal"]
            and checks["v31_replay_exact"] and checks["v37_j7_replay_exact"]
            and checks["independent_shadow_replay_exact"] and checks["shadow_state_parity"]
            and checks["overlay_scope"] and checks["original_v31_tactical_before_dca_order"]
            and checks["no_same_timestamp_opposite_tactical_action"]
            and checks["opportunity_lifecycle_complete"]
        ),
        "checks": checks,
        "timing_violations": timing_violations,
        "completed_feature_violations": completed_violations,
        "same_timestamp_opposite_tactical_action_violations": opposite_violations,
        "original_order_violations": order_violations,
        "future_tokens": future_tokens,
        "reporting_date_tokens_in_engine": reporting_date_tokens,
    }


__all__ = [
    "actual_tactical_events", "bottom_summary", "bottom_whipsaw_audit",
    "daily_history_v38", "enrich_opportunity_cost", "event_drawdown_audit",
    "fixed_dca_integrity", "fsm_audit", "no_lookahead_audit",
    "overlay_scope_audit", "promotion_evaluation", "shadow_replay_integrity",
    "shadow_state_parity_audit", "short_whipsaw_pairs", "summary_v38",
    "tactical_statistics", "v31_replay_integrity", "v37_replay_integrity",
    "whipsaw_pairs",
]
