from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .v31_analysis import daily_history_v31, enriched_summary, fixed_dca_integrity


def daily_history_v39(result: Any) -> pd.DataFrame:
    daily = daily_history_v31(result.history)
    if result.scenario.model == "P":
        extra = result.history.copy()
        extra["date"] = pd.to_datetime(extra["timestamp"], utc=True).dt.floor("D")
        columns = [
            "bull_persistence_active", "healthy_bull_structure",
            "bull_persistence_guard", "bear_reentry_candidate_active",
            "bear_reentry_confirmation_count", "sma200_failure_streak",
        ]
        extra = extra.groupby("date", as_index=False)[columns].last()
        daily = daily.merge(extra, on="date", how="left", validate="one_to_one")
    else:
        daily["bull_persistence_active"] = False
        daily["healthy_bull_structure"] = False
        daily["bull_persistence_guard"] = False
        daily["bear_reentry_candidate_active"] = False
        daily["bear_reentry_confirmation_count"] = 0
        daily["sma200_failure_streak"] = 0
    daily.insert(0, "model", result.scenario.model)
    daily.insert(1, "strategy", result.scenario.name)
    return daily


def period_stats(daily: pd.DataFrame, start: str, end: str | None) -> dict[str, Any]:
    dates = pd.to_datetime(daily["date"], utc=True)
    mask = dates >= pd.Timestamp(start, tz="UTC")
    if end and end != "end":
        mask &= dates <= pd.Timestamp(end, tz="UTC")
    work = daily.loc[mask].copy().reset_index(drop=True)
    if work.empty:
        return {
            "observations": 0, "start": pd.NaT, "end": pd.NaT,
            "portfolio_return": np.nan, "portfolio_cagr": np.nan,
            "maximum_drawdown": np.nan, "peak_date": pd.NaT, "trough_date": pd.NaT,
            "average_crypto_exposure": np.nan, "median_crypto_exposure": np.nan,
            "time_exposure_gte_70": np.nan, "time_exposure_gte_80": np.nan,
            "time_exposure_gte_85": np.nan, "time_exposure_gte_90": np.nan,
            "average_tactical_cash_ratio": np.nan,
        }
    local_nav = work["unit_nav"].astype(float) / float(work["unit_nav"].iloc[0])
    local_peak = local_nav.cummax()
    local_dd = local_nav / local_peak - 1.0
    trough_idx = int(local_dd.idxmin())
    peak_idx = int(local_nav.loc[:trough_idx].idxmax())
    elapsed_years = max(
        (pd.Timestamp(work.iloc[-1]["date"]) - pd.Timestamp(work.iloc[0]["date"])).total_seconds()
        / (365.25 * 86_400.0),
        1.0 / 365.25,
    )
    ret = float(local_nav.iloc[-1] - 1.0)
    return {
        "observations": int(len(work)),
        "start": work.iloc[0]["date"], "end": work.iloc[-1]["date"],
        "portfolio_return": ret,
        "portfolio_cagr": float((1.0 + ret) ** (1.0 / elapsed_years) - 1.0),
        "maximum_drawdown": float(local_dd.min()),
        "peak_date": work.loc[peak_idx, "date"],
        "trough_date": work.loc[trough_idx, "date"],
        "average_crypto_exposure": float(work["crypto_exposure"].mean()),
        "median_crypto_exposure": float(work["crypto_exposure"].median()),
        "time_exposure_gte_70": float((work["crypto_exposure"] >= 0.70).mean()),
        "time_exposure_gte_80": float((work["crypto_exposure"] >= 0.80).mean()),
        "time_exposure_gte_85": float((work["crypto_exposure"] >= 0.85).mean()),
        "time_exposure_gte_90": float((work["crypto_exposure"] >= 0.90).mean()),
        "average_tactical_cash_ratio": float(work["tactical_cash_ratio"].mean()),
    }


def build_summary(results: list[Any], rules: dict[str, Any], windows: dict[str, list[str]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        row = enriched_summary(result, rules)
        daily = daily_history_v39(result)
        bull = period_stats(daily, *windows["BULL_PARTICIPATION"])
        row.update({
            "bull_2023_2025_average_crypto_exposure": bull["average_crypto_exposure"],
            "bull_2023_2025_median_crypto_exposure": bull["median_crypto_exposure"],
            "bull_2023_2025_time_exposure_gte_70": bull["time_exposure_gte_70"],
            "bull_2023_2025_time_exposure_gte_80": bull["time_exposure_gte_80"],
            "bull_2023_2025_time_exposure_gte_85": bull["time_exposure_gte_85"],
            "bull_2023_2025_time_exposure_gte_90": bull["time_exposure_gte_90"],
            "bull_2023_2025_average_tactical_cash_ratio": bull["average_tactical_cash_ratio"],
            "bull_2023_2025_portfolio_cagr": bull["portfolio_cagr"],
            "bull_2023_2025_maximum_drawdown": bull["maximum_drawdown"],
            "blocked_drift_sells": int(result.counters.get("blocked_drift_sell_count", 0)),
            "bear_reentry_candidates": int(result.counters.get("bear_reentry_candidate_count", 0)),
            "confirmed_bear_reentries": int(result.counters.get("bear_reentry_confirmed_count", 0)),
            "rejected_bear_reentries": int(result.counters.get("bear_reentry_rejected_count", 0)),
        })
        rows.append(row)
    return pd.DataFrame(rows)


def build_event_drawdown_audit(
    daily_by_model: dict[str, pd.DataFrame], windows: dict[str, list[str]],
) -> pd.DataFrame:
    selected = ["COVID", "MAY_2021", "NOV_2021_JUN_2022", "CORRECTION_2025_2026"]
    rows: list[dict[str, Any]] = []
    for event in selected:
        for model in ("B", "P"):
            stats = period_stats(daily_by_model[model], *windows[event])
            rows.append({"event": event, "model": model, **stats})
    out = pd.DataFrame(rows)
    b = out.loc[out["model"].eq("B")].set_index("event")
    p = out.loc[out["model"].eq("P")].set_index("event")
    delta = (p["maximum_drawdown"] - b["maximum_drawdown"]).to_dict()
    out["p_minus_b_drawdown_pp"] = out["event"].map({key: 100.0 * value for key, value in delta.items()})
    return out


def build_peak_guard_audit(
    daily_b: pd.DataFrame, daily_p: pd.DataFrame, signals_b: pd.DataFrame,
    signals_p: pd.DataFrame, start: str, end: str,
) -> pd.DataFrame:
    cols = ["date", "portfolio_value", "unit_nav", "drawdown", "crypto_exposure", "macro_state", "sell_stage"]
    b = daily_b[cols].rename(columns={column: f"B_{column}" for column in cols if column != "date"})
    pcols = [*cols, "bull_persistence_active", "healthy_bull_structure", "bull_persistence_guard"]
    p = daily_p[pcols].rename(columns={column: f"P_{column}" for column in pcols if column != "date"})
    out = b.merge(p, on="date", how="inner", validate="one_to_one")
    date = pd.to_datetime(out["date"], utc=True)
    out = out.loc[date.between(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))].copy()
    for model, signals in (("B", signals_b), ("P", signals_p)):
        action = signals[["signal_date", "actions"]].copy()
        action["date"] = pd.to_datetime(action["signal_date"], utc=True).dt.floor("D")
        action = action.groupby("date", as_index=False)["actions"].agg(lambda x: "|".join(x.fillna("").astype(str)))
        action = action.rename(columns={"actions": f"{model}_actions"})
        out = out.merge(action, on="date", how="left", validate="one_to_one")
    out["exposure_delta_p_minus_b"] = out["P_crypto_exposure"] - out["B_crypto_exposure"]
    out["portfolio_delta_p_minus_b"] = out["P_portfolio_value"] - out["B_portfolio_value"]
    return out


def append_forward_returns(blocked: pd.DataFrame, signals_b: pd.DataFrame) -> pd.DataFrame:
    out = blocked.copy()
    if out.empty:
        for column in ("btc_forward_return_30d", "btc_forward_return_60d"):
            out[column] = pd.Series(dtype=float)
        return out
    prices = signals_b[["signal_date", "btc_close"]].copy()
    prices["signal_date"] = pd.to_datetime(prices["signal_date"], utc=True)
    prices = prices.drop_duplicates("signal_date").sort_values("signal_date").reset_index(drop=True)
    loc = {date: idx for idx, date in enumerate(prices["signal_date"])}
    returns30: list[float] = []
    returns60: list[float] = []
    for value in pd.to_datetime(out["signal_date"], utc=True):
        idx = loc.get(value)
        current = float(prices.loc[idx, "btc_close"]) if idx is not None else np.nan
        returns30.append(
            float(prices.loc[idx + 30, "btc_close"] / current - 1.0)
            if idx is not None and idx + 30 < len(prices) else np.nan
        )
        returns60.append(
            float(prices.loc[idx + 60, "btc_close"] / current - 1.0)
            if idx is not None and idx + 60 < len(prices) else np.nan
        )
    out["btc_forward_return_30d"] = returns30
    out["btc_forward_return_60d"] = returns60
    return out


def complete_drift_audit(
    blocked: pd.DataFrame, signals_b: pd.DataFrame, signals_p: pd.DataFrame,
) -> pd.DataFrame:
    """Include every shadow V3.1 drift event, even when the guard was inactive."""
    rows = blocked.to_dict("records") if not blocked.empty else []
    existing = {pd.Timestamp(row["timestamp"]) for row in rows}
    p = signals_p.set_index("execution_4h_open")
    for _, shadow in signals_b.iterrows():
        if "DRIFT_SELL:" not in str(shadow.get("actions", "")):
            continue
        timestamp = pd.Timestamp(shadow["execution_4h_open"])
        if timestamp in existing:
            continue
        prow = p.loc[timestamp]
        p_actions = str(prow.get("actions", ""))
        executed = "DRIFT_SELL:EXECUTED" in p_actions
        rows.append({
            "timestamp": timestamp,
            "signal_date": shadow.get("signal_date"),
            "original_v31_signal_type": "DRIFT_SELL",
            "original_v31_action": shadow.get("actions", ""),
            "original_target": shadow.get("active_target_after", np.nan),
            "btc_close": shadow.get("btc_close", np.nan),
            "sma20": shadow.get("sma20", np.nan),
            "sma50": shadow.get("sma50", np.nan),
            "sma200": shadow.get("sma200", np.nan),
            "sma200_slope_20d": prow.get("sma200_slope_20d", np.nan),
            "healthy_bull_structure": bool(prow.get("healthy_bull_structure", False)),
            "bull_persistence_active": bool(prow.get("bull_persistence_active", False)),
            "blocked_or_executed": "EXECUTED" if executed else "NOT_EXECUTED_GUARD_INACTIVE",
            "reason": "P_NATIVE_DRIFT_EXECUTED" if executed else "GUARD_INACTIVE_AND_P_DRIFT_TRIGGER_NOT_MET",
            "actual_exposure_before": float(prow.get("crypto_exposure_before", np.nan)),
            "actual_exposure_after": float(prow.get("crypto_exposure_after", np.nan)),
        })
    out = pd.DataFrame(rows)
    return out.sort_values("timestamp").reset_index(drop=True) if not out.empty else out


def transition_statistics(daily_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    bull = {"BULL", "DISTRIBUTION", "EARLY_BEAR", "NEW_BULL"}
    rows: list[dict[str, Any]] = []
    for model in ("B", "P"):
        work = daily_by_model[model].copy().reset_index(drop=True)
        work["class"] = np.where(work["macro_state"].isin(bull), "BULL", "BEAR")
        work["group"] = work["class"].ne(work["class"].shift()).cumsum()
        episodes = work.groupby(["group", "class"], as_index=False).agg(
            start=("date", "min"), end=("date", "max"), observations=("date", "size")
        )
        episodes["duration_days"] = (
            pd.to_datetime(episodes["end"], utc=True) - pd.to_datetime(episodes["start"], utc=True)
        ).dt.total_seconds() / 86_400.0 + 1.0
        transitions = work["class"].ne(work["class"].shift())
        before = work["class"].shift()
        b2bear = int((transitions & before.eq("BULL") & work["class"].eq("BEAR")).sum())
        bear2b = int((transitions & before.eq("BEAR") & work["class"].eq("BULL")).sum())
        bear_eps = episodes.loc[episodes["class"].eq("BEAR")]
        rows.append({
            "model": model,
            "bull_to_bear_transitions": b2bear,
            "bear_to_bull_transitions": bear2b,
            "average_bull_duration_days": float(episodes.loc[episodes["class"].eq("BULL"), "duration_days"].mean()),
            "average_bear_duration_days": float(bear_eps["duration_days"].mean()),
            "false_short_bear_episodes_lt_30d": int((bear_eps["duration_days"] < 30.0).sum()),
        })
    return pd.DataFrame(rows)


def stage4_integrity(trades_by_model: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for model in ("B", "P"):
        trades = trades_by_model[model]
        selected = trades.loc[
            trades["action"].eq("TACTICAL_SELL_STAGE4")
            & pd.to_datetime(trades["timestamp"], utc=True).between(
                pd.Timestamp("2025-11-01", tz="UTC"), pd.Timestamp("2025-11-30 23:59:59", tz="UTC")
            )
        ].copy()
        for timestamp, group in selected.groupby("timestamp"):
            rows.append({
                "model": model, "signal_date": group["signal_date"].iloc[0],
                "execution_date": timestamp,
                "exposure_before": float(group["before_crypto_exposure"].iloc[0]),
                "exposure_after": float(group["after_crypto_exposure"].iloc[-1]),
                "gross_notional_usd": float(group["gross_notional_usd"].sum()),
                "assets": "|".join(group["asset"].astype(str)),
                "reason": "|".join(group["reason"].astype(str).unique()),
            })
    return pd.DataFrame(rows)


def crash_integrity(signals_b: pd.DataFrame, signals_p: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    p = signals_p.set_index("execution_4h_open")
    for _, row in signals_b.iterrows():
        actions = str(row.get("actions", ""))
        for level in ("CRASH_L1", "CRASH_L2"):
            if f"{level}:" not in actions:
                continue
            timestamp = pd.Timestamp(row["execution_4h_open"])
            p_actions = str(p.loc[timestamp, "actions"]) if timestamp in p.index else ""
            rows.append({
                "execution_4h_open": timestamp,
                "level": level,
                "v31_action": actions,
                "v39_action": p_actions,
                "not_suppressed": f"{level}:" in p_actions,
            })
    return pd.DataFrame(rows)


def promotion_evaluation(
    summary: pd.DataFrame,
    event_audit: pd.DataFrame,
    stage4: pd.DataFrame,
    crash: pd.DataFrame,
    integrity: dict[str, bool],
    gates: dict[str, Any],
) -> dict[str, Any]:
    index = summary.set_index("model")
    b, p = index.loc["B"], index.loc["P"]
    events = event_audit.pivot(index="event", columns="model", values="maximum_drawdown")
    checks = {
        "G0_INTEGRITY_ALL_PASS": all(integrity.values()),
        "G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP": 100.0 * (
            p["bull_2023_2025_average_crypto_exposure"] - b["bull_2023_2025_average_crypto_exposure"]
        ) >= float(gates["G1_bull_average_exposure_delta_min_pp"]),
        "G2_BULL_TIME_GTE85_DELTA_GTE_15PP": 100.0 * (
            p["bull_2023_2025_time_exposure_gte_85"] - b["bull_2023_2025_time_exposure_gte_85"]
        ) >= float(gates["G2_bull_time_exposure_gte_85_delta_min_pp"]),
        "G3_FINAL_VALUE_GTE_V31": float(p["final_portfolio_value"]) >= float(gates["G3_final_portfolio_min_usd"]),
        "G4_TWR_CAGR_GTE_47_5PCT": float(p["twr_cagr"]) >= float(gates["G4_twr_cagr_min"]),
        "G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP": float(events.loc["NOV_2021_JUN_2022", "P"]) >= (
            float(events.loc["NOV_2021_JUN_2022", "B"]) - float(gates["G5_2021nov_2022jun_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G6_2025_2026_DD_WORSEN_LTE_2PP": float(events.loc["CORRECTION_2025_2026", "P"]) >= (
            float(events.loc["CORRECTION_2025_2026", "B"]) - float(gates["G6_2025_2026_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G7_COVID_DD_WORSEN_LTE_1PP": float(events.loc["COVID", "P"]) >= (
            float(events.loc["COVID", "B"]) - float(gates["G7_covid_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G8_MAY_2021_DD_WORSEN_LTE_1PP": float(events.loc["MAY_2021", "P"]) >= (
            float(events.loc["MAY_2021", "B"]) - float(gates["G8_may_2021_drawdown_worsening_max_pp"]) / 100.0
        ),
        "G9_2025_11_STAGE4_EXECUTED": set(stage4["model"]) >= {"B", "P"} if not stage4.empty else False,
        "G10_CRASH_L1_L2_NOT_SUPPRESSED": bool(not crash.empty and crash["not_suppressed"].all()),
        "G11_CALMAR_NOT_BELOW_V31": float(p["calmar"]) >= float(b["calmar"]),
        "G12_TURNOVER_INCREASE_LTE_10PCT": float(p["tactical_turnover"]) <= (
            float(b["tactical_turnover"]) * (1.0 + float(gates["G12_tactical_turnover_increase_max_fraction"]))
        ),
    }
    if all(checks.values()):
        verdict = "A. V3.9 BULL PERSISTENCE PROMOTED"
    elif not all(checks[key] for key in [
        "G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP", "G6_2025_2026_DD_WORSEN_LTE_2PP",
        "G7_COVID_DD_WORSEN_LTE_1PP", "G8_MAY_2021_DD_WORSEN_LTE_1PP",
        "G9_2025_11_STAGE4_EXECUTED", "G10_CRASH_L1_L2_NOT_SUPPRESSED",
    ]):
        verdict = "C. V3.9 REJECTED - BEAR PROTECTION DEGRADED"
    elif not checks["G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP"] or not checks["G2_BULL_TIME_GTE85_DELTA_GTE_15PP"]:
        verdict = "D. V3.9 REJECTED - NO MATERIAL BULL EDGE"
    else:
        verdict = "B. V3.1 REMAINS CHAMPION"
    return {
        "verdict": verdict,
        "all_gates_pass": bool(all(checks.values())),
        "checks": {key: bool(value) for key, value in checks.items()},
    }


__all__ = [
    "append_forward_returns", "build_event_drawdown_audit", "build_peak_guard_audit",
    "build_summary", "crash_integrity", "daily_history_v39", "fixed_dca_integrity",
    "complete_drift_audit", "period_stats", "promotion_evaluation", "stage4_integrity",
    "transition_statistics",
]
