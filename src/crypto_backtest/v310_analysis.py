from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import daily_history_v31, enriched_summary, fixed_dca_integrity
from .v39_analysis import period_stats


def daily_history_v310(result: Any, model: str) -> pd.DataFrame:
    daily = daily_history_v31(result.history)
    if model == "Q":
        extra = result.history.copy()
        extra["date"] = pd.to_datetime(extra["timestamp"], utc=True).dt.floor("D")
        columns = [
            "stage3_confirmation_eligible", "stage3_candidate_active",
            "stage3_candidate_id", "stage3_confirmation_count",
            "sma200_failure_streak", "causal_parent_stage3_candidate_id",
        ]
        extra = extra.groupby("date", as_index=False)[columns].last()
        daily = daily.merge(extra, on="date", how="left", validate="one_to_one")
    elif model == "P39":
        extra = result.history.copy()
        extra["date"] = pd.to_datetime(extra["timestamp"], utc=True).dt.floor("D")
        source = [
            "bull_persistence_active", "bear_reentry_candidate_active",
            "bear_reentry_confirmation_count", "sma200_failure_streak",
        ]
        extra = extra.groupby("date", as_index=False)[source].last().rename(columns={
            "bull_persistence_active": "stage3_confirmation_eligible",
            "bear_reentry_candidate_active": "stage3_candidate_active",
            "bear_reentry_confirmation_count": "stage3_confirmation_count",
        })
        extra["stage3_candidate_id"] = ""
        extra["causal_parent_stage3_candidate_id"] = ""
        daily = daily.merge(extra, on="date", how="left", validate="one_to_one")
    else:
        daily["stage3_confirmation_eligible"] = False
        daily["stage3_candidate_active"] = False
        daily["stage3_candidate_id"] = ""
        daily["stage3_confirmation_count"] = 0
        daily["sma200_failure_streak"] = 0
        daily["causal_parent_stage3_candidate_id"] = ""
    daily.insert(0, "model", model)
    daily.insert(1, "strategy", result.scenario.name)
    return daily


def build_summary(
    results: dict[str, Any], rules: dict[str, Any], windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model, result in results.items():
        row = enriched_summary(result, rules)
        row["model"] = model
        daily = daily_history_v310(result, model)
        bull = period_stats(daily, *windows["BULL_PARTICIPATION"])
        row.update({
            "bull_2023_2025_average_crypto_exposure": bull["average_crypto_exposure"],
            "bull_2023_2025_median_crypto_exposure": bull["median_crypto_exposure"],
            "bull_2023_2025_time_exposure_gte_70": bull["time_exposure_gte_70"],
            "bull_2023_2025_time_exposure_gte_80": bull["time_exposure_gte_80"],
            "bull_2023_2025_time_exposure_gte_85": bull["time_exposure_gte_85"],
            "bull_2023_2025_time_exposure_gte_90": bull["time_exposure_gte_90"],
            "bull_2023_2025_average_tactical_cash_ratio": bull["average_tactical_cash_ratio"],
            "candidate_count": int(result.counters.get("stage3_candidate_count", 0)),
            "candidate_rejected": int(result.counters.get("stage3_candidate_rejected_count", 0)),
            "candidate_confirmed": int(result.counters.get("stage3_candidate_confirmed_count", 0)),
            "candidate_hard_failure": int(result.counters.get("stage3_candidate_hard_failure_count", 0)),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def fixed_dca_audit(results: dict[str, Any]) -> pd.DataFrame:
    audit = fixed_dca_integrity(list(results.values()))
    audit["model"] = audit["model"].replace({"P": "P39"})
    return audit


def build_event_drawdown_audit(
    daily: dict[str, pd.DataFrame], windows: dict[str, list[str]],
) -> pd.DataFrame:
    selected = ["COVID", "MAY_2021", "NOV_2021_JUN_2022", "CORRECTION_2025_2026"]
    rows: list[dict[str, Any]] = []
    for event in selected:
        for model in ("B", "P39", "Q"):
            rows.append({"event": event, "model": model, **period_stats(daily[model], *windows[event])})
    out = pd.DataFrame(rows)
    pivot = out.pivot(index="event", columns="model", values="maximum_drawdown")
    out["q_minus_b_drawdown_pp"] = out["event"].map(
        (100.0 * (pivot["Q"] - pivot["B"])).to_dict()
    )
    out["p39_minus_b_drawdown_pp"] = out["event"].map(
        (100.0 * (pivot["P39"] - pivot["B"])).to_dict()
    )
    return out


def _signal_actions(signals: pd.DataFrame, model: str) -> pd.DataFrame:
    out = signals[["signal_date", "actions"]].copy()
    out["date"] = pd.to_datetime(out["signal_date"], utc=True).dt.floor("D")
    out = out.groupby("date", as_index=False)["actions"].agg(
        lambda values: "|".join(values.fillna("").astype(str))
    )
    return out.rename(columns={"actions": f"{model}_actions"})


def build_stage_window_detail(
    daily: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame], start: str, end: str,
) -> pd.DataFrame:
    columns = [
        "date", "BTC_signal_close", "sma20", "sma50", "sma200",
        "macro_state", "sell_stage", "crypto_exposure", "portfolio_value",
    ]
    output: pd.DataFrame | None = None
    for model in ("B", "P39", "Q"):
        keep = daily[model][columns].copy().rename(columns={
            column: f"{model}_{column}" for column in columns if column != "date"
        })
        output = keep if output is None else output.merge(keep, on="date", how="inner", validate="one_to_one")
        output = output.merge(_signal_actions(signals[model], model), on="date", how="left", validate="one_to_one")
    assert output is not None
    date = pd.to_datetime(output["date"], utc=True)
    return output.loc[date.between(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))].copy()


def stage4_integrity(trades: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in ("B", "P39", "Q"):
        selected = trades[model].loc[
            trades[model]["action"].eq("TACTICAL_SELL_STAGE4")
            & pd.to_datetime(trades[model]["timestamp"], utc=True).between(
                pd.Timestamp("2025-11-01", tz="UTC"),
                pd.Timestamp("2025-11-30 23:59:59", tz="UTC"),
            )
        ]
        for timestamp, group in selected.groupby("timestamp"):
            rows.append({
                "model": model,
                "signal_date": group["signal_date"].iloc[0],
                "execution_date": timestamp,
                "exposure_before": float(group["before_crypto_exposure"].iloc[0]),
                "exposure_after": float(group["after_crypto_exposure"].iloc[-1]),
                "gross_notional_usd": float(group["gross_notional_usd"].sum()),
                "assets": "|".join(group["asset"].astype(str)),
                "reason": "|".join(group["reason"].astype(str).unique()),
            })
    return pd.DataFrame(rows)


def crash_integrity(signals: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    p = signals["P39"].set_index("execution_4h_open")
    q = signals["Q"].set_index("execution_4h_open")
    for _, row in signals["B"].iterrows():
        actions = str(row.get("actions", ""))
        for level in ("CRASH_L1", "CRASH_L2"):
            if f"{level}:" not in actions:
                continue
            timestamp = pd.Timestamp(row["execution_4h_open"])
            p_actions = str(p.loc[timestamp, "actions"]) if timestamp in p.index else ""
            q_actions = str(q.loc[timestamp, "actions"]) if timestamp in q.index else ""
            rows.append({
                "execution_4h_open": timestamp,
                "level": level,
                "v31_action": actions,
                "v39_action": p_actions,
                "v310_action": q_actions,
                "p39_not_suppressed": f"{level}:" in p_actions,
                "q_not_suppressed": f"{level}:" in q_actions,
            })
    return pd.DataFrame(rows)


def _core_actions(value: Any) -> str:
    ignored_prefixes = (
        "STAGE3_ELIGIBILITY_", "STAGE3_REENTRY_CANDIDATE:",
        "STAGE3_HELD_FOR_3_CLOSE_CONFIRMATION", "STAGE3_REENTRY_CONFIRMED",
    )
    return "|".join(
        item for item in str(value or "").split("|")
        if item and not item.startswith(ignored_prefixes)
    )


def stage3_scope_integrity(
    signals_b: pd.DataFrame, signals_q: pd.DataFrame, candidates: pd.DataFrame,
) -> pd.DataFrame:
    columns = [
        "execution_4h_open", "signal_date", "state_before", "state_after",
        "stage_before", "stage_after", "active_target_before", "active_target_after",
        "crypto_exposure_before", "crypto_exposure_after", "actions",
    ]
    b = signals_b[columns].rename(columns={column: f"B_{column}" for column in columns if column != "execution_4h_open"})
    qcols = columns + ["direct_difference_candidate_id", "causal_parent_stage3_candidate_id"]
    q = signals_q[qcols].rename(columns={column: f"Q_{column}" for column in qcols if column != "execution_4h_open"})
    out = b.merge(q, on="execution_4h_open", how="outer", validate="one_to_one")
    out["B_core_actions"] = out["B_actions"].map(_core_actions)
    out["Q_core_actions"] = out["Q_actions"].map(_core_actions)
    string_cols = ["state_before", "state_after", "stage_before", "stage_after"]
    numeric_cols = ["active_target_before", "active_target_after", "crypto_exposure_before", "crypto_exposure_after"]
    different = pd.Series(False, index=out.index)
    for column in string_cols:
        different |= out[f"B_{column}"].fillna("").astype(str).ne(out[f"Q_{column}"].fillna("").astype(str))
    for column in numeric_cols:
        different |= ~np.isclose(
            pd.to_numeric(out[f"B_{column}"], errors="coerce"),
            pd.to_numeric(out[f"Q_{column}"], errors="coerce"),
            rtol=0.0, atol=1e-10, equal_nan=True,
        )
    different |= out["B_core_actions"].ne(out["Q_core_actions"])
    out["has_economic_or_state_difference"] = different

    candidate_exec = {}
    if not candidates.empty:
        candidate_exec = {
            pd.Timestamp(row["candidate_execution_date"]): int(row["candidate_id"])
            for _, row in candidates.iterrows()
        }
    ordered_candidates = sorted(candidate_exec.items())

    classifications: list[str] = []
    parents: list[Any] = []
    for _, row in out.iterrows():
        if not bool(row["has_economic_or_state_difference"]):
            classifications.append("SAME")
            parents.append("")
            continue
        timestamp = pd.Timestamp(row["execution_4h_open"])
        if timestamp in candidate_exec and "STAGE3_SELL:" in str(row["B_actions"]):
            classifications.append("DIRECT_STAGE3_DELAY")
            parents.append(candidate_exec[timestamp])
            continue
        eligible = [item for item in ordered_candidates if item[0] <= timestamp]
        if eligible:
            classifications.append("INDIRECT_PATH_DIFFERENCE")
            parents.append(eligible[-1][1])
        else:
            classifications.append("UNEXPECTED_DIFFERENCE")
            parents.append("")
    out["classification"] = classifications
    out["causal_parent_stage3_candidate_id"] = parents
    return out


def causal_lineage_audit(
    trades_b: pd.DataFrame, trades_q: pd.DataFrame, candidates: pd.DataFrame,
) -> pd.DataFrame:
    keys = ["timestamp", "action", "side", "asset"]
    measures = ["quantity", "gross_notional_usd", "cash_change_usd", "cost_usd"]

    def grouped(frame: pd.DataFrame, prefix: str) -> pd.DataFrame:
        out = frame.groupby(keys, dropna=False, as_index=False)[measures].sum()
        return out.rename(columns={column: f"{prefix}_{column}" for column in measures})

    out = grouped(trades_b, "B").merge(grouped(trades_q, "Q"), on=keys, how="outer")
    for column in [f"{prefix}_{measure}" for prefix in ("B", "Q") for measure in measures]:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0.0)
    different = pd.Series(False, index=out.index)
    for measure in measures:
        different |= ~np.isclose(out[f"B_{measure}"], out[f"Q_{measure}"], rtol=0.0, atol=1e-8)
    out = out.loc[different].copy().sort_values(keys).reset_index(drop=True)

    ordered = [] if candidates.empty else sorted(
        (pd.Timestamp(row["candidate_execution_date"]), int(row["candidate_id"]))
        for _, row in candidates.iterrows()
    )
    classifications: list[str] = []
    parents: list[Any] = []
    for _, row in out.iterrows():
        timestamp = pd.Timestamp(row["timestamp"])
        exact = [candidate_id for date, candidate_id in ordered if date == timestamp]
        if exact and str(row["action"]) == "TACTICAL_SELL_STAGE3":
            classifications.append("DIRECT_STAGE3_DELAY")
            parents.append(exact[-1])
            continue
        prior = [candidate_id for date, candidate_id in ordered if date <= timestamp]
        if prior:
            classifications.append("INDIRECT_PATH_DIFFERENCE")
            parents.append(prior[-1])
        else:
            classifications.append("UNEXPLAINED_PATH_DIFFERENCE")
            parents.append("")
    out["classification"] = classifications
    out["causal_parent_stage3_candidate_id"] = parents
    return out


def bearish_rebreak_scope_audit(signals_b: pd.DataFrame, signals_q: pd.DataFrame) -> pd.DataFrame:
    b = signals_b[["execution_4h_open", "signal_date", "actions"]].rename(columns={"actions": "B_actions"})
    q = signals_q[["execution_4h_open", "actions"]].rename(columns={"actions": "Q_actions"})
    out = b.merge(q, on="execution_4h_open", how="inner")
    mask = out["B_actions"].str.contains("BEARISH_REBREAK", na=False) | out["Q_actions"].str.contains("BEARISH_REBREAK", na=False)
    out = out.loc[mask].copy()
    out["same_day_presence"] = out.apply(
        lambda row: ("BEARISH_REBREAK" in str(row["B_actions"])) == ("BEARISH_REBREAK" in str(row["Q_actions"])), axis=1,
    )
    out["unexpected_delay"] = ~out["same_day_presence"]
    if out.empty:
        return pd.DataFrame([{
            "execution_4h_open": pd.NaT, "signal_date": pd.NaT,
            "B_actions": "NO_BEARISH_REBREAK_EVENTS", "Q_actions": "NO_BEARISH_REBREAK_EVENTS",
            "same_day_presence": True, "unexpected_delay": False,
        }])
    return out


def _first_on_or_after(daily: pd.DataFrame, date: pd.Timestamp, column: str) -> float:
    dates = pd.to_datetime(daily["date"], utc=True)
    selected = daily.loc[dates >= date, column]
    return float(selected.iloc[0]) if not selected.empty else np.nan


def _local_drawdown(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    dates = pd.to_datetime(daily["date"], utc=True)
    selected = daily.loc[dates.between(start, end), "unit_nav"].astype(float)
    if selected.empty:
        return np.nan
    local = selected / float(selected.iloc[0])
    return float((local / local.cummax() - 1.0).min())


def candidate_economic_audit(
    candidates: pd.DataFrame, daily_b: pd.DataFrame, daily_q: pd.DataFrame,
) -> pd.DataFrame:
    if candidates.empty:
        columns = [
            "candidate_id", "candidate_date", "B_stage3_execution_date",
            "Q_stage3_execution_date", "status", "delay_days",
            "incremental_exposure_days", "B_portfolio_value_30d",
            "Q_portfolio_value_30d", "B_portfolio_value_60d",
            "Q_portfolio_value_60d", "B_local_dd", "Q_local_dd",
        ]
        return pd.DataFrame(columns=columns)
    rows: list[dict[str, Any]] = []
    b_dates = pd.to_datetime(daily_b["date"], utc=True)
    q_dates = pd.to_datetime(daily_q["date"], utc=True)
    for _, item in candidates.iterrows():
        start = pd.Timestamp(item["candidate_date"])
        resolution = pd.Timestamp(item["resolution_date"])
        mask_b = b_dates.between(start, resolution)
        mask_q = q_dates.between(start, resolution)
        b_exposure = daily_b.loc[mask_b, ["date", "crypto_exposure"]]
        q_exposure = daily_q.loc[mask_q, ["date", "crypto_exposure"]]
        exposure = b_exposure.merge(q_exposure, on="date", suffixes=("_B", "_Q"))
        end60 = start + pd.Timedelta(days=60)
        rows.append({
            **item.to_dict(),
            "Q_stage3_execution_date": item.get("final_reentry_date", pd.NaT),
            "status": item.get("confirmed_or_rejected", ""),
            "delay_days": item.get("days_delayed_vs_v31", np.nan),
            "incremental_exposure_days": float(
                (exposure["crypto_exposure_Q"] - exposure["crypto_exposure_B"]).sum()
            ),
            "B_portfolio_value_30d": _first_on_or_after(daily_b, start + pd.Timedelta(days=30), "portfolio_value"),
            "Q_portfolio_value_30d": _first_on_or_after(daily_q, start + pd.Timedelta(days=30), "portfolio_value"),
            "B_portfolio_value_60d": _first_on_or_after(daily_b, end60, "portfolio_value"),
            "Q_portfolio_value_60d": _first_on_or_after(daily_q, end60, "portfolio_value"),
            "B_local_dd": _local_drawdown(daily_b, start, end60),
            "Q_local_dd": _local_drawdown(daily_q, start, end60),
        })
    return pd.DataFrame(rows)


def promotion_evaluation(
    summary: pd.DataFrame,
    event_audit: pd.DataFrame,
    rolling: pd.DataFrame,
    stage4: pd.DataFrame,
    crash: pd.DataFrame,
    integrity: dict[str, bool],
    gates: dict[str, Any],
) -> dict[str, Any]:
    index = summary.set_index("model")
    b, p, q = index.loc["B"], index.loc["P39"], index.loc["Q"]
    events = event_audit.pivot(index="event", columns="model", values="maximum_drawdown")
    v39_uplift = float(p["final_portfolio_value"] - b["final_portfolio_value"])
    q_uplift = float(q["final_portfolio_value"] - b["final_portfolio_value"])
    capture = q_uplift / v39_uplift if abs(v39_uplift) > 1e-12 else np.nan
    rolling_ratios = rolling["Q_final_portfolio_value"] / rolling["B_final_portfolio_value"] - 1.0
    checks = {
        "G0_INTEGRITY_ALL_PASS": bool(all(integrity.values())),
        "G1_Q_FINAL_ABOVE_B": float(q["final_portfolio_value"]) > float(b["final_portfolio_value"]),
        "G2_UPLIFT_CAPTURE_GTE_75PCT": capture >= float(gates["G2_v39_uplift_capture_min"]),
        "G3_TWR_CAGR_GTE_48_4PCT": float(q["twr_cagr"]) >= float(gates["G3_twr_cagr_min"]),
        "G4_OVERALL_DD_WORSEN_LTE_0_5PP": float(q["maximum_drawdown"]) >= (
            float(b["maximum_drawdown"]) - float(gates["G4_overall_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G5_2022_BEAR_DD_WORSEN_LTE_1PP": float(events.loc["NOV_2021_JUN_2022", "Q"]) >= (
            float(events.loc["NOV_2021_JUN_2022", "B"]) - float(gates["G5_2022_bear_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G6_2025_2026_DD_WORSEN_LTE_1PP": float(events.loc["CORRECTION_2025_2026", "Q"]) >= (
            float(events.loc["CORRECTION_2025_2026", "B"]) - float(gates["G6_2025_2026_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G7_STAGE4_AND_CRASH_INTEGRITY": bool(
            set(stage4["model"]) >= {"B", "P39", "Q"}
            and not crash.empty and crash["q_not_suppressed"].all()
        ),
        "G8_CALMAR_NOT_BELOW_B": float(q["calmar"]) >= float(b["calmar"]),
        "G9_TURNOVER_INCREASE_LTE_5PCT": float(q["tactical_turnover"]) <= (
            float(b["tactical_turnover"]) * (1.0 + float(gates["G9_turnover_increase_max_fraction"]))
        ),
        "G10_ROLLING_START_ROBUSTNESS": bool(
            int((rolling["Q_final_portfolio_value"] > rolling["B_final_portfolio_value"]).sum())
            >= int(gates["G10_rolling_q_final_above_b_min_starts"])
            and float(rolling_ratios.min()) >= -float(gates["G10_rolling_any_start_underperformance_max_fraction"])
        ),
        "COVID_DD_WORSEN_LTE_0_5PP": float(events.loc["COVID", "Q"]) >= (
            float(events.loc["COVID", "B"]) - float(gates["covid_drawdown_worsening_max_pp"]) / 100.0
        ),
        "MAY_2021_DD_WORSEN_LTE_0_5PP": float(events.loc["MAY_2021", "Q"]) >= (
            float(events.loc["MAY_2021", "B"]) - float(gates["may_2021_drawdown_worsening_max_pp"]) / 100.0
        ),
    }
    safety_keys = [
        "G4_OVERALL_DD_WORSEN_LTE_0_5PP", "G5_2022_BEAR_DD_WORSEN_LTE_1PP",
        "G6_2025_2026_DD_WORSEN_LTE_1PP", "G7_STAGE4_AND_CRASH_INTEGRITY",
        "COVID_DD_WORSEN_LTE_0_5PP", "MAY_2021_DD_WORSEN_LTE_0_5PP",
    ]
    edge_keys = [
        "G1_Q_FINAL_ABOVE_B", "G2_UPLIFT_CAPTURE_GTE_75PCT",
        "G3_TWR_CAGR_GTE_48_4PCT", "G8_CALMAR_NOT_BELOW_B",
        "G10_ROLLING_START_ROBUSTNESS",
    ]
    if not checks["G0_INTEGRITY_ALL_PASS"]:
        verdict = "C. V3.10 INVALID — SCOPE CONTAMINATION"
    elif not all(checks[key] for key in safety_keys):
        verdict = "E. V3.10 REJECTED — BEAR PROTECTION DEGRADED"
    elif not all(checks[key] for key in edge_keys):
        verdict = "D. V3.10 REJECTED — V3.9 EDGE NOT REPRODUCED"
    elif not checks["G9_TURNOVER_INCREASE_LTE_5PCT"]:
        verdict = "B. V3.1 REMAINS CHAMPION"
    else:
        verdict = "A. V3.10 STAGE3 CONFIRMATION PROMOTED"
    return {
        "verdict": verdict,
        "all_gates_pass": bool(all(checks.values())),
        "checks": {key: bool(value) for key, value in checks.items()},
        "v39_return_uplift_usd": v39_uplift,
        "v310_return_uplift_usd": q_uplift,
        "uplift_capture_ratio": float(capture),
        "precise_75pct_final_value_threshold_usd": float(
            b["final_portfolio_value"] + float(gates["G2_v39_uplift_capture_min"]) * v39_uplift
        ),
    }


__all__ = [
    "bearish_rebreak_scope_audit", "build_event_drawdown_audit", "build_stage_window_detail",
    "build_summary", "candidate_economic_audit", "causal_lineage_audit", "crash_integrity",
    "daily_history_v310", "fixed_dca_audit", "promotion_evaluation", "stage3_scope_integrity",
    "stage4_integrity",
]
