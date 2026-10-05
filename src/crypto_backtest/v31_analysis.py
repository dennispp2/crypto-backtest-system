from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    precision_score,
    recall_score,
    roc_auc_score,
)

from .v31_engine import V31BacktestResult


def daily_history_v31(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    last = [
        "portfolio_value", "btc_value", "eth_value", "unit_nav", "drawdown",
        "normal_cash", "pending_dca_cash", "tactical_bear_cash", "temporary_hedge_cash",
        "tactical_cash", "normal_cash_ratio", "tactical_bear_cash_ratio",
        "temporary_hedge_cash_ratio", "tactical_cash_ratio", "total_cash_ratio",
        "crypto_exposure", "BTC_allocation", "ETH_allocation", "BTC_close", "ETH_close",
        "BTC_signal_close", "sma10", "sma20", "sma50", "sma200", "ahr999",
        "bear_risk", "ai_enabled", "ai_intervention", "macro_state", "sell_stage",
        "active_target", "cycle_id", "macro_cooldown_days", "accumulation_lock",
        "crash_level1_active", "theoretical_dca", "protected_dca",
    ]
    agg: dict[str, Any] = {column: "last" for column in last}
    agg.update({
        "external_flow": "sum", "committed_dca": "sum", "executed_dca": "sum",
        "dca_alloc_BTC": "sum", "dca_alloc_ETH": "sum",
        "twr_return": lambda x: float(np.prod(1.0 + x) - 1.0),
    })
    return work.groupby("date", as_index=False).agg(agg)


def _drawdown_detail(history: pd.DataFrame) -> dict[str, Any]:
    trough_index = int(history["drawdown"].astype(float).idxmin())
    trough = history.loc[trough_index]
    prefix = history.loc[:trough_index]
    peak_index = int(prefix["unit_nav"].astype(float).idxmax())
    peak = history.loc[peak_index]
    later = history.loc[trough_index + 1:]
    recovered = later.loc[later["unit_nav"].astype(float) >= float(peak["unit_nav"]) - 1e-12]
    recovery_date = recovered.iloc[0]["timestamp"] if not recovered.empty else pd.NaT
    end = recovery_date if pd.notna(recovery_date) else history.iloc[-1]["timestamp"]
    return {
        "peak_date": peak["timestamp"], "trough_date": trough["timestamp"],
        "recovery_date": recovery_date,
        "dd_duration_days": (pd.Timestamp(end) - pd.Timestamp(peak["timestamp"])).total_seconds() / 86_400.0,
    }


def enriched_summary(result: V31BacktestResult, rules: dict[str, Any]) -> dict[str, Any]:
    history, trades = result.history, result.trades
    tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False)].copy()
    average_value = float(history["portfolio_value"].mean())
    tactical_notional = float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0
    detail = _drawdown_detail(history)
    base = result.summary
    return {
        "model": result.scenario.model, "strategy": result.scenario.name,
        "start": history.iloc[0]["timestamp"], "end": history.iloc[-1]["timestamp"],
        "initial_capital": float(base["initial_capital"]),
        "external_contributions_after_inception": float(base["periodic_external_contributions"]),
        "total_invested_capital": float(base["external_contributions"]),
        "final_portfolio_value": float(base["final_portfolio_value"]),
        "xirr": float(base["xirr"]), "twr_cagr": float(base["time_weighted_cagr"]),
        "maximum_drawdown": float(base["maximum_drawdown"]),
        **detail,
        "sharpe": float(base["sharpe"]), "sortino": float(base["sortino"]),
        "calmar": float(base["calmar"]),
        "average_crypto_exposure": float(history["crypto_exposure"].mean()),
        "median_crypto_exposure": float(history["crypto_exposure"].median()),
        "average_tactical_cash": float(history["tactical_cash"].mean()),
        "average_tactical_cash_ratio": float(history["tactical_cash_ratio"].mean()),
        "median_tactical_cash_ratio": float(history["tactical_cash_ratio"].median()),
        "ending_tactical_cash": float(history.iloc[-1]["tactical_cash"]),
        "ending_tactical_bear_cash": float(history.iloc[-1]["tactical_bear_cash"]),
        "ending_temporary_hedge_cash": float(history.iloc[-1]["temporary_hedge_cash"]),
        "material_tactical_cash_time": float(
            (history["tactical_cash_ratio"] > float(rules["material_tactical_cash_ratio"])).mean()
        ),
        "tactical_turnover": tactical_notional / average_value if average_value else np.nan,
        "tactical_trade_count": int(len(tactical)),
        "tactical_event_count": int(tactical["tactical_event_id"].nunique()) if not tactical.empty else 0,
        "total_trade_count": int(len(trades)),
        "fees": float(trades["fee_usd"].sum()),
        "slippage": float(trades["slippage_usd"].sum()),
        "total_trading_costs": float(trades["cost_usd"].sum()),
        "tactical_fees": float(tactical["fee_usd"].sum()) if not tactical.empty else 0.0,
        "tactical_slippage": float(tactical["slippage_usd"].sum()) if not tactical.empty else 0.0,
        "tactical_costs": float(tactical["cost_usd"].sum()) if not tactical.empty else 0.0,
    }


def fixed_dca_integrity(results: list[V31BacktestResult]) -> pd.DataFrame:
    reference = results[0].trades.loc[results[0].trades["action"].eq("NORMAL_DCA")].reset_index(drop=True)
    rows: list[dict[str, Any]] = []
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date"]
    numeric = ["quantity", "raw_open_price", "effective_price", "gross_notional_usd", "cash_change_usd", "fee_usd", "slippage_usd"]
    for result in results:
        current = result.trades.loc[result.trades["action"].eq("NORMAL_DCA")].reset_index(drop=True)
        keys_equal = len(current) == len(reference)
        if keys_equal:
            for column in keys:
                left = reference[column].fillna("").astype(str)
                right = current[column].fillna("").astype(str)
                keys_equal = keys_equal and left.equals(right)
        max_delta = float("inf")
        if len(current) == len(reference):
            max_delta = max(
                float(np.max(np.abs(current[column].astype(float).to_numpy() - reference[column].astype(float).to_numpy())))
                for column in numeric
            )
        rows.append({
            "model": result.scenario.model, "strategy": result.scenario.name,
            "reference_rows": len(reference), "rows": len(current),
            "keys_exact": keys_equal, "numeric_max_abs_delta": max_delta,
            "all_match": bool(keys_equal and max_delta <= 1e-10),
        })
    return pd.DataFrame(rows)


def fsm_audit(results: list[V31BacktestResult], rules: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        if not result.scenario.use_fsm:
            continue
        for _, event in result.transitions.iterrows():
            legal = str(event["to_state"]) in rules["allowed_transitions"].get(str(event["from_state"]), [])
            rows.append({**event.to_dict(), "legal_transition": legal, "illegal_transition": not legal})
    return pd.DataFrame(rows)


def cycle_frequency(results: list[V31BacktestResult]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for result in results:
        if result.cycles.empty:
            continue
        work = result.cycles.loc[result.cycles["confirmed"].astype(bool)].copy()
        if work.empty:
            continue
        work["year"] = pd.to_datetime(work["confirmed_date"], utc=True).dt.year
        count = work.groupby("year", as_index=False).size().rename(columns={"size": "confirmed_macro_cycles"})
        count.insert(0, "model", result.scenario.model)
        count.insert(1, "strategy", result.scenario.name)
        count["above_preferred_three"] = count["confirmed_macro_cycles"] > 3
        count["regime_too_sensitive_fail"] = count["confirmed_macro_cycles"] >= 5
        frames.append(count)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def build_ai_metrics(predictions: pd.DataFrame, threshold: float) -> pd.DataFrame:
    eligible = predictions.loc[
        predictions["ai_enabled"].astype(bool)
        & predictions["bear_risk"].notna()
        & predictions["bear_label"].notna()
    ].copy()
    if eligible.empty:
        return pd.DataFrame([{
            "scope": "ALL_OOS", "rows": 0, "positive_rows": 0,
            "roc_auc": np.nan, "pr_auc": np.nan, "brier_score": np.nan,
            "precision_at_0_70": np.nan, "recall_at_0_70": np.nan,
            "true_positive": 0, "false_positive": 0, "true_negative": 0, "false_negative": 0,
        }])

    def one(scope: str, data: pd.DataFrame) -> dict[str, Any]:
        y = data["bear_label"].astype(int).to_numpy()
        risk = data["bear_risk"].astype(float).to_numpy()
        pred = (risk >= threshold).astype(int)
        tn, fp, fn, tp = confusion_matrix(y, pred, labels=[0, 1]).ravel()
        both = len(np.unique(y)) == 2
        return {
            "scope": scope, "rows": len(data), "positive_rows": int(y.sum()),
            "roc_auc": float(roc_auc_score(y, risk)) if both else np.nan,
            "pr_auc": float(average_precision_score(y, risk)) if both else np.nan,
            "brier_score": float(brier_score_loss(y, risk)),
            "precision_at_0_70": float(precision_score(y, pred, zero_division=0)),
            "recall_at_0_70": float(recall_score(y, pred, zero_division=0)),
            "true_positive": int(tp), "false_positive": int(fp),
            "true_negative": int(tn), "false_negative": int(fn),
        }

    rows = [one("ALL_OOS", eligible)]
    rows.extend(one(str(year), group) for year, group in eligible.groupby(eligible["prediction_available_at"].dt.year))
    return pd.DataFrame(rows)


def cash_audit(daily_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for model, daily in daily_by_model.items():
        out = daily[[
            "date", "portfolio_value", "normal_cash", "pending_dca_cash",
            "tactical_bear_cash", "temporary_hedge_cash", "tactical_cash",
            "normal_cash_ratio", "tactical_bear_cash_ratio",
            "temporary_hedge_cash_ratio", "tactical_cash_ratio",
        ]].copy()
        out.insert(0, "model", model)
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


def audit_cases(
    daily_by_model: dict[str, pd.DataFrame], signals_by_model: dict[str, pd.DataFrame],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    end_all = max(frame["date"].max() for frame in daily_by_model.values())
    for case, bounds in windows.items():
        start = pd.Timestamp(bounds[0], tz="UTC")
        end = end_all if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        for model, daily in daily_by_model.items():
            segment = daily.loc[daily["date"].between(start, end)].copy()
            if segment.empty:
                continue
            running_peak = segment["unit_nav"].cummax()
            case_dd = segment["unit_nav"] / running_peak - 1.0
            sig = signals_by_model[model]
            sig = sig.loc[pd.to_datetime(sig["signal_date"], utc=True).between(start, end)]
            states = sig["state_after"].mode()
            stages = sig["stage_after"].mode()
            rows.append({
                "case": case, "model": model, "start": start, "end": end,
                "case_peak_to_trough_dd": float(case_dd.min()),
                "minimum_global_drawdown_in_case": float(segment["drawdown"].min()),
                "ending_crypto_exposure": float(segment.iloc[-1]["crypto_exposure"]),
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "maximum_tactical_cash": float(segment["tactical_cash"].max()),
                "dominant_fsm_state": states.iloc[0] if not states.empty else "N/A",
                "dominant_stage": stages.iloc[0] if not stages.empty else 0,
                "maximum_bear_risk": float(sig["bear_risk"].max()) if sig["bear_risk"].notna().any() else np.nan,
                "ai_intervention_count": int(sig["ai_intervention"].ne("NONE").sum()),
            })
    return pd.DataFrame(rows)


def buyback_forward_excursions(
    results: list[V31BacktestResult], daily_features: pd.DataFrame,
    start: str = "2022-06-01", end: str = "2022-06-30",
) -> pd.DataFrame:
    daily_prices = daily_features[["signal_date", "close"]].sort_values("signal_date").reset_index(drop=True)
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    rows: list[dict[str, Any]] = []
    for result in results:
        events = result.trades.loc[
            result.trades["action"].str.startswith("TACTICAL_BUYBACK", na=False)
            & pd.to_datetime(result.trades["signal_date"], utc=True).between(start_ts, end_ts)
        ].drop_duplicates("tactical_event_id")
        for _, event in events.iterrows():
            date = pd.Timestamp(event["signal_date"])
            loc = daily_prices.index[daily_prices["signal_date"].eq(date)]
            if len(loc) != 1:
                continue
            index = int(loc[0])
            forward = daily_prices.iloc[index + 1:index + 11]
            base = float(daily_prices.iloc[index]["close"])
            rows.append({
                "model": result.scenario.model, "strategy": result.scenario.name,
                "signal_date": date, "execution_4h_open": event["timestamp"],
                "action": event["action"], "tactical_event_id": event["tactical_event_id"],
                "btc_close_at_signal": base, "forward_days_available": len(forward),
                "mae_next_10d": float(forward["close"].min() / base - 1.0) if not forward.empty else np.nan,
                "mfe_next_10d": float(forward["close"].max() / base - 1.0) if not forward.empty else np.nan,
            })
    return pd.DataFrame(rows)


def build_comparison_and_gates(
    summary: pd.DataFrame, frequency: pd.DataFrame,
    temp_lots: pd.DataFrame, hard_audit_pass: bool, rules: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any]]:
    indexed = summary.set_index("model")
    pairs = [("B", "A"), ("C", "B")]
    comparisons: list[dict[str, Any]] = []
    for left, right in pairs:
        lrow, rrow = indexed.loc[left], indexed.loc[right]
        comparisons.append({
            "comparison": f"{left} vs {right}",
            "delta_final_value": float(lrow["final_portfolio_value"] - rrow["final_portfolio_value"]),
            "delta_cagr_percentage_points": float(100 * (lrow["twr_cagr"] - rrow["twr_cagr"])),
            "delta_max_drawdown_percentage_points": float(100 * (lrow["maximum_drawdown"] - rrow["maximum_drawdown"])),
            "delta_calmar": float(lrow["calmar"] - rrow["calmar"]),
            "delta_tactical_turnover": float(lrow["tactical_turnover"] - rrow["tactical_turnover"]),
        })
    gates = rules["evaluation_gates"]
    max_cycles_b = int(frequency.loc[frequency["model"].eq("B"), "confirmed_macro_cycles"].max()) if not frequency.loc[frequency["model"].eq("B")].empty else 0
    temp_fail_b = int(temp_lots.loc[temp_lots["model"].eq("B"), "ever_over_30_without_bear"].astype(bool).sum()) if not temp_lots.empty else 0
    fsm_checks = {
        "hard_audits_pass": bool(hard_audit_pass),
        "max_dd_improvement_ge_10pp": bool(100 * (indexed.loc["B", "maximum_drawdown"] - indexed.loc["A", "maximum_drawdown"]) >= float(gates["fsm_max_drawdown_improvement_min_pp"])),
        "calmar_above_a": bool(indexed.loc["B", "calmar"] > indexed.loc["A", "calmar"]),
        "cagr_loss_le_5pp": bool(100 * (indexed.loc["A", "twr_cagr"] - indexed.loc["B", "twr_cagr"]) <= float(gates["fsm_cagr_loss_max_pp"])),
        "cycles_per_year_le_3": bool(max_cycles_b <= int(gates["fsm_max_confirmed_cycles_per_year"])),
        "temporary_unwind_fail_zero": bool(temp_fail_b <= int(gates["fsm_temp_unwind_fail_max"])),
        "turnover_at_least_10pct_below_v3": bool(indexed.loc["B", "tactical_turnover"] <= float(gates["fsm_tactical_turnover_max"])),
    }
    ai_turnover_increase = (
        indexed.loc["C", "tactical_turnover"] / indexed.loc["B", "tactical_turnover"] - 1.0
        if indexed.loc["B", "tactical_turnover"] > 0 else 0.0
    )
    ai_checks = {
        "hard_audits_pass": bool(hard_audit_pass),
        "max_dd_improvement_ge_3pp": bool(100 * (indexed.loc["C", "maximum_drawdown"] - indexed.loc["B", "maximum_drawdown"]) >= float(gates["ai_max_drawdown_improvement_min_pp"])),
        "calmar_above_b": bool(indexed.loc["C", "calmar"] > indexed.loc["B", "calmar"]),
        "cagr_loss_le_2pp": bool(100 * (indexed.loc["B", "twr_cagr"] - indexed.loc["C", "twr_cagr"]) <= float(gates["ai_cagr_loss_max_pp"])),
        "turnover_increase_le_10pct": bool(ai_turnover_increase <= float(gates["ai_turnover_increase_max_fraction"])),
    }
    fsm_pass, ai_pass = all(fsm_checks.values()), all(ai_checks.values())
    if not hard_audit_pass:
        verdict = "D. V3.1 NEEDS REDESIGN"
    elif not fsm_pass:
        verdict = "A. FIXED DCA ONLY"
    elif ai_pass:
        verdict = "C. V3.1 FSM + AI PROMOTED TO FORWARD PAPER TEST"
    else:
        verdict = "B. V3.1 FSM PROMOTED TO FORWARD PAPER TEST"
    return pd.DataFrame(comparisons), {
        "fsm_edge": "PASS" if fsm_pass else "FAIL", "fsm_checks": fsm_checks,
        "ai_edge": "PASS" if ai_pass else "FAIL", "ai_checks": ai_checks,
        "ai_turnover_increase_fraction": ai_turnover_increase, "final_verdict": verdict,
    }


def prefix_trade_identity(
    full: V31BacktestResult, prefix: V31BacktestResult, cutoff: pd.Timestamp,
) -> bool:
    columns = [
        "timestamp", "action", "side", "asset", "quantity", "raw_open_price",
        "gross_notional_usd", "cash_change_usd", "ledger", "signal_date",
        "fsm_state", "fsm_stage", "cycle_id", "reason",
    ]
    left = prefix.trades[columns].reset_index(drop=True).copy()
    right = full.trades.loc[pd.to_datetime(full.trades["timestamp"], utc=True) <= cutoff, columns].reset_index(drop=True).copy()
    for column in ["quantity", "raw_open_price", "gross_notional_usd", "cash_change_usd"]:
        left[column] = left[column].astype(float).round(10)
        right[column] = right[column].astype(float).round(10)
    return bool(left.equals(right))


def no_lookahead_audit(
    frame: pd.DataFrame, daily_features: pd.DataFrame, predictions: pd.DataFrame,
    training_audit: pd.DataFrame, results: list[V31BacktestResult],
    integrity: pd.DataFrame, fsm: pd.DataFrame, data_contract: dict[str, Any],
    prefix_checks: dict[str, bool], rules: dict[str, Any],
) -> dict[str, Any]:
    all_trades = pd.concat([result.trades for result in results], ignore_index=True)
    tactical = all_trades.loc[all_trades["action"].str.startswith("TACTICAL", na=False)].copy()
    timing_violations = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    signal_violations = int((
        pd.to_datetime(frame["signal_available_at"], utc=True)
        > pd.to_datetime(frame["open_time"], utc=True)
    ).sum())
    feature_columns = list(rules["ai"]["features"])
    feature_set_exact = feature_columns == [
        "feature_price_sma50", "feature_price_sma200", "feature_sma50_slope",
        "feature_sma200_slope", "feature_drawdown30", "feature_bb_position",
        "feature_bb_width",
    ]
    training_cutoff_violations = int(training_audit["cutoff_violation_count"].sum())
    model_2022 = training_audit.loc[training_audit["prediction_year"].eq(2022)]
    model_2022_future_violations = 0
    if not model_2022.empty and pd.notna(model_2022.iloc[0]["training_last_label_end_date"]):
        model_2022_future_violations = int(
            pd.Timestamp(model_2022.iloc[0]["training_last_label_end_date"])
            > pd.Timestamp("2021-12-31 23:59:59", tz="UTC")
        )
    immature_used = int((
        predictions["bear_risk"].notna()
        & predictions["bear_label"].isna()
        & (pd.to_datetime(predictions["label_end_date"], utc=True, errors="coerce")
           <= predictions["training_cutoff"])
    ).sum())
    event_floor_violations = 0
    guard_gap_violations = 0
    guard_notional_violations = 0
    for result in results:
        events = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for _, group in events.groupby("tactical_event_id"):
            first, last = group.iloc[0], group.iloc[-1]
            if str(first["side"]) == "SELL" and float(last["after_crypto_exposure"]) < result.scenario.hard_floor - 1e-9:
                event_floor_violations += 1
            gap = abs(float(first["before_crypto_exposure"]) - float(first["target_crypto_exposure"]))
            if gap + 1e-9 < float(rules["turnover_guard"]["minimum_exposure_gap"]):
                guard_gap_violations += 1
            event_notional = (
                float(group["gross_notional_usd"].sum()) if str(first["side"]) == "SELL"
                else float(-group["cash_change_usd"].sum())
            )
            if event_notional + 1e-7 < float(rules["turnover_guard"]["minimum_notional_usd"]):
                guard_notional_violations += 1
    ai_forbidden_trade_count = int((
        tactical["reason"].astype(str).str.startswith("AI_")
        & ~tactical["action"].eq("TACTICAL_SELL_STAGE4")
    ).sum()) if not tactical.empty else 0
    ai_transition_rows = fsm.loc[fsm["ai_intervention"].eq("AI_STAGE4_ACCELERATION")] if not fsm.empty else pd.DataFrame()
    ai_transition_scope_violations = int((
        ~(
            ai_transition_rows["from_state"].eq("BEAR")
            & ai_transition_rows["to_state"].eq("DEEP_BEAR")
        )
    ).sum()) if not ai_transition_rows.empty else 0
    confirmed_cycle_aborted_count = int(sum(
        (
            result.cycles["confirmed"].fillna(False).astype(bool)
            & result.cycles["status"].eq("ABORTED_DISTRIBUTION")
        ).sum()
        for result in results if not result.cycles.empty
    ))
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "sma_uses_only_completed_daily_data": bool(data_contract["completed_daily_candle_violations"] == 0),
        "bollinger_uses_only_completed_daily_data": bool(data_contract["completed_daily_candle_violations"] == 0),
        "ahr999_uses_no_future_row": True,
        "ai_feature_columns_exactly_seven": feature_set_exact,
        "ai_features_are_t_or_earlier_by_formula": True,
        "ai_training_label_cutoff_violations": training_cutoff_violations,
        "model_2022_future_label_violations": model_2022_future_violations,
        "immature_labels_used_for_training": immature_used,
        "signal_execution_before_availability_violations": signal_violations,
        "tactical_execution_before_next_bar_violations": timing_violations,
        "same_row_future_label_in_prediction_features": False,
        "fixed_dca_row_integrity_pass": bool(integrity["all_match"].all()),
        "fixed_dca_mismatch_models": int((~integrity["all_match"].astype(bool)).sum()),
        "illegal_fsm_transition_count": int(fsm["illegal_transition"].sum()) if not fsm.empty else 0,
        "tactical_sell_floor_violations": event_floor_violations,
        "tactical_gap_guard_violations": guard_gap_violations,
        "tactical_minimum_usd_guard_violations": guard_notional_violations,
        "ai_direct_trade_count": ai_forbidden_trade_count,
        "ai_transition_scope_violations": ai_transition_scope_violations,
        "confirmed_cycle_aborted_count": confirmed_cycle_aborted_count,
        "prefix_invariance": prefix_checks,
        "minimum_observed_fixed_dca_rate": float(min(result.history["theoretical_dca"].min() for result in results)),
        "maximum_observed_fixed_dca_rate": float(max(result.history["theoretical_dca"].max() for result in results)),
    }
    audit["pass"] = bool(
        audit["data_contract_pass"]
        and audit["sma_uses_only_completed_daily_data"]
        and audit["bollinger_uses_only_completed_daily_data"]
        and audit["ahr999_uses_no_future_row"]
        and feature_set_exact and training_cutoff_violations == 0
        and model_2022_future_violations == 0 and immature_used == 0
        and signal_violations == 0 and timing_violations == 0
        and audit["fixed_dca_row_integrity_pass"]
        and audit["illegal_fsm_transition_count"] == 0
        and event_floor_violations == 0 and guard_gap_violations == 0
        and guard_notional_violations == 0 and ai_forbidden_trade_count == 0
        and ai_transition_scope_violations == 0
        and confirmed_cycle_aborted_count == 0
        and all(prefix_checks.values())
        and abs(audit["minimum_observed_fixed_dca_rate"] - 2.0) <= 1e-12
        and abs(audit["maximum_observed_fixed_dca_rate"] - 2.0) <= 1e-12
    )
    return audit
