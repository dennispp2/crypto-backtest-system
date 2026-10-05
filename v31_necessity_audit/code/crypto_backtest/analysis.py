from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
import pandas as pd

from .engine import BacktestResult, Scenario, run_backtest


def overheat_variant_frame(frame: pd.DataFrame, sma20_dev: float, sma50_dev: float, minimum: int = 2) -> pd.DataFrame:
    out = frame.copy()
    out["overheat_bb"] = out["BTC_daily_close"] > out["bb_upper"]
    out["overheat_sma20"] = out["close_sma20_dev"] >= sma20_dev
    out["overheat_sma50"] = out["close_sma50_dev"] >= sma50_dev
    out["overheat_count"] = out[["overheat_bb", "overheat_sma20", "overheat_sma50"]].sum(axis=1)
    out["overheat_gate"] = out["overheat_count"] >= minimum
    return out


def run_parameter_sensitivity(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    base: Scenario,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    sens = rules["sensitivity"]
    for d20 in sens["sma20_deviation"]:
        for d50 in sens["sma50_deviation"]:
            variant_frame = overheat_variant_frame(frame, d20, d50)
            for mid in sens["dca_ahr_030_035"]:
                for low in sens["dca_ahr_below_030"]:
                    scenario = replace(
                        base,
                        variant=f"sensitivity_d20={d20:.2f}_d50={d50:.2f}_mid={mid:.1f}_low={low:.1f}",
                        dca_mid=float(mid),
                        dca_low=float(low),
                    )
                    result = run_backtest(variant_frame, rules, scenario, record_signals=False)
                    row = {
                        "sensitivity_type": "frozen_grid_do_not_select",
                        "sma20_deviation": d20,
                        "sma50_deviation": d50,
                        "dca_ahr_030_035": mid,
                        "dca_ahr_below_030": low,
                        "min_notional_usdt": rules["modeled_min_notional_usdt"]["BTC"],
                    }
                    row.update(result.summary)
                    rows.append(row)
    return pd.DataFrame(rows)


def cash_analysis(results: list[BacktestResult]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for result in results:
        hist = result.history.copy()
        hist["date"] = hist["timestamp"].dt.floor("D")
        daily = hist.groupby("date", as_index=False).last()
        rows.append(
            {
                "capital_test": result.scenario.capital_test,
                "strategy": result.scenario.name,
                "variant": result.scenario.variant,
                "cash_protection": result.scenario.cash_protection,
                "cash_ratio_lt20_days": int((daily["normal_cash_ratio"] < 0.20).sum()),
                "cash_ratio_lt15_days": int((daily["normal_cash_ratio"] < 0.15).sum()),
                "cash_ratio_lt10_days": int((daily["normal_cash_ratio"] < 0.10).sum()),
                "dca_cash_protection_slowdowns": result.counters["dca_cash_protection_slowdowns"],
                "dca_cash_shortfall_count": result.counters["dca_cash_shortfall_count"],
                "ever_normal_cash_zero": result.counters["ever_normal_cash_zero"],
                "first_normal_cash_depletion": result.counters["first_normal_cash_depletion"],
                "final_portfolio_value": result.summary["final_portfolio_value"],
                "time_weighted_cagr": result.summary["time_weighted_cagr"],
                "maximum_drawdown": result.summary["maximum_drawdown"],
                "average_tactical_cash": result.summary["average_tactical_cash"],
                "time_in_tactical_cash": result.summary["time_in_tactical_cash"],
                "cash_drag": result.summary["cash_drag"],
            }
        )
    return pd.DataFrame(rows)


def _window_metrics(daily: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, float]:
    sub = daily.loc[(daily["date"] >= start) & (daily["date"] <= end)].copy()
    if sub.empty:
        return {
            "start_value": np.nan,
            "end_value": np.nan,
            "twr_return": np.nan,
            "maximum_drawdown": np.nan,
            "average_cash_ratio": np.nan,
            "cash_drag": np.nan,
        }
    normalized = sub["unit_nav"] / sub["unit_nav"].iloc[0]
    dd = normalized / normalized.cummax() - 1.0
    return {
        "start_value": float(sub["portfolio_value"].iloc[0]),
        "end_value": float(sub["portfolio_value"].iloc[-1]),
        "twr_return": float(normalized.iloc[-1] - 1.0),
        "maximum_drawdown": float(dd.min()),
        "average_cash_ratio": float(sub["total_cash_ratio"].mean()),
        "cash_drag": float(np.prod(1.0 + sub.get("cash_drag_increment", 0.0)) - 1.0) if "cash_drag_increment" in sub else np.nan,
    }


def cycle_analysis(
    full: BacktestResult,
    fixed: BacktestResult,
    rules: dict[str, Any],
) -> pd.DataFrame:
    full_daily = full.history.copy()
    fixed_daily = fixed.history.copy()
    for df in (full_daily, fixed_daily):
        df["date"] = df["timestamp"].dt.floor("D")
        df.drop_duplicates("date", keep="last", inplace=True)
    rows: list[dict[str, Any]] = []
    for label, (start_text, end_text) in rules["cycle_windows"].items():
        start = pd.Timestamp(start_text, tz="UTC")
        end = pd.Timestamp(end_text, tz="UTC")
        f = _window_metrics(full_daily, start, end)
        b = _window_metrics(fixed_daily, start, end)
        full_trades = full.trades.loc[
            (full.trades["timestamp"] >= start) & (full.trades["timestamp"] <= end)
        ]
        sell = full_trades[full_trades["action"].str.startswith("TACTICAL_SELL", na=False)]
        buy = full_trades[full_trades["action"].str.startswith("TACTICAL_BUYBACK", na=False)]
        rows.append(
            {
                "cycle": label,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "full_start_value": f["start_value"],
                "full_end_value": f["end_value"],
                "fixed_start_value": b["start_value"],
                "fixed_end_value": b["end_value"],
                "full_twr_return": f["twr_return"],
                "fixed_twr_return": b["twr_return"],
                "final_return_difference": f["twr_return"] - b["twr_return"],
                "full_maximum_drawdown": f["maximum_drawdown"],
                "fixed_maximum_drawdown": b["maximum_drawdown"],
                "drawdown_difference": f["maximum_drawdown"] - b["maximum_drawdown"],
                "full_average_cash_ratio": f["average_cash_ratio"],
                "full_cash_drag": f["cash_drag"],
                "tactical_sell_trade_count": len(sell),
                "tactical_buyback_trade_count": len(buy),
                "stage1_count": int(sell["action"].eq("TACTICAL_SELL_STAGE_1").sum()),
                "stage2_count": int(sell["action"].eq("TACTICAL_SELL_STAGE_2").sum()),
                "stage3_count": int(sell["action"].eq("TACTICAL_SELL_STAGE_3").sum()),
                "stage4_count": int(sell["action"].eq("TACTICAL_SELL_STAGE_4").sum()),
                "buy_030_035_count": int(buy["action"].eq("TACTICAL_BUYBACK_AHR_030_035").sum()),
                "buy_below_030_count": int(buy["action"].eq("TACTICAL_BUYBACK_AHR_BELOW_030").sum()),
                "buy_extreme_count": int(buy["action"].eq("TACTICAL_BUYBACK_AHR_EXTREME").sum()),
                "right_confirmation_count": int(buy["action"].eq("TACTICAL_BUYBACK_RIGHT_CONFIRMATION").sum()),
            }
        )
    return pd.DataFrame(rows)


def btc_threshold_events(
    daily: pd.DataFrame,
    *,
    ahr_column: str,
    threshold: float,
    horizons: tuple[int, ...] = (30, 90, 180, 365),
) -> pd.DataFrame:
    work = daily[["open_time", "close", ahr_column]].dropna().copy().reset_index(drop=True)
    inside = work[ahr_column] <= threshold
    entry = inside & ~inside.shift(1, fill_value=False)
    records: list[dict[str, Any]] = []
    for idx in np.flatnonzero(entry.to_numpy()):
        base = float(work.at[idx, "close"])
        row: dict[str, Any] = {
            "trigger_date": work.at[idx, "open_time"],
            "ahr_method": ahr_column,
            "threshold": threshold,
            "ahr_at_trigger": float(work.at[idx, ahr_column]),
            "trigger_close": base,
        }
        for horizon in horizons:
            future_idx = idx + horizon
            row[f"return_{horizon}d"] = (
                float(work.at[future_idx, "close"] / base - 1.0)
                if future_idx < len(work)
                else np.nan
            )
        future = work.iloc[idx + 1 : min(len(work), idx + 366)]["close"]
        row["maximum_adverse_excursion_365d"] = float(future.min() / base - 1.0) if len(future) else np.nan
        row["maximum_favorable_excursion_365d"] = float(future.max() / base - 1.0) if len(future) else np.nan
        records.append(row)
    return pd.DataFrame(records)


def btc_extended_validation(daily: pd.DataFrame, seed: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    methods = [
        "ahr999_fixed_arithmetic",
        "ahr999_fixed_geometric",
        "ahr999_expanding_arithmetic",
    ]
    thresholds = (0.45, 0.35, 0.30, 0.28)
    event_frames = [
        btc_threshold_events(daily, ahr_column=method, threshold=threshold)
        for method in methods
        for threshold in thresholds
    ]
    events = pd.concat([x for x in event_frames if not x.empty], ignore_index=True)
    rows: list[dict[str, Any]] = []
    rng = np.random.default_rng(seed)
    for (method, threshold), group in events.groupby(["ahr_method", "threshold"]):
        row: dict[str, Any] = {
            "ahr_method": method,
            "threshold": threshold,
            "event_count": len(group),
            "first_event": group["trigger_date"].min(),
            "last_event": group["trigger_date"].max(),
            "mean_mae_365d": group["maximum_adverse_excursion_365d"].mean(),
            "mean_mfe_365d": group["maximum_favorable_excursion_365d"].mean(),
        }
        for horizon in (30, 90, 180, 365):
            values = group[f"return_{horizon}d"].dropna()
            row[f"n_{horizon}d"] = len(values)
            row[f"win_rate_{horizon}d"] = float((values > 0).mean()) if len(values) else np.nan
            row[f"median_return_{horizon}d"] = float(values.median()) if len(values) else np.nan
            row[f"mean_return_{horizon}d"] = float(values.mean()) if len(values) else np.nan
        rows.append(row)
    summary = pd.DataFrame(rows)

    # Descriptive bootstrap: events are few and nested, so this is not claimed as an independent-sample test.
    comparisons: list[dict[str, Any]] = []
    primary = events[events["ahr_method"] == "ahr999_fixed_arithmetic"]
    base = primary[primary["threshold"] == 0.30]["return_365d"].dropna().to_numpy()
    for comparator in (0.35, 0.45):
        other = primary[primary["threshold"] == comparator]["return_365d"].dropna().to_numpy()
        if len(base) and len(other):
            draws = np.empty(5000)
            for i in range(len(draws)):
                draws[i] = np.median(rng.choice(base, len(base), replace=True)) - np.median(
                    rng.choice(other, len(other), replace=True)
                )
            comparisons.append(
                {
                    "ahr_method": "ahr999_fixed_arithmetic",
                    "threshold": 0.30,
                    "comparison_threshold": comparator,
                    "median_365d_return_difference": float(np.median(base) - np.median(other)),
                    "bootstrap_ci_low": float(np.quantile(draws, 0.025)),
                    "bootstrap_ci_high": float(np.quantile(draws, 0.975)),
                    "independent_significance_claim_allowed": False,
                    "reason": "threshold episodes are few and nested",
                }
            )
    comparison_df = pd.DataFrame(comparisons)
    if not comparison_df.empty:
        # Preserve one summary row per method/threshold.  Comparators are
        # separate columns because both 0.35 and 0.45 compare with 0.30.
        for _, comp in comparison_df.iterrows():
            suffix = str(comp["comparison_threshold"]).replace(".", "_")
            mask = (
                (summary["ahr_method"] == comp["ahr_method"])
                & (summary["threshold"] == comp["threshold"])
            )
            summary.loc[mask, f"median_365d_diff_vs_{suffix}"] = comp[
                "median_365d_return_difference"
            ]
            summary.loc[mask, f"bootstrap_ci_low_vs_{suffix}"] = comp["bootstrap_ci_low"]
            summary.loc[mask, f"bootstrap_ci_high_vs_{suffix}"] = comp["bootstrap_ci_high"]
            summary.loc[mask, f"independent_claim_allowed_vs_{suffix}"] = False
    return summary, events


def tactical_event_effectiveness(signals: pd.DataFrame, btc_daily: pd.DataFrame) -> pd.DataFrame:
    if signals.empty:
        return pd.DataFrame()
    price = btc_daily.set_index("signal_date")["close"].sort_index()
    rows: list[dict[str, Any]] = []
    events = signals.loc[signals["stage_action"].astype(str).str.startswith("STAGE_")]
    for _, event in events.iterrows():
        date = pd.Timestamp(event["signal_date"])
        if date not in price.index:
            continue
        base = float(price.loc[date])
        future = price.loc[price.index > date].iloc[:180]
        rows.append(
            {
                "signal_date": date,
                "stage": int(str(event["stage_action"]).split("_")[-1]),
                "btc_close": base,
                "return_30d": float(future.iloc[29] / base - 1.0) if len(future) >= 30 else np.nan,
                "return_90d": float(future.iloc[89] / base - 1.0) if len(future) >= 90 else np.nan,
                "return_180d": float(future.iloc[179] / base - 1.0) if len(future) >= 180 else np.nan,
                "mae_90d": float(future.iloc[:90].min() / base - 1.0) if len(future) else np.nan,
                "mfe_90d": float(future.iloc[:90].max() / base - 1.0) if len(future) else np.nan,
            }
        )
    detail = pd.DataFrame(rows)
    if detail.empty:
        return detail
    summary = detail.groupby("stage", as_index=False).agg(
        event_count=("stage", "size"),
        median_return_90d=("return_90d", "median"),
        mean_return_180d=("return_180d", "mean"),
        median_mae_90d=("mae_90d", "median"),
        median_mfe_90d=("mfe_90d", "median"),
    )
    return summary
