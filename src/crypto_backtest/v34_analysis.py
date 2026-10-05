from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import _drawdown_detail, enriched_summary, prefix_trade_identity
from .v31_engine import V31BacktestResult
from .v33_analysis import fixed_dca_integrity, v31_replay_integrity


def daily_history_v34(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    sum_columns = {
        "external_flow", "committed_dca", "executed_dca", "dca_alloc_BTC", "dca_alloc_ETH"
    }
    agg: dict[str, Any] = {}
    for column in work.columns:
        if column in {"timestamp", "date"}:
            continue
        if column in sum_columns:
            agg[column] = "sum"
        elif column == "twr_return":
            agg[column] = lambda x: float(np.prod(1.0 + x.astype(float)) - 1.0)
        else:
            agg[column] = "last"
    return work.groupby("date", as_index=False).agg(agg)


def summary_v34(result: V31BacktestResult, rules: dict[str, Any]) -> dict[str, Any]:
    row = enriched_summary(result, rules)
    row["total_capital_supplied"] = row["total_invested_capital"]
    row["net_profit"] = row["final_portfolio_value"] - row["total_capital_supplied"]
    row["median_tactical_cash"] = float(result.history["tactical_cash"].median())
    row["confirmed_cycle_count"] = int(
        result.cycles.get("confirmed", pd.Series(dtype=bool)).fillna(False).astype(bool).sum()
    ) if not result.cycles.empty else 0
    if not result.cycles.empty:
        start = pd.to_datetime(result.cycles["start"], utc=True)
        end = pd.to_datetime(result.cycles["end"], utc=True)
        row["longest_cycle_duration_days"] = float((end - start).dt.total_seconds().div(86400).max())
    else:
        row["longest_cycle_duration_days"] = 0.0
    row["crash_level3_count"] = int(result.counters.get("crash_level3_count", 0))
    row["macro_bull_requalification_count"] = int(
        result.counters.get("macro_bull_requalification_count", 0)
    )
    row["final_cash_sweep_count"] = int(result.counters.get("final_cash_sweep_count", 0))
    return row


def fsm_audit_v34(results: list[V31BacktestResult], base_rules: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    patch_from = {"BEAR", "DEEP_BEAR", "ACCUMULATION"}
    for result in results:
        if not result.scenario.use_fsm:
            continue
        for _, event in result.transitions.iterrows():
            normal = str(event["to_state"]) in base_rules["allowed_transitions"].get(
                str(event["from_state"]), []
            )
            patch = bool(
                result.scenario.model == "F"
                and event["from_state"] in patch_from
                and event["to_state"] == "NEW_BULL"
                and event["reason"] == "MACRO_BULL_REQUALIFICATION_NEW_BULL"
            )
            rows.append({
                "model": result.scenario.model,
                **event.to_dict(),
                "v31_legal_transition": normal,
                "v34_patch_authorized_transition": patch,
                "legal_transition": normal or patch,
            })
    return pd.DataFrame(rows)


def churn_audit_v34(results: list[V31BacktestResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        if result.scenario.model not in {"B", "F"}:
            continue
        transitions = result.transitions.copy()
        for from_state, to_state in (("BEAR", "DEEP_BEAR"), ("DEEP_BEAR", "BEAR")):
            count = int(((transitions["from_state"] == from_state) & (transitions["to_state"] == to_state)).sum())
            rows.append({
                "model": result.scenario.model,
                "record_type": "transition_count",
                "state": f"{from_state}->{to_state}",
                "count": count,
                "average_dwell_days": np.nan,
                "median_dwell_days": np.nan,
            })
        signals = result.signals.sort_values("signal_date").copy()
        if signals.empty:
            continue
        signals["signal_date"] = pd.to_datetime(signals["signal_date"], utc=True)
        signals["run_id"] = signals["state_after"].ne(signals["state_after"].shift()).cumsum()
        runs = signals.groupby(["run_id", "state_after"], as_index=False).agg(
            start=("signal_date", "min"), end=("signal_date", "max")
        )
        runs["dwell_days"] = (runs["end"] - runs["start"]).dt.total_seconds().div(86400.0) + 1.0
        for state in ("BEAR", "DEEP_BEAR"):
            group = runs.loc[runs["state_after"].eq(state)]
            rows.append({
                "model": result.scenario.model,
                "record_type": "state_dwell",
                "state": state,
                "count": len(group),
                "average_dwell_days": float(group["dwell_days"].mean()) if not group.empty else np.nan,
                "median_dwell_days": float(group["dwell_days"].median()) if not group.empty else np.nan,
            })
    return pd.DataFrame(rows)


def _window_bounds(bounds: list[str], cutoff: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    start = pd.Timestamp(bounds[0], tz="UTC")
    end = cutoff if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
    return start, end


def event_window_audit_v34(
    daily_by_model: dict[str, pd.DataFrame],
    results: list[V31BacktestResult],
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    result_map = {result.scenario.model: result for result in results}
    cutoff = max(pd.Timestamp(frame["date"].max()) for frame in daily_by_model.values())
    for event, bounds in windows.items():
        start, end = _window_bounds(bounds, cutoff)
        for model in ("B", "F"):
            daily = daily_by_model[model]
            segment = daily.loc[daily["date"].between(start, end)].copy()
            if segment.empty:
                continue
            local_dd = segment["unit_nav"] / segment["unit_nav"].cummax() - 1.0
            trough_pos = int(np.argmin(local_dd.to_numpy()))
            trough_row = segment.iloc[trough_pos]
            peak_pos = int(np.argmax(segment.iloc[:trough_pos + 1]["unit_nav"].to_numpy()))
            peak_row = segment.iloc[peak_pos]
            later = segment.iloc[trough_pos + 1:]
            recovered = later.loc[later["unit_nav"] >= float(peak_row["unit_nav"]) - 1e-12]
            trades = result_map[model].trades
            trade_dates = pd.to_datetime(trades["signal_date"], utc=True, errors="coerce")
            tactical = trades.loc[
                trades["action"].str.startswith("TACTICAL", na=False)
                & trade_dates.between(start, end)
            ]
            transitions = result_map[model].transitions
            transition_dates = pd.to_datetime(transitions["signal_date"], utc=True, errors="coerce")
            window_transitions = transitions.loc[transition_dates.between(start, end)]
            rows.append({
                "event": event,
                "model": model,
                "start": start,
                "end": end,
                "peak_to_trough_dd": float(local_dd.min()),
                "peak_date": peak_row["date"],
                "trough_date": trough_row["date"],
                "recovery_date": recovered.iloc[0]["date"] if not recovered.empty else pd.NaT,
                "minimum_crypto_exposure": float(segment["crypto_exposure"].min()),
                "maximum_crypto_exposure": float(segment["crypto_exposure"].max()),
                "average_crypto_exposure": float(segment["crypto_exposure"].mean()),
                "median_crypto_exposure": float(segment["crypto_exposure"].median()),
                "time_exposure_gte_85": float((segment["crypto_exposure"] >= 0.85).mean()),
                "time_exposure_gte_90": float((segment["crypto_exposure"] >= 0.90).mean()),
                "average_tactical_cash_ratio": float(segment["tactical_cash_ratio"].mean()),
                "maximum_tactical_cash_ratio": float(segment["tactical_cash_ratio"].max()),
                "ending_state": str(segment.iloc[-1]["macro_state"]),
                "ending_stage": int(segment.iloc[-1]["sell_stage"]),
                "tactical_trade_notional": float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0,
                "transition_path": "|".join(
                    f"{pd.Timestamp(item.signal_date).date()}:{item.from_state}->{item.to_state}"
                    for item in window_transitions.itertuples()
                ),
            })
    return pd.DataFrame(rows)


def crash_level3_audit(result_f: V31BacktestResult) -> pd.DataFrame:
    signals = result_f.signals.loc[
        result_f.signals["actions"].str.contains(r"(?:^|\|)CRASH_L3:", regex=True, na=False)
    ].copy()
    lots = (
        result_f.temporary_lots.loc[result_f.temporary_lots["source"].eq("CRASH_LEVEL3")].copy()
        if not result_f.temporary_lots.empty and "source" in result_f.temporary_lots
        else pd.DataFrame()
    )
    rows: list[dict[str, Any]] = []
    for signal in signals.itertuples():
        trigger = pd.Timestamp(signal.signal_date)
        matching_lot = lots.loc[
            pd.to_datetime(lots["level3_trigger_date"], utc=True).eq(trigger)
        ] if not lots.empty else lots
        lot = matching_lot.iloc[0] if not matching_lot.empty else None
        trigger_trades = result_f.trades.loc[
            result_f.trades["action"].eq("TEMPORARY_CRASH_SELL_LEVEL3")
            & pd.to_datetime(result_f.trades["signal_date"], utc=True).eq(trigger)
        ]
        action_token = next(
            (token for token in str(signal.actions).split("|") if token.startswith("CRASH_L3:")),
            "CRASH_L3:UNKNOWN",
        )
        rows.append({
            "model": "F",
            "lot_id": int(lot["lot_id"]) if lot is not None else np.nan,
            "crash_episode_id": int(signal.crash_episode_id),
            "level3_trigger_date": trigger,
            "btc_close_at_trigger": float(signal.btc_close),
            "pre_crash_macro_target": float(signal.active_target_after),
            "exposure_before_level3": float(signal.crypto_exposure_before),
            "exposure_after_level3": float(trigger_trades.iloc[-1]["after_crypto_exposure"]) if not trigger_trades.empty else float(signal.crypto_exposure_after),
            "level3_action_outcome": action_token.split(":", 1)[1],
            "crash_cash_original": float(lot["original_proceeds"]) if lot is not None else 0.0,
            "crash_cash_remaining": float(lot["cash_remaining"]) if lot is not None else 0.0,
            "recovery_confirmed_date": lot["recovery_confirmed_date"] if lot is not None else pd.NaT,
            "unwind_completed_date": lot["unwind_completed_date"] if lot is not None else pd.NaT,
            "status": lot["status"] if lot is not None else "NO_SELL_EXPOSURE_ALREADY_AT_OR_BELOW_35",
            "closure_reason": lot["closure_reason"] if lot is not None else "NO_LEVEL3_CASH_CREATED",
        })
    return pd.DataFrame(rows)


def crash_false_positive_audit(
    crash_audit: pd.DataFrame,
    daily_f: pd.DataFrame,
    rules: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    horizon = int(rules["crash_level_3"]["false_positive_horizon_calendar_days"])
    threshold = float(rules["crash_level_3"]["false_positive_continuation_drawdown"])
    for item in crash_audit.itertuples():
        start = pd.Timestamp(item.level3_trigger_date)
        end = start + pd.Timedelta(days=horizon)
        window = daily_f.loc[daily_f["date"].between(start, end)]
        min_close = float(window["BTC_close"].min()) if not window.empty else np.nan
        continued = bool(min_close <= float(item.btc_close_at_trigger) * (1.0 + threshold)) if pd.notna(min_close) else False
        recovery_date = pd.Timestamp(item.recovery_confirmed_date) if pd.notna(item.recovery_confirmed_date) else pd.NaT
        quick_v = bool(pd.notna(recovery_date) and recovery_date <= end)
        rows.append({
            "model": "F",
            "lot_id": item.lot_id,
            "level3_trigger_date": start,
            "audit_end": end,
            "minimum_btc_close": min_close,
            "continued_down_at_least_10pct": continued,
            "quick_v_recovery_confirmed": quick_v,
            "potential_crash_false_positive": bool(not continued and quick_v),
        })
    return pd.DataFrame(rows)


def macro_bull_requalification_audit(
    result_f: V31BacktestResult,
    daily_f: pd.DataFrame,
    rules: dict[str, Any],
) -> pd.DataFrame:
    signals = result_f.signals.copy()
    if signals.empty:
        return pd.DataFrame()
    signals["signal_date"] = pd.to_datetime(signals["signal_date"], utc=True)
    candidates = signals.loc[signals["actions"].str.contains(
        r"(?:^|\|)MACRO_BULL_REQUALIFICATION_CANDIDATE(?:\||$)", regex=True, na=False
    )]
    invalidations = signals.loc[signals["actions"].str.contains("MACRO_BEAR_INVALIDATED_TARGET_70", na=False)]
    new_bulls = result_f.transitions.loc[
        result_f.transitions["reason"].eq("MACRO_BULL_REQUALIFICATION_NEW_BULL")
    ].copy()
    rows: list[dict[str, Any]] = []
    horizon = int(rules["macro_bull_requalification"]["false_positive_horizon_calendar_days"])
    dd_threshold = float(rules["macro_bull_requalification"]["false_positive_drawdown"])
    for candidate in candidates.itertuples():
        candidate_date = pd.Timestamp(candidate.signal_date)
        later_invalid = invalidations.loc[invalidations["signal_date"] >= candidate_date]
        invalid_date = pd.Timestamp(later_invalid.iloc[0]["signal_date"]) if not later_invalid.empty else pd.NaT
        later_nb = new_bulls.loc[
            pd.to_datetime(new_bulls["signal_date"], utc=True) >= candidate_date
        ]
        new_bull_date = pd.Timestamp(later_nb.iloc[0]["signal_date"]) if not later_nb.empty else pd.NaT
        false_end = new_bull_date + pd.Timedelta(days=horizon) if pd.notna(new_bull_date) else pd.NaT
        window = daily_f.loc[daily_f["date"].between(new_bull_date, false_end)] if pd.notna(new_bull_date) else daily_f.iloc[0:0]
        confirm_close = float(window.iloc[0]["BTC_close"]) if not window.empty else np.nan
        below_sma200 = bool((window["BTC_close"] < window["sma200"]).any()) if not window.empty else False
        drawdown_20 = bool(window["BTC_close"].min() <= confirm_close * (1.0 + dd_threshold)) if not window.empty else False
        rows.append({
            "model": "F",
            "candidate_date": candidate_date,
            "macro_bear_invalidated_date": invalid_date,
            "new_bull_confirmed_date": new_bull_date,
            "candidate_to_invalidated_days": (invalid_date - candidate_date).days if pd.notna(invalid_date) else np.nan,
            "invalidated_to_new_bull_days": (new_bull_date - invalid_date).days if pd.notna(new_bull_date) and pd.notna(invalid_date) else np.nan,
            "within_60d_below_sma200": below_sma200,
            "within_60d_drawdown_gte_20pct": drawdown_20,
            "potential_false_bull_requalification": bool(below_sma200 and drawdown_20),
        })
    return pd.DataFrame(rows)


def cycle_duration_audit_v34(
    results: list[V31BacktestResult],
    daily_by_model: dict[str, pd.DataFrame],
    rules: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    long_days = int(rules["diagnostic_guardrails"]["cycle_long_warning_days"])
    extreme_days = int(rules["diagnostic_guardrails"]["cycle_extreme_warning_days"])
    window_days = int(rules["diagnostic_guardrails"]["missed_macro_bull_window_days"])
    min_above = int(rules["diagnostic_guardrails"]["missed_macro_bull_close_count"])
    for result in results:
        if result.scenario.model not in {"B", "F"}:
            continue
        daily = daily_by_model[result.scenario.model].copy()
        above = daily["BTC_close"] > daily["sma200"]
        rolling_count = above.astype(int).rolling(window_days, min_periods=window_days).sum()
        rising_200 = daily["sma200"] > daily["sma200"].shift(window_days - 1)
        macro_bull_market = rolling_count.ge(min_above) & rising_200 & daily["sma50"].gt(daily["sma200"])
        stuck = daily["macro_state"].isin(["BEAR", "DEEP_BEAR"])
        if result.scenario.model == "F":
            requal_absent = ~daily["requal_candidate_active"].fillna(False).astype(bool) & ~daily[
                "macro_bear_invalidated"
            ].fillna(False).astype(bool)
        else:
            requal_absent = pd.Series(True, index=daily.index)
        missed = macro_bull_market & stuck & requal_absent
        for _, cycle in result.cycles.iterrows():
            start = pd.Timestamp(cycle["start"])
            end = pd.Timestamp(cycle["end"])
            duration = (end - start).total_seconds() / 86400.0
            cycle_daily = daily.loc[daily["date"].between(start, end)]
            missed_days = int(missed.loc[cycle_daily.index].sum()) if not cycle_daily.empty else 0
            first_missed = cycle_daily.loc[missed.loc[cycle_daily.index], "date"] if not cycle_daily.empty else pd.Series(dtype="datetime64[ns, UTC]")
            rows.append({
                "model": result.scenario.model,
                "cycle_id": int(cycle["cycle_id"]),
                "start": start,
                "end": end,
                "status": cycle["status"],
                "confirmed": bool(cycle["confirmed"]),
                "duration_days": duration,
                "long_cycle_warning": duration > long_days,
                "extreme_cycle_warning": duration > extreme_days,
                "missed_macro_bull": missed_days > 0,
                "missed_macro_bull_days": missed_days,
                "first_missed_macro_bull_date": first_missed.iloc[0] if not first_missed.empty else pd.NaT,
                "new_bull_date": cycle.get("new_bull_date", pd.NaT),
                "new_bull_path": cycle.get("new_bull_path", ""),
                "cycle_closed": cycle.get("cycle_closed", cycle["status"] != "OPEN_AT_END"),
            })
    return pd.DataFrame(rows)


def cash_reset_audit_v34(result_f: V31BacktestResult) -> pd.DataFrame:
    if result_f.cycles.empty:
        return pd.DataFrame()
    columns = [
        "cycle_id", "start", "end", "status", "new_bull_date", "bull_date",
        "final_cash_sweep_date", "final_cash_sweep_spent", "cash_reset_audit",
        "cash_reset_reason", "tactical_bear_cash_ratio_at_close", "cycle_closed",
    ]
    available = [column for column in columns if column in result_f.cycles.columns]
    out = result_f.cycles[available].copy()
    out.insert(0, "model", "F")
    return out


def bull_participation_audit_v34(
    results: list[V31BacktestResult],
    daily_by_model: dict[str, pd.DataFrame],
    rules: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    result_map = {result.scenario.model: result for result in results}
    horizons = list(rules["diagnostic_guardrails"]["bull_participation_days"])
    for model in ("B", "F"):
        result = result_map[model]
        events = result.transitions.loc[result.transitions["to_state"].eq("NEW_BULL")].copy()
        daily = daily_by_model[model].sort_values("date").reset_index(drop=True)
        trade_dates = pd.to_datetime(result.trades["signal_date"], utc=True, errors="coerce")
        crash_actions = {"TACTICAL_SELL_CRASH_L2", "TEMPORARY_CRASH_SELL_LEVEL3"}
        for event in events.itertuples():
            date = pd.Timestamp(event.signal_date)
            after = daily.loc[daily["date"] >= date].reset_index(drop=True)
            row: dict[str, Any] = {
                "model": model,
                "cycle_id": int(event.cycle_id),
                "new_bull_date": date,
                "new_bull_path": event.reason,
            }
            for horizon in horizons:
                if len(after) > horizon:
                    observation = after.iloc[horizon]
                    observation_date = pd.Timestamp(observation["date"])
                    crash = result.trades.loc[
                        result.trades["action"].isin(crash_actions)
                        & trade_dates.between(date, observation_date)
                    ]
                    row[f"exposure_{horizon}d"] = float(observation["crypto_exposure"])
                    row[f"crash_l2_l3_within_{horizon}d"] = not crash.empty
                else:
                    row[f"exposure_{horizon}d"] = np.nan
                    row[f"crash_l2_l3_within_{horizon}d"] = False
            for threshold in (0.85, 0.90, 0.95):
                hit = after.loc[after["crypto_exposure"] >= threshold - 1e-10]
                tag = int(threshold * 100)
                row[f"first_{tag}_date"] = hit.iloc[0]["date"] if not hit.empty else pd.NaT
                row[f"days_to_{tag}"] = (
                    (pd.Timestamp(hit.iloc[0]["date"]) - date).days if not hit.empty else np.nan
                )
            row["gate_10d_85_pass"] = bool(
                row["crash_l2_l3_within_10d"]
                or (pd.notna(row["exposure_10d"]) and row["exposure_10d"] >= 0.85)
            )
            row["gate_20d_90_pass"] = bool(
                row["crash_l2_l3_within_20d"]
                or (pd.notna(row["exposure_20d"]) and row["exposure_20d"] >= 0.90)
            )
            rows.append(row)
    return pd.DataFrame(rows)


def _metric(events: pd.DataFrame, event: str, model: str, column: str) -> float:
    row = events.loc[events["event"].eq(event) & events["model"].eq(model)]
    return float(row.iloc[0][column]) if not row.empty else np.nan


def comparison_and_promotion_v34(
    summary: pd.DataFrame,
    churn: pd.DataFrame,
    events: pd.DataFrame,
    participation: pd.DataFrame,
    cycle_audit: pd.DataFrame,
    cash_reset: pd.DataFrame,
    rules: dict[str, Any],
    *,
    replay_pass: bool,
    fixed_dca_pass: bool,
    no_lookahead_pass: bool,
    execution_pass: bool,
    fsm_pass: bool,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    indexed = summary.set_index("model")
    b, f = indexed.loc["B"], indexed.loc["F"]
    counts = churn.loc[churn["record_type"].eq("transition_count")].groupby("model")["count"].sum()
    b_churn, f_churn = int(counts.get("B", 0)), int(counts.get("F", 0))
    churn_reduction = 1.0 - f_churn / b_churn if b_churn else np.nan
    bear_b = _metric(events, "2021_NOV_TO_2022_JUN", "B", "peak_to_trough_dd")
    bear_f = _metric(events, "2021_NOV_TO_2022_JUN", "F", "peak_to_trough_dd")
    normal_bear_regression_pp = 100.0 * (bear_b - bear_f)
    bull_b = _metric(events, "2023_TO_2025_BULL", "B", "average_crypto_exposure")
    bull_f = _metric(events, "2023_TO_2025_BULL", "F", "average_crypto_exposure")
    comparison = pd.DataFrame([{
        "comparison": "F V3.4 vs B V3.1",
        "delta_final_value": float(f["final_portfolio_value"] - b["final_portfolio_value"]),
        "delta_cagr_percentage_points": float(100 * (f["twr_cagr"] - b["twr_cagr"])),
        "delta_max_drawdown_percentage_points": float(100 * (f["maximum_drawdown"] - b["maximum_drawdown"])),
        "delta_calmar": float(f["calmar"] - b["calmar"]),
        "delta_material_tactical_cash_time_percentage_points": float(100 * (f["material_tactical_cash_time"] - b["material_tactical_cash_time"])),
        "delta_tactical_turnover": float(f["tactical_turnover"] - b["tactical_turnover"]),
        "delta_covid_dd_percentage_points": 100 * (_metric(events, "2020_COVID", "F", "peak_to_trough_dd") - _metric(events, "2020_COVID", "B", "peak_to_trough_dd")),
        "delta_may_dd_percentage_points": 100 * (_metric(events, "2021_MAY", "F", "peak_to_trough_dd") - _metric(events, "2021_MAY", "B", "peak_to_trough_dd")),
        "delta_2022_bear_dd_percentage_points": 100 * (bear_f - bear_b),
        "delta_2023_2025_average_exposure_percentage_points": 100 * (bull_f - bull_b),
        "delta_2025_2026_correction_dd_percentage_points": 100 * (_metric(events, "2025_TO_CUTOFF", "F", "peak_to_trough_dd") - _metric(events, "2025_TO_CUTOFF", "B", "peak_to_trough_dd")),
        "delta_state_churn_count": f_churn - b_churn,
        "state_churn_reduction_fraction": churn_reduction,
        "delta_longest_cycle_duration_days": float(f["longest_cycle_duration_days"] - b["longest_cycle_duration_days"]),
    }])
    gates = rules["promotion_gates"]
    f_part = participation.loc[participation["model"].eq("F")]
    participation_pass = bool(
        not f_part.empty
        and f_part["gate_10d_85_pass"].all()
        and f_part["gate_20d_90_pass"].all()
    )
    relevant_cash = cash_reset.loc[cash_reset["status"].eq("COMPLETED_NEW_BULL")]
    cash_pass = bool(not relevant_cash.empty and relevant_cash["cash_reset_audit"].eq("PASS").all())
    checks = {
        "maximum_drawdown_gte_minus_0_30": bool(f["maximum_drawdown"] >= float(gates["maximum_drawdown_minimum"])),
        "twr_cagr_gte_0_45": bool(f["twr_cagr"] >= float(gates["twr_cagr_minimum"])),
        "calmar_gte_1_50": bool(f["calmar"] >= float(gates["calmar_minimum"])),
        "final_value_gte_95pct_of_v31_b": bool(f["final_portfolio_value"] >= float(gates["final_value_minimum_fraction_of_v31_b"]) * b["final_portfolio_value"]),
        "normal_bear_regression_lte_2pp": bool(normal_bear_regression_pp <= float(gates["normal_bear_maximum_regression_percentage_points"])),
        "bull_participation_pass": participation_pass,
        "cash_reset_pass": cash_pass,
        "state_churn_reduced_at_least_50pct": bool(pd.notna(churn_reduction) and churn_reduction >= float(gates["state_churn_minimum_reduction_fraction"])),
        "tactical_turnover_lte_9_8361": bool(f["tactical_turnover"] <= float(gates["tactical_turnover_maximum"])),
        "no_lookahead_pass": bool(no_lookahead_pass),
        "execution_integrity_pass": bool(execution_pass and replay_pass and fixed_dca_pass),
        "fsm_audit_pass": bool(fsm_pass),
        "cash_reset_audit_pass": cash_pass,
    }
    hard_integrity = all([replay_pass, fixed_dca_pass, no_lookahead_pass, execution_pass, fsm_pass])
    promoted = all(checks.values())
    verdict = (
        "A. V3.4 PROMOTED TO FORWARD PAPER TEST"
        if promoted
        else "B. V3.1 REMAINS CHAMPION"
        if hard_integrity
        else "C. V3.4 NEEDS REDESIGN"
    )
    return comparison, {
        "promotion_gate": "PASS" if promoted else "FAIL",
        "checks": checks,
        "normal_bear_regression_percentage_points": normal_bear_regression_pp,
        "final_verdict": verdict,
    }


def build_no_lookahead_audit_v34(
    frame: pd.DataFrame,
    daily_features: pd.DataFrame,
    results: list[V31BacktestResult],
    data_contract: dict[str, Any],
    fixed_dca: pd.DataFrame,
    fsm: pd.DataFrame,
    replay: dict[str, Any],
    cash_reset: pd.DataFrame,
    prefix_checks: dict[str, bool],
    engine_source: str,
    indicator_source: str,
) -> dict[str, Any]:
    result_f = next(result for result in results if result.scenario.model == "F")
    h0 = next(result for result in results if result.scenario.model == "H0")
    tactical = pd.concat([
        result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)]
        for result in results if not result.trades.empty
    ], ignore_index=True)
    timing_violations = int((
        pd.to_datetime(tactical["timestamp"], utc=True)
        < pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    ).sum()) if not tactical.empty else 0
    sell_floor = tactical.loc[tactical["side"].eq("SELL"), "after_crypto_exposure"]

    exits = result_f.transitions.loc[
        result_f.transitions["from_state"].eq("DEEP_BEAR")
        & result_f.transitions["to_state"].eq("BEAR")
    ]
    signals = result_f.signals.copy()
    signal_index = signals.set_index(pd.to_datetime(signals["signal_date"], utc=True))
    hysteresis_violations = 0
    for event in exits.itertuples():
        sample = signal_index.loc[pd.Timestamp(event.signal_date)]
        if isinstance(sample, pd.DataFrame):
            sample = sample.iloc[0]
        if int(sample["deep_bear_dwell_days"]) < 10 or not bool(sample["deep_bear_exit_v34_confirmed"]):
            hysteresis_violations += 1

    l3_signals = signals.loc[signals["actions"].str.contains(r"(?:^|\|)CRASH_L3:", regex=True, na=False)]
    l3_rule_violations = int((~l3_signals["crash_level3_price_raw"].fillna(False).astype(bool)).sum())
    l2_proof = (
        l3_signals["crash_level2_active"].fillna(False).astype(bool)
        | l3_signals["actions"].str.contains("CRASH_L2_ACTUAL_RECORDED", regex=False, na=False)
    )
    l3_rule_violations += int((~l2_proof).sum())
    invalidations = signals.loc[signals["actions"].str.contains("MACRO_BEAR_INVALIDATED_TARGET_70", na=False)]
    requal_rule_violations = int((invalidations["requal_candidate_following_days"] < 5).sum())
    alt_new_bull = result_f.transitions.loc[
        result_f.transitions["reason"].eq("MACRO_BULL_REQUALIFICATION_NEW_BULL")
    ]
    for event in alt_new_bull.itertuples():
        sample = signal_index.loc[pd.Timestamp(event.signal_date)]
        if isinstance(sample, pd.DataFrame):
            sample = sample.iloc[0]
        if int(sample["requal_new_bull_following_days"]) < 5:
            requal_rule_violations += 1

    final_sweep = result_f.trades.loc[
        result_f.trades["action"].eq("TACTICAL_BUYBACK_FINAL_CASH_SWEEP")
    ]
    final_sweep_ledger_violations = int((final_sweep["ledger"] != "tactical_bear").sum())
    final_sweep_target_violations = int((final_sweep["after_crypto_exposure"] > 0.95 + 1e-9).sum())
    completed_cash = cash_reset.loc[cash_reset["status"].eq("COMPLETED_NEW_BULL")]
    cash_reset_pass = bool(not completed_cash.empty and completed_cash["cash_reset_audit"].eq("PASS").all())

    promotion_terms = (
        "promotion_gates", "maximum_drawdown_minimum", "twr_cagr_minimum", "calmar_minimum"
    )
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
        "crash_level3_rule_violations": l3_rule_violations,
        "macro_bull_requalification_rule_violations": requal_rule_violations,
        "final_cash_sweep_ledger_violations": final_sweep_ledger_violations,
        "final_cash_sweep_target_violations": final_sweep_target_violations,
        "cash_reset_integrity_pass": cash_reset_pass,
        "h0_external_contributions_zero": bool(abs(float(h0.history["external_flow"].sum())) <= 1e-12),
        "h0_post_initial_trade_count_zero": bool(len(h0.trades.loc[~h0.trades["action"].eq("INITIAL_ALLOCATION")]) == 0),
        "promotion_gate_terms_absent_from_trading_engine": bool(not any(term in engine_source for term in promotion_terms)),
        "v32_trading_logic_absent_from_v34_engine": bool(not any(term in engine_source for term in forbidden_v32)),
        "future_reference_tokens_absent_from_v34_indicator_source": bool(not any(term in indicator_source for term in future_tokens)),
        "prefix_invariance": prefix_checks,
        "formal_execution_frame_rows": len(frame),
        "daily_feature_rows": len(daily_features),
    }
    audit["no_lookahead_pass"] = bool(
        audit["data_contract_pass"]
        and audit["completed_daily_candle_violations"] == 0
        and audit["signal_availability_violations"] == 0
        and not audit["future_columns_in_execution_frame"]
        and audit["tactical_execution_before_next_bar_violations"] == 0
        and audit["future_reference_tokens_absent_from_v34_indicator_source"]
        and all(prefix_checks.values())
    )
    audit["execution_integrity_pass"] = bool(
        audit["fixed_dca_row_integrity_pass"]
        and audit["v3_1_replay_integrity_pass"]
        and audit["illegal_fsm_transition_count"] == 0
        and audit["tactical_sell_floor_violations"] == 0
        and audit["hysteresis_exit_rule_violations"] == 0
        and audit["crash_level3_rule_violations"] == 0
        and audit["macro_bull_requalification_rule_violations"] == 0
        and audit["final_cash_sweep_ledger_violations"] == 0
        and audit["final_cash_sweep_target_violations"] == 0
        and audit["h0_external_contributions_zero"]
        and audit["h0_post_initial_trade_count_zero"]
        and audit["promotion_gate_terms_absent_from_trading_engine"]
        and audit["v32_trading_logic_absent_from_v34_engine"]
        and all(prefix_checks.values())
    )
    audit["combined_hard_integrity_pass"] = bool(
        audit["no_lookahead_pass"]
        and audit["execution_integrity_pass"]
        and audit["cash_reset_integrity_pass"]
    )
    audit["pass"] = audit["no_lookahead_pass"]
    return audit


__all__ = [
    "daily_history_v34",
    "summary_v34",
    "v31_replay_integrity",
    "fixed_dca_integrity",
    "fsm_audit_v34",
    "churn_audit_v34",
    "event_window_audit_v34",
    "crash_level3_audit",
    "crash_false_positive_audit",
    "macro_bull_requalification_audit",
    "cycle_duration_audit_v34",
    "cash_reset_audit_v34",
    "bull_participation_audit_v34",
    "comparison_and_promotion_v34",
    "build_no_lookahead_audit_v34",
    "prefix_trade_identity",
    "_drawdown_detail",
]
