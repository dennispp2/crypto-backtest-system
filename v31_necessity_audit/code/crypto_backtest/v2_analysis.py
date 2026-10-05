from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .engine import ASSETS, BacktestResult
from .metrics import calculate_summary
from .v2_engine import HedgeScenario, V2BacktestResult


def standardize_champion(
    result: BacktestResult,
    rules_v2: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    history = result.history.copy()
    crypto_value = (
        history["portfolio_value"]
        - history["normal_cash"]
        - history["pending_dca_cash"]
        - history["tactical_cash"]
    )
    history["btc_value"] = crypto_value * history["BTC_allocation"]
    history["eth_value"] = crypto_value * history["ETH_allocation"]
    history["bnb_value"] = crypto_value * history["BNB_allocation"]
    history["crypto_exposure"] = crypto_value / history["portfolio_value"]
    history["cycle_regime"] = "CONTROL"
    history["sell_cycle_id"] = 0
    history["stage_target_exposure"] = np.nan
    history["stage_lower_band"] = np.nan
    history["stage_upper_band"] = np.nan
    history["intended_dca"] = (
        float(rules_v2["external_contribution_per_4h"])
        * history["elapsed_4h_intervals"].astype(float)
    )
    history["tactical_cash_drag_increment"] = 0.0
    history["daily_floor_breach_reason"] = "not_applicable_control"
    history["stage4_upper_band_exception_reason"] = "not_applicable_control"

    trades = result.trades.copy()
    trades["cycle_regime"] = "CONTROL"
    trades["sell_cycle_id"] = 0
    trades["post_trade_crypto_exposure"] = np.nan
    trades["normal_cash_after"] = np.nan
    trades["pending_dca_cash_after"] = np.nan
    trades["tactical_cash_after"] = 0.0
    return history, trades


def drawdown_episode(history: pd.DataFrame) -> dict[str, Any]:
    work = history.sort_values("timestamp").reset_index(drop=True)
    trough_pos = int(work["drawdown"].astype(float).to_numpy().argmin())
    through_trough = work.iloc[: trough_pos + 1]
    peak_nav = max(1.0, float(through_trough["unit_nav"].max()))
    if peak_nav <= 1.0 and not (through_trough["unit_nav"] >= 1.0).any():
        peak_pos = 0
    else:
        peak_candidates = through_trough.index[
            np.isclose(through_trough["unit_nav"].astype(float), peak_nav, rtol=0.0, atol=1e-12)
        ]
        peak_pos = int(peak_candidates[-1])
    peak = work.iloc[peak_pos]
    trough = work.iloc[trough_pos]
    after = work.iloc[trough_pos + 1 :]
    recovered = after.loc[after["unit_nav"].astype(float) >= peak_nav - 1e-12]
    if recovered.empty:
        recovery_ts = pd.NaT
        duration_end = pd.Timestamp(work.iloc[-1]["timestamp"])
        recovery_status = "NOT_RECOVERED_BY_END"
    else:
        recovery_ts = pd.Timestamp(recovered.iloc[0]["timestamp"])
        duration_end = recovery_ts
        recovery_status = "RECOVERED"
    peak_ts = pd.Timestamp(peak["timestamp"])
    trough_ts = pd.Timestamp(trough["timestamp"])
    return {
        "max_dd_peak_date": peak_ts.isoformat(),
        "max_dd_peak_portfolio_value": float(peak["portfolio_value"]),
        "max_dd_trough_date": trough_ts.isoformat(),
        "max_dd_trough_portfolio_value": float(trough["portfolio_value"]),
        "max_dd_peak_to_trough_days": (trough_ts - peak_ts).total_seconds() / 86_400.0,
        "max_dd_recovery_date": "" if pd.isna(recovery_ts) else recovery_ts.isoformat(),
        "max_dd_duration_days": (duration_end - peak_ts).total_seconds() / 86_400.0,
        "max_dd_recovery_status": recovery_status,
    }


def enriched_summary(
    result: BacktestResult | V2BacktestResult,
    history: pd.DataFrame,
    trades: pd.DataFrame,
    rules_v2: dict[str, Any],
) -> dict[str, Any]:
    counters = result.counters
    base = calculate_summary(
        history,
        trades,
        scenario=result.scenario,
        counters=counters,
        rules=rules_v2,
    )
    tactical_sell = trades[trades["action"].str.startswith("TACTICAL_SELL", na=False)]
    tactical_buy = trades[trades["action"].str.startswith("TACTICAL_BUYBACK", na=False)]
    episode = drawdown_episode(history)
    tactical_drag = float(
        np.prod(1.0 + history["tactical_cash_drag_increment"].fillna(0.0).clip(lower=-0.999999))
        - 1.0
    )
    hard_floor = getattr(result.scenario, "hard_floor", np.nan)
    base.update(
        {
            "hard_floor": hard_floor,
            "total_tactical_sell_notional": float(tactical_sell["gross_notional_usd"].sum()),
            "total_tactical_buy_notional": float(tactical_buy["gross_notional_usd"].sum()),
            "average_crypto_exposure": float(history["crypto_exposure"].mean()),
            "median_crypto_exposure": float(history["crypto_exposure"].median()),
            "time_crypto_exposure_below_30pct": float((history["crypto_exposure"] < 0.30).mean()),
            "time_crypto_exposure_below_50pct": float((history["crypto_exposure"] < 0.50).mean()),
            "transaction_count": int(len(trades)),
            "total_fees": float(trades["fee_usd"].sum()),
            "total_slippage": float(trades["slippage_usd"].sum()),
            "tactical_cash_drag": tactical_drag,
            **episode,
        }
    )
    return base


def daily_history_v2(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    last_columns = [
        "portfolio_value",
        "btc_value",
        "eth_value",
        "bnb_value",
        "unit_nav",
        "drawdown",
        "normal_cash",
        "pending_dca_cash",
        "tactical_cash",
        "normal_cash_ratio",
        "total_cash_ratio",
        "tactical_cash_ratio",
        "crypto_exposure",
        "BTC_allocation",
        "ETH_allocation",
        "BNB_allocation",
        "BTC_close",
        "ETH_close",
        "BNB_close",
        "ahr999",
        "cycle_regime",
        "sell_stage",
        "sell_cycle_id",
        "stage_target_exposure",
        "stage_lower_band",
        "stage_upper_band",
        "theoretical_dca",
        "protected_dca",
        "daily_floor_breach_reason",
        "stage4_upper_band_exception_reason",
    ]
    sum_columns = ["external_flow", "intended_dca", "committed_dca", "executed_dca"]
    aggregations: dict[str, Any] = {column: "last" for column in last_columns}
    aggregations.update({column: "sum" for column in sum_columns})
    aggregations["twr_return"] = lambda x: float(np.prod(1.0 + x) - 1.0)
    aggregations["cash_drag_increment"] = lambda x: float(np.prod(1.0 + x) - 1.0)
    aggregations["tactical_cash_drag_increment"] = lambda x: float(np.prod(1.0 + x) - 1.0)
    return work.groupby("date", as_index=False).agg(aggregations)


def fixed_dca_integrity_audit(
    a_history: pd.DataFrame,
    a_trades: pd.DataFrame,
    e20: V2BacktestResult,
) -> pd.DataFrame:
    def trade_pivot(trades: pd.DataFrame, prefix: str) -> pd.DataFrame:
        dca = trades.loc[trades["action"].eq("NORMAL_DCA")].copy()
        if dca.empty:
            return pd.DataFrame(columns=["timestamp"])
        grouped = (
            dca.groupby(["timestamp", "asset"], as_index=False)
            .agg(
                budget_usd=("cash_change_usd", lambda x: float(-x.sum())),
                quantity=("quantity", "sum"),
                gross_notional=("gross_notional_usd", "sum"),
            )
        )
        pieces: list[pd.DataFrame] = []
        for value in ("budget_usd", "quantity", "gross_notional"):
            wide = grouped.pivot(index="timestamp", columns="asset", values=value).fillna(0.0)
            wide.columns = [f"{prefix}_{value}_{asset}" for asset in wide.columns]
            pieces.append(wide)
        return pd.concat(pieces, axis=1).reset_index()

    a = a_history[
        ["timestamp", "external_flow", "intended_dca", "committed_dca", "executed_dca"]
    ].copy()
    a = a.rename(columns={column: f"A_{column}" for column in a.columns if column != "timestamp"})
    e = e20.history[
        ["timestamp", "external_flow", "intended_dca", "committed_dca", "executed_dca"]
    ].copy()
    e = e.rename(columns={column: f"E20_{column}" for column in e.columns if column != "timestamp"})
    audit = a.merge(e, on="timestamp", how="outer", validate="one_to_one")
    audit = audit.merge(trade_pivot(a_trades, "A"), on="timestamp", how="left", validate="one_to_one")
    audit = audit.merge(trade_pivot(e20.trades, "E20"), on="timestamp", how="left", validate="one_to_one")
    numeric = audit.select_dtypes(include=[np.number]).columns
    audit[numeric] = audit[numeric].fillna(0.0)
    comparisons = [
        ("external_flow_match", "A_external_flow", "E20_external_flow"),
        ("intended_notional_match", "A_intended_dca", "E20_intended_dca"),
        ("committed_notional_match", "A_committed_dca", "E20_committed_dca"),
        ("executed_notional_match", "A_executed_dca", "E20_executed_dca"),
    ]
    for asset in ASSETS:
        for value in ("budget_usd", "quantity", "gross_notional"):
            left = f"A_{value}_{asset}"
            right = f"E20_{value}_{asset}"
            if left not in audit:
                audit[left] = 0.0
            if right not in audit:
                audit[right] = 0.0
            comparisons.append((f"{value}_{asset}_match", left, right))
    match_columns: list[str] = []
    for label, left, right in comparisons:
        audit[label] = np.isclose(
            audit[left].astype(float), audit[right].astype(float), rtol=1e-11, atol=1e-9
        )
        match_columns.append(label)
    audit["all_match"] = audit[match_columns].all(axis=1)
    return audit


def exposure_audit(
    daily_by_strategy: dict[str, pd.DataFrame],
    floors: dict[str, float | None],
) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for strategy, daily in daily_by_strategy.items():
        out = daily[
            [
                "date",
                "portfolio_value",
                "btc_value",
                "eth_value",
                "bnb_value",
                "normal_cash",
                "pending_dca_cash",
                "tactical_cash",
                "crypto_exposure",
                "total_cash_ratio",
                "cycle_regime",
                "sell_stage",
                "sell_cycle_id",
                "stage_target_exposure",
                "stage_lower_band",
                "stage_upper_band",
                "daily_floor_breach_reason",
                "stage4_upper_band_exception_reason",
            ]
        ].copy()
        out.insert(1, "strategy", strategy)
        floor = floors[strategy]
        out["hard_floor"] = floor
        out["crypto_exposure_pct"] = 100.0 * out["crypto_exposure"]
        out["cash_pct"] = 100.0 * out["total_cash_ratio"]
        if floor is None:
            out["daily_mark_to_market_floor_pass"] = True
        else:
            out["daily_mark_to_market_floor_pass"] = out["crypto_exposure"] >= floor - 1e-10
        allowed = {
            "none",
            "minimum_notional",
            "signal_timing_between_daily_checks",
            "execution_delay",
            "hard_floor_binding",
            "not_applicable_control",
        }
        stage4_problem = (out["sell_stage"].astype(int) == 4) & (
            out["crypto_exposure"] > out["stage_upper_band"].astype(float) + 1e-10
        )
        out["stage4_upper_band_assertion_pass"] = (~stage4_problem) | out[
            "stage4_upper_band_exception_reason"
        ].isin(allowed - {"none"})
        out["stage3_93pct_decoupling_pass"] = ~(
            (out["sell_stage"].astype(int) == 3) & (out["crypto_exposure"] >= 0.93)
        )
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def segment_analysis(
    histories: dict[str, pd.DataFrame],
    segments: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for strategy, history in histories.items():
        work = history.copy()
        work["timestamp"] = pd.to_datetime(work["timestamp"], utc=True)
        for label, (start_text, end_text) in segments.items():
            start = pd.Timestamp(start_text, tz="UTC")
            end = work["timestamp"].max() if end_text == "end" else pd.Timestamp(end_text, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(hours=4)
            sub = work.loc[(work["timestamp"] >= start) & (work["timestamp"] <= end)].copy()
            if sub.empty:
                continue
            segment_nav = (1.0 + sub["twr_return"].astype(float)).cumprod()
            dd = segment_nav / segment_nav.cummax() - 1.0
            trough_pos = int(dd.to_numpy().argmin())
            peak_pos = int(segment_nav.iloc[: trough_pos + 1].to_numpy().argmax())
            rows.append(
                {
                    "segment": label,
                    "strategy": strategy,
                    "start": sub.iloc[0]["timestamp"],
                    "end": sub.iloc[-1]["timestamp"],
                    "start_portfolio_value": float(sub.iloc[0]["portfolio_value"]),
                    "end_portfolio_value": float(sub.iloc[-1]["portfolio_value"]),
                    "segment_twr_return": float(segment_nav.iloc[-1] - 1.0),
                    "segment_max_drawdown": float(dd.min()),
                    "max_dd_peak_date": sub.iloc[peak_pos]["timestamp"],
                    "max_dd_trough_date": sub.iloc[trough_pos]["timestamp"],
                    "average_crypto_exposure": float(sub["crypto_exposure"].mean()),
                    "median_crypto_exposure": float(sub["crypto_exposure"].median()),
                    "time_tactical_cash_positive": float((sub["tactical_cash"] > 1e-9).mean()),
                    "minimum_crypto_exposure": float(sub["crypto_exposure"].min()),
                    "maximum_sell_stage": int(sub["sell_stage"].max()),
                }
            )
    return pd.DataFrame(rows)


def longest_true_run_days(dates: pd.Series, mask: pd.Series) -> float:
    if not mask.any():
        return 0.0
    groups = (~mask).cumsum()
    durations: list[float] = []
    for _, index in dates[mask].groupby(groups[mask]).groups.items():
        selected = pd.to_datetime(dates.loc[index], utc=True)
        durations.append((selected.max() - selected.min()).total_seconds() / 86_400.0 + 1.0)
    return max(durations, default=0.0)
