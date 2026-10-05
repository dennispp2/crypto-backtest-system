from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import prefix_trade_identity
from .v31_engine import V31BacktestResult
from .v33_analysis import fixed_dca_integrity, v31_replay_integrity
from .v34_analysis import (
    crash_false_positive_audit,
    crash_level3_audit,
    daily_history_v34,
    macro_bull_requalification_audit,
    summary_v34,
)


BOTTOM_BUY_ACTIONS_B = {
    "TACTICAL_BUYBACK_AHR999_TO_35",
    "TACTICAL_BUYBACK_RIGHT_TO_50",
    "TACTICAL_BUYBACK_RIGHT_TO_60",
}
BOTTOM_BUY_ACTIONS_G = {
    "TACTICAL_BUYBACK_PATCH_D_VALUE_BASE_35",
    "TACTICAL_BUYBACK_PATCH_D_RIGHT_50",
    "TACTICAL_BUYBACK_PATCH_D_RIGHT_60",
}


def _models(results: list[V31BacktestResult]) -> dict[str, V31BacktestResult]:
    return {result.scenario.model: result for result in results}


def fsm_audit_v35(results: list[V31BacktestResult], base_rules: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    patch_from = {"BEAR", "DEEP_BEAR", "ACCUMULATION"}
    for result in results:
        if not result.scenario.use_fsm:
            continue
        for _, event in result.transitions.iterrows():
            normal = str(event["to_state"]) in base_rules["allowed_transitions"].get(
                str(event["from_state"]), []
            )
            v34 = bool(
                result.scenario.model in {"F", "G"}
                and event["from_state"] in patch_from
                and event["to_state"] == "NEW_BULL"
                and event["reason"] == "MACRO_BULL_REQUALIFICATION_NEW_BULL"
            )
            rows.append({
                "model": result.scenario.model,
                **event.to_dict(),
                "v31_legal_transition": normal,
                "v34_patch_authorized_transition": v34,
                "patch_d_authorized_transition": bool(
                    result.scenario.model == "G"
                    and event["from_state"] == "DEEP_BEAR"
                    and event["to_state"] == "ACCUMULATION"
                    and event["reason"] == "PATCH_D_VALUE_BASE_ACCUMULATION"
                ),
            })
    out = pd.DataFrame(rows)
    if not out.empty:
        out["legal_transition"] = out[
            ["v31_legal_transition", "v34_patch_authorized_transition", "patch_d_authorized_transition"]
        ].any(axis=1)
    return out


def churn_audit_v35(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.scenario.model not in {"B", "G"}:
            continue
        transitions = result.transitions.copy()
        for from_state, to_state in (("BEAR", "DEEP_BEAR"), ("DEEP_BEAR", "BEAR")):
            rows.append({
                "model": result.scenario.model,
                "record_type": "transition_count",
                "state": f"{from_state}->{to_state}",
                "count": int(((transitions["from_state"] == from_state) & (transitions["to_state"] == to_state)).sum()),
            })
    return pd.DataFrame(rows)


def _bounds(bounds: list[str], cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(bounds[0], tz="UTC")
    end = cutoff if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
    return start, end


def event_window_audit_v35(
    daily_by_model: dict[str, pd.DataFrame],
    results: list[V31BacktestResult],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    result_map = _models(results)
    cutoff = max(pd.Timestamp(daily_by_model[model]["date"].max()) for model in ("B", "G"))
    for event, bounds in windows.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "G"):
            daily = daily_by_model[model]
            segment = daily.loc[daily["date"].between(start, end)].copy()
            if segment.empty:
                continue
            local_dd = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            trough_pos = int(np.argmin(local_dd.to_numpy()))
            trough = segment.iloc[trough_pos]
            peak = segment.iloc[int(np.argmax(segment.iloc[:trough_pos + 1]["unit_nav"].to_numpy()))]
            later = segment.iloc[trough_pos + 1:]
            recovered = later.loc[later["unit_nav"] >= float(peak["unit_nav"]) - 1e-12]
            trades = result_map[model].trades
            dates = pd.to_datetime(trades["signal_date"], utc=True, errors="coerce")
            tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False) & dates.between(start, end)]
            rows.append({
                "event": event,
                "model": model,
                "start": start,
                "end": end,
                "peak_to_trough_dd": float(local_dd.min()),
                "peak_date": peak["date"],
                "trough_date": trough["date"],
                "recovery_date": recovered.iloc[0]["date"] if not recovered.empty else pd.NaT,
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "average_crypto_exposure": float(segment["crypto_exposure"].mean()),
                "time_exposure_gte_85": float((segment["crypto_exposure"] >= 0.85).mean()),
                "average_tactical_cash_ratio": float(segment["tactical_cash_ratio"].mean()),
                "tactical_trade_notional": float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0,
            })
    return pd.DataFrame(rows)


def _bottom_scope(trades: pd.DataFrame, model: str) -> pd.Series:
    action = trades["action"].fillna("")
    reason = trades["reason"].fillna("")
    if model == "B":
        return action.isin(BOTTOM_BUY_ACTIONS_B) | reason.eq("ACCUMULATION_BEARISH_REBREAK") | (
            action.eq("TACTICAL_SELL_DRIFT") & trades["fsm_state"].eq("ACCUMULATION")
        )
    return action.isin(BOTTOM_BUY_ACTIONS_G) | action.str.startswith(
        "TACTICAL_SELL_PATCH_D_HARD_FAILURE", na=False
    ) | (action.eq("TACTICAL_SELL_DRIFT") & trades["fsm_state"].eq("ACCUMULATION"))


def bottom_action_audit(
    results: list[V31BacktestResult],
    daily_by_model: dict[str, pd.DataFrame],
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, Any]] = []
    result_map = _models(results)
    for model in ("B", "G"):
        result = result_map[model]
        trades = result.trades.loc[_bottom_scope(result.trades, model)].copy()
        if trades.empty:
            continue
        trades["timestamp"] = pd.to_datetime(trades["timestamp"], utc=True)
        trades["signal_date"] = pd.to_datetime(trades["signal_date"], utc=True)
        group_cols = ["tactical_event_id", "timestamp", "signal_date", "action", "side", "reason", "cycle_id"]
        events = trades.groupby(group_cols, dropna=False, as_index=False).agg(
            gross_notional_usd=("gross_notional_usd", "sum"),
            exposure_before=("before_crypto_exposure", "first"),
            exposure_after=("after_crypto_exposure", "last"),
        ).sort_values("timestamp")
        signals = result.signals.copy()
        signals["signal_date"] = pd.to_datetime(signals["signal_date"], utc=True)
        signal_map = signals.drop_duplicates("signal_date", keep="last").set_index("signal_date")
        previous_time: pd.Timestamp | None = None
        previous_side: str | None = None
        for event in events.itertuples():
            signal = signal_map.loc[event.signal_date] if event.signal_date in signal_map.index else pd.Series(dtype=object)
            days = (event.timestamp - previous_time).total_seconds() / 86400.0 if previous_time is not None else np.nan
            pair = bool(previous_side is not None and previous_side != event.side and days <= 14.0 + 1e-12)
            cooldown_before = bool(pd.notna(days) and days < 14.0 - 1e-12)
            rows.append({
                "model": model,
                "timestamp": event.timestamp,
                "signal_date": event.signal_date,
                "cycle_id": event.cycle_id,
                "accumulation_episode_id": signal.get("accumulation_episode_id", np.nan),
                "action": event.action,
                "side": event.side,
                "reason": event.reason,
                "exposure_before": event.exposure_before,
                "exposure_after": event.exposure_after,
                "days_since_previous_tactical_action": days,
                "whipsaw_pair_with_previous": pair,
                "ahr999": signal.get("ahr999", np.nan),
                "btc_close": signal.get("btc_close", np.nan),
                "sma20": signal.get("sma20", np.nan),
                "sma50": signal.get("sma50", np.nan),
                "sma200": signal.get("sma200", np.nan),
                "new_20d_low": signal.get("new_20d_low", np.nan),
                "cooldown_active": cooldown_before,
                "hard_failure_confirmed": signal.get("patch_d_hard_failure_confirmed", False),
                "crash_level3_active": bool("CRASH_L3:" in str(signal.get("actions", ""))),
                "gross_notional": event.gross_notional_usd,
                "gross_notional_usd": event.gross_notional_usd,
            })
            previous_time, previous_side = event.timestamp, event.side
    audit = pd.DataFrame(rows)
    summary_rows: list[dict[str, Any]] = []
    cutoff = max(pd.Timestamp(daily_by_model[model]["date"].max()) for model in ("B", "G"))
    periods = {"FULL": ["2020-01-01", "end"], **rules["audit_windows"]}
    for period, bounds in periods.items():
        start, end = _bounds(bounds, cutoff)
        for model in ("B", "G"):
            segment = audit.loc[
                audit["model"].eq(model) & pd.to_datetime(audit["signal_date"], utc=True).between(start, end)
            ] if not audit.empty else audit
            daily = daily_by_model[model]
            daily_segment = daily.loc[daily["date"].between(start, end)]
            notional = float(segment["gross_notional_usd"].sum()) if not segment.empty else 0.0
            average_value = float(daily_segment["portfolio_value"].mean()) if not daily_segment.empty else np.nan
            if not segment.empty:
                ordered = segment.sort_values("timestamp")
                within_days = pd.to_datetime(ordered["timestamp"], utc=True).diff().dt.total_seconds().div(86400)
                within_pairs = (
                    ordered["side"].ne(ordered["side"].shift())
                    & within_days.le(14.0 + 1e-12)
                )
            else:
                within_days = pd.Series(dtype=float)
                within_pairs = pd.Series(dtype=bool)
            summary_rows.append({
                "period": period,
                "model": model,
                "start": start,
                "end": end,
                "bottom_tactical_event_count": len(segment),
                "bottom_tactical_notional_usd": notional,
                "bottom_turnover": notional / average_value if average_value and pd.notna(average_value) else np.nan,
                "whipsaw_pair_count": int(within_pairs.sum()),
                "average_days_between_actions": float(within_days.dropna().mean()) if len(within_days.dropna()) else np.nan,
            })
    return audit, pd.DataFrame(summary_rows)


def cash_reset_audit_v35(result_g: V31BacktestResult) -> pd.DataFrame:
    if result_g.cycles.empty:
        return pd.DataFrame()
    columns = [
        "cycle_id", "start", "end", "status", "new_bull_date", "bull_date",
        "final_cash_sweep_date", "final_cash_sweep_spent", "cash_reset_audit",
        "cash_reset_reason", "tactical_bear_cash_ratio_at_close", "cycle_closed",
    ]
    out = result_g.cycles[[column for column in columns if column in result_g.cycles.columns]].copy()
    out.insert(0, "model", "G")
    return out


def bull_participation_audit_v35(
    results: list[V31BacktestResult], daily_by_model: dict[str, pd.DataFrame], horizons=(10, 20)
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in ("B", "G"):
        result = _models(results)[model]
        daily = daily_by_model[model].sort_values("date")
        for event in result.transitions.loc[result.transitions["to_state"].eq("NEW_BULL")].itertuples():
            date = pd.Timestamp(event.signal_date)
            after = daily.loc[daily["date"] >= date].reset_index(drop=True)
            row = {"model": model, "cycle_id": int(event.cycle_id), "new_bull_date": date, "new_bull_path": event.reason}
            for horizon in horizons:
                row[f"exposure_{horizon}d"] = float(after.iloc[horizon]["crypto_exposure"]) if len(after) > horizon else np.nan
            row["gate_10d_85_pass"] = bool(pd.notna(row["exposure_10d"]) and row["exposure_10d"] >= 0.85)
            row["gate_20d_90_pass"] = bool(pd.notna(row["exposure_20d"]) and row["exposure_20d"] >= 0.90)
            rows.append(row)
    return pd.DataFrame(rows)


def _event_metric(events: pd.DataFrame, event: str, model: str, column="peak_to_trough_dd") -> float:
    row = events.loc[events["event"].eq(event) & events["model"].eq(model)]
    return float(row.iloc[0][column]) if not row.empty else np.nan


def _reduction(bottom_summary: pd.DataFrame, period: str, column: str) -> float:
    indexed = bottom_summary.loc[bottom_summary["period"].eq(period)].set_index("model")
    base = float(indexed.loc["B", column])
    challenger = float(indexed.loc["G", column])
    if base == 0:
        return 1.0 if challenger == 0 else -np.inf
    return 1.0 - challenger / base


def comparison_and_promotion_v35(
    summary: pd.DataFrame,
    events: pd.DataFrame,
    bottom_summary: pd.DataFrame,
    participation: pd.DataFrame,
    cash_reset: pd.DataFrame,
    rules: dict[str, Any],
    v34_rules: dict[str, Any],
    *,
    no_lookahead_pass: bool,
    execution_pass: bool,
    replay_pass: bool,
    fixed_dca_pass: bool,
    fsm_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    indexed = summary.set_index("model")
    b, g = indexed.loc["B"], indexed.loc["G"]
    bottom_pair_reduction = _reduction(bottom_summary, "FULL", "whipsaw_pair_count")
    bottom_2022_reduction = _reduction(bottom_summary, "2022_BOTTOM", "bottom_tactical_event_count")
    bottom_2026_reduction = _reduction(bottom_summary, "2026_BOTTOM", "bottom_tactical_event_count")
    dd_2022_regression = 100 * (
        _event_metric(events, "2021_NOV_TO_2022_JUN", "B")
        - _event_metric(events, "2021_NOV_TO_2022_JUN", "G")
    )
    dd_2025_regression = 100 * (
        _event_metric(events, "2025_TO_CUTOFF", "B")
        - _event_metric(events, "2025_TO_CUTOFF", "G")
    )
    comparison = pd.DataFrame([{
        "comparison": "G V3.5 Patch D vs B V3.1",
        "delta_final_value": float(g["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": 100 * float(g["twr_cagr"] - b["twr_cagr"]),
        "delta_max_drawdown_percentage_points": 100 * float(g["maximum_drawdown"] - b["maximum_drawdown"]),
        "delta_calmar": float(g["calmar"] - b["calmar"]),
        "delta_tactical_turnover": float(g["tactical_turnover"] - b["tactical_turnover"]),
        "bottom_whipsaw_pair_reduction_fraction": bottom_pair_reduction,
        "bottom_2022_trade_count_reduction_fraction": bottom_2022_reduction,
        "bottom_2026_trade_count_reduction_fraction": bottom_2026_reduction,
        "normal_bear_regression_percentage_points": dd_2022_regression,
        "2025_to_cutoff_dd_regression_percentage_points": dd_2025_regression,
    }])
    patch_gates = rules["evaluation_gates"]
    patch_checks = {
        "bottom_whipsaw_pair_reduction_gte_50pct": bool(bottom_pair_reduction >= patch_gates["bottom_whipsaw_pair_reduction_minimum_fraction"]),
        "2022_bottom_trade_reduction_gte_50pct": bool(bottom_2022_reduction >= patch_gates["2022_bottom_trade_count_reduction_minimum_fraction"]),
        "2026_bottom_trade_reduction_gte_50pct": bool(bottom_2026_reduction >= patch_gates["2026_bottom_trade_count_reduction_minimum_fraction"]),
        "turnover_lte_v31_b": bool(g["tactical_turnover"] <= patch_gates["overall_tactical_turnover_maximum_vs_v31"] + 1e-12),
        "2021nov_2022jun_dd_regression_lte_2pp": bool(dd_2022_regression <= patch_gates["2021nov_2022jun_dd_regression_maximum_percentage_points"]),
        "2025_to_cutoff_dd_regression_lte_2pp": bool(dd_2025_regression <= patch_gates["2025_to_cutoff_dd_regression_maximum_percentage_points"]),
        "final_value_gte_95pct_v31_b": bool(g["final_portfolio_value"] >= patch_gates["final_value_minimum_fraction_of_v31_b"] * b["final_portfolio_value"]),
    }
    base_gates = v34_rules["promotion_gates"]
    g_part = participation.loc[participation["model"].eq("G")]
    completed_cash = cash_reset.loc[cash_reset["status"].eq("COMPLETED_NEW_BULL")]
    cash_pass = bool(not completed_cash.empty and completed_cash["cash_reset_audit"].eq("PASS").all())
    core_checks = {
        "maximum_drawdown_gte_minus_0_30": bool(g["maximum_drawdown"] >= base_gates["maximum_drawdown_minimum"]),
        "twr_cagr_gte_0_45": bool(g["twr_cagr"] >= base_gates["twr_cagr_minimum"]),
        "calmar_gte_1_50": bool(g["calmar"] >= base_gates["calmar_minimum"]),
        "bull_participation_pass": bool(not g_part.empty and g_part["gate_10d_85_pass"].all() and g_part["gate_20d_90_pass"].all()),
        "cash_reset_pass": cash_pass,
        "no_lookahead_pass": bool(no_lookahead_pass),
        "execution_integrity_pass": bool(execution_pass and replay_pass and fixed_dca_pass),
        "fsm_audit_pass": bool(fsm_pass),
    }
    all_checks = {**patch_checks, **core_checks}
    hard_integrity = all([no_lookahead_pass, execution_pass, replay_pass, fixed_dca_pass, fsm_pass])
    promoted = all(all_checks.values())
    verdict = (
        "A. V3.5 PATCH D PROMOTED TO FORWARD PAPER TEST"
        if promoted else "B. V3.1 REMAINS CHAMPION" if hard_integrity else "C. V3.5 NEEDS REDESIGN"
    )
    return comparison, {
        "promotion_gate": "PASS" if promoted else "FAIL",
        "patch_d_gate": "PASS" if all(patch_checks.values()) else "FAIL",
        "patch_d_checks": patch_checks,
        "v3_4_core_checks": core_checks,
        "final_verdict": verdict,
    }


def build_no_lookahead_audit_v35(
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
    result_map = _models(results)
    g = result_map["G"]
    h0 = result_map["H0"]
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    timing = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    sells = tactical.loc[tactical["side"].eq("SELL"), "after_crypto_exposure"]
    patch_trades = g.trades.loc[_bottom_scope(g.trades, "G")].copy()
    if not patch_trades.empty:
        event_rows = patch_trades.groupby("tactical_event_id", as_index=False).agg(
            timestamp=("timestamp", "first"), action=("action", "first"),
            before=("before_crypto_exposure", "first"), after=("after_crypto_exposure", "last"),
        ).sort_values("timestamp")
        event_rows["timestamp"] = pd.to_datetime(event_rows["timestamp"], utc=True)
        gaps = event_rows["timestamp"].diff().dt.total_seconds().div(86400)
        cooldown_violations = int((gaps.dropna() < 14.0 - 1e-12).sum())
        ladder = np.array([0.25, 0.35, 0.50, 0.60])
        executed_dates = set(pd.to_datetime(patch_trades["signal_date"], utc=True))
        signal_events = g.signals.loc[
            pd.to_datetime(g.signals["signal_date"], utc=True).isin(executed_dates)
            & g.signals["actions"].str.contains("PATCH_D_", na=False)
        ]
        rung_violations = 0
        for row in signal_events.itertuples():
            before_i = int(np.argmin(np.abs(ladder - float(row.active_target_before))))
            after_i = int(np.argmin(np.abs(ladder - float(row.active_target_after))))
            if abs(after_i - before_i) > 1:
                rung_violations += 1
    else:
        cooldown_violations = 0
        rung_violations = 0
    forbidden_dates = ("2022-06-01", "2026-02-01")
    future_tokens = ("shift(-", "future_min_return", "bear_label", "label_end_date")
    evaluation_tokens = ("evaluation_gates", "bottom_whipsaw_pair_reduction", "final_value_minimum_fraction")
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "completed_daily_candle_violations": int(data_contract["completed_daily_candle_violations"]),
        "signal_availability_violations": int(data_contract["signal_availability_violations"]),
        "future_columns_in_execution_frame": data_contract["future_columns_in_execution_frame"],
        "tactical_execution_before_next_bar_violations": timing,
        "fixed_dca_row_integrity_pass": bool(fixed_dca["all_match"].all()),
        "v3_1_replay_integrity_pass": bool(replay["pass"]),
        "illegal_fsm_transition_count": int((~fsm["legal_transition"].astype(bool)).sum()) if not fsm.empty else 0,
        "tactical_sell_floor_violations": int((sells < 0.20 - 1e-9).sum()),
        "patch_d_cooldown_violations": cooldown_violations,
        "patch_d_multi_rung_violations": rung_violations,
        "audit_dates_absent_from_trading_engine": bool(not any(token in engine_source for token in forbidden_dates)),
        "evaluation_gate_terms_absent_from_trading_engine": bool(not any(token in engine_source for token in evaluation_tokens)),
        "future_reference_tokens_absent_from_indicator_source": bool(not any(token in indicator_source for token in future_tokens)),
        "h0_external_contributions_zero": bool(abs(float(h0.history["external_flow"].sum())) <= 1e-12),
        "h0_post_initial_trade_count_zero": bool(len(h0.trades.loc[~h0.trades["action"].eq("INITIAL_ALLOCATION")]) == 0),
        "prefix_invariance": prefix_checks,
        "formal_execution_frame_rows": len(frame),
        "daily_feature_rows": len(daily_features),
    }
    audit["no_lookahead_pass"] = bool(
        audit["data_contract_pass"]
        and audit["completed_daily_candle_violations"] == 0
        and audit["signal_availability_violations"] == 0
        and not audit["future_columns_in_execution_frame"]
        and timing == 0
        and audit["future_reference_tokens_absent_from_indicator_source"]
        and all(prefix_checks.values())
    )
    audit["execution_integrity_pass"] = bool(
        audit["fixed_dca_row_integrity_pass"]
        and audit["v3_1_replay_integrity_pass"]
        and audit["illegal_fsm_transition_count"] == 0
        and audit["tactical_sell_floor_violations"] == 0
        and audit["patch_d_cooldown_violations"] == 0
        and audit["patch_d_multi_rung_violations"] == 0
        and audit["audit_dates_absent_from_trading_engine"]
        and audit["evaluation_gate_terms_absent_from_trading_engine"]
        and audit["h0_external_contributions_zero"]
        and audit["h0_post_initial_trade_count_zero"]
        and all(prefix_checks.values())
    )
    audit["combined_hard_integrity_pass"] = bool(audit["no_lookahead_pass"] and audit["execution_integrity_pass"])
    audit["pass"] = audit["no_lookahead_pass"]
    return audit


def v34_replay_integrity(
    result_f: V31BacktestResult, v34_dir: Path, primary_rules: dict[str, Any]
) -> dict[str, Any]:
    reference_summary = pd.read_csv(v34_dir / "results" / "summary_v3_4.csv")
    ref = reference_summary.loc[reference_summary["model"].eq("F")].iloc[0]
    current = summary_v34(result_f, primary_rules)
    headline = {
        "final_portfolio_value": float(current["final_portfolio_value"]),
        "twr_cagr": float(current["twr_cagr"]),
        "maximum_drawdown": float(current["maximum_drawdown"]),
        "calmar": float(current["calmar"]),
    }
    diffs = {key: abs(value - float(ref[key])) for key, value in headline.items()}
    return {"headline_absolute_differences": diffs, "pass": bool(max(diffs.values()) <= 1e-9)}


__all__ = [
    "daily_history_v34", "summary_v34", "fixed_dca_integrity", "v31_replay_integrity",
    "prefix_trade_identity", "fsm_audit_v35", "churn_audit_v35", "event_window_audit_v35",
    "bottom_action_audit", "cash_reset_audit_v35", "bull_participation_audit_v35",
    "comparison_and_promotion_v35", "build_no_lookahead_audit_v35", "v34_replay_integrity",
    "crash_level3_audit", "crash_false_positive_audit", "macro_bull_requalification_audit",
]
