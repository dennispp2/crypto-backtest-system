from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .engine import ASSETS, BacktestResult
from .metrics import calculate_summary
from .v2_analysis import drawdown_episode
from .v3_engine import V3BacktestResult


def standardize_champion(
    result: BacktestResult,
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    history = result.history.copy()
    crypto_value = history["portfolio_value"] - history["normal_cash"] - history["pending_dca_cash"] - history["tactical_cash"]
    history["btc_value"] = crypto_value * history["BTC_allocation"]
    history["eth_value"] = crypto_value * history["ETH_allocation"]
    history["bnb_value"] = crypto_value * history["BNB_allocation"]
    history["crypto_exposure"] = crypto_value / history["portfolio_value"]
    history["macro_regime_previous"] = "CONTROL"
    history["macro_regime_current"] = "CONTROL"
    history["macro_regime"] = "CONTROL"
    history["transition_reason"] = "NOT_APPLICABLE_CONTROL"
    history["sell_stage"] = 0
    history["sell_cycle_id"] = 0
    history["redeploy_cycle_id"] = 0
    history["cycle_confirmed"] = False
    history["days_in_current_regime"] = 0
    history["target_crypto_exposure"] = np.nan
    history["active_exposure_target"] = np.nan
    history["crash_override"] = False
    history["crash_override_event"] = False
    history["ordinary_risk_off_lock_days"] = 0
    history["redeploy_days_remaining"] = 0
    for gate in range(1, 8):
        history[f"new_bull_gate_{gate}"] = False
    history["BTC_signal_close"] = history["BTC_close"]
    history["BTC_signal_low"] = np.nan
    history["sma10"] = np.nan
    history["sma20"] = np.nan
    history["sma50"] = np.nan
    history["sma200"] = np.nan
    history["intended_dca"] = float(rules["external_contribution_per_4h"]) * history["elapsed_4h_intervals"].astype(float)
    history["tactical_cash_drag_increment"] = 0.0
    history["daily_floor_breach_reason"] = "not_applicable_control"

    trades = result.trades.copy()
    defaults: dict[str, Any] = {
        "reason": "",
        "macro_regime": "CONTROL",
        "sell_cycle_id": 0,
        "before_crypto_exposure": np.nan,
        "target_crypto_exposure": np.nan,
        "after_crypto_exposure": np.nan,
        "active_exposure_target": np.nan,
        "days_since_previous_tactical_trade": np.nan,
        "tactical_event_id": 0,
        "bearish_invalidation": False,
        "normal_cash_after": np.nan,
        "pending_dca_cash_after": np.nan,
        "tactical_cash_after": 0.0,
    }
    for column, value in defaults.items():
        trades[column] = value
    return history, trades


def enriched_summary(
    result: BacktestResult | V3BacktestResult,
    history: pd.DataFrame,
    trades: pd.DataFrame,
    rules: dict[str, Any],
) -> dict[str, Any]:
    base = calculate_summary(history, trades, scenario=result.scenario, counters=result.counters, rules=rules)
    tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False)].copy()
    tactical_sells = tactical.loc[tactical["side"].eq("SELL")]
    tactical_buys = tactical.loc[tactical["side"].eq("BUY")]
    daily_snapshot = (
        history.assign(_date=pd.to_datetime(history["timestamp"], utc=True).dt.floor("D"))
        .groupby("_date", as_index=False)
        .last()
    )
    average_value = float(daily_snapshot["portfolio_value"].mean())
    tactical_notional = float(tactical["gross_notional_usd"].sum()) if not tactical.empty else 0.0
    tactical_drag = float(np.prod(1.0 + history["tactical_cash_drag_increment"].fillna(0.0).clip(lower=-0.999999)) - 1.0)
    episode = drawdown_episode(history)
    base.update(
        {
            "hard_floor": getattr(result.scenario, "hard_floor", np.nan),
            "average_crypto_exposure": float(daily_snapshot["crypto_exposure"].mean()),
            "median_crypto_exposure": float(daily_snapshot["crypto_exposure"].median()),
            "average_tactical_cash_ratio": float(daily_snapshot["tactical_cash_ratio"].mean()),
            "material_tactical_cash_time": float((daily_snapshot["tactical_cash_ratio"] > float(rules["material_tactical_cash_ratio"])).mean()),
            "raw_tactical_cash_positive_time": float((daily_snapshot["tactical_cash"] > 1e-9).mean()),
            "transaction_count": int(len(trades)),
            "tactical_transaction_count": int(len(tactical)),
            "tactical_event_count": int(tactical["tactical_event_id"].nunique()) if not tactical.empty else 0,
            "tactical_turnover": tactical_notional / average_value if average_value else np.nan,
            "total_tactical_sell_notional": float(tactical_sells["gross_notional_usd"].sum()),
            "total_tactical_buy_notional": float(tactical_buys["gross_notional_usd"].sum()),
            "total_fees": float(trades["fee_usd"].sum()),
            "total_slippage": float(trades["slippage_usd"].sum()),
            "tactical_cash_drag": tactical_drag,
            **episode,
        }
    )
    return base


def daily_history_v3(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    first_columns = ["macro_regime_previous", "transition_reason"]
    last_columns = [
        "portfolio_value", "btc_value", "eth_value", "bnb_value", "unit_nav", "drawdown",
        "normal_cash", "pending_dca_cash", "tactical_cash", "normal_cash_ratio", "total_cash_ratio",
        "tactical_cash_ratio", "crypto_exposure", "BTC_allocation", "ETH_allocation", "BNB_allocation",
        "BTC_signal_close", "BTC_signal_low", "sma10", "sma20", "sma50", "sma200", "ahr999",
        "macro_regime_current", "macro_regime", "sell_stage", "sell_cycle_id", "redeploy_cycle_id",
        "cycle_confirmed", "days_in_current_regime", "target_crypto_exposure", "active_exposure_target",
        "crash_override", "ordinary_risk_off_lock_days", "redeploy_days_remaining", "theoretical_dca",
        "protected_dca", "daily_floor_breach_reason", *[f"new_bull_gate_{gate}" for gate in range(1, 8)],
    ]
    aggregations: dict[str, Any] = {column: "first" for column in first_columns}
    aggregations.update({column: "last" for column in last_columns})
    aggregations["crash_override_event"] = "max"
    for column in ("external_flow", "intended_dca", "committed_dca", "executed_dca"):
        aggregations[column] = "sum"
    for column in ("twr_return", "cash_drag_increment", "tactical_cash_drag_increment"):
        aggregations[column] = lambda values: float(np.prod(1.0 + values) - 1.0)
    daily = work.groupby("date", as_index=False).agg(aggregations)
    daily["timestamp"] = daily["date"]
    daily["btc_close"] = daily["BTC_signal_close"]
    daily["actual_crypto_exposure"] = daily["crypto_exposure"]
    daily["active_crypto_exposure_target"] = daily["active_exposure_target"]
    daily["crash_override_active"] = daily["crash_override"]
    daily["cycle_id"] = daily["sell_cycle_id"]
    return daily


def fixed_dca_integrity_audit(
    a_history: pd.DataFrame,
    a_trades: pd.DataFrame,
    e20: V3BacktestResult,
) -> pd.DataFrame:
    def pivot(trades: pd.DataFrame, prefix: str) -> pd.DataFrame:
        dca = trades.loc[trades["action"].eq("NORMAL_DCA")].copy()
        grouped = dca.groupby(["timestamp", "asset"], as_index=False).agg(
            budget_usd=("cash_change_usd", lambda values: float(-values.sum())),
            quantity=("quantity", "sum"),
            gross_notional=("gross_notional_usd", "sum"),
        )
        pieces: list[pd.DataFrame] = []
        for value in ("budget_usd", "quantity", "gross_notional"):
            wide = grouped.pivot(index="timestamp", columns="asset", values=value).fillna(0.0)
            wide.columns = [f"{prefix}_{value}_{asset}" for asset in wide.columns]
            pieces.append(wide)
        return pd.concat(pieces, axis=1).reset_index()

    columns = ["timestamp", "external_flow", "intended_dca", "committed_dca", "executed_dca"]
    left = a_history[columns].rename(columns={column: f"A_{column}" for column in columns if column != "timestamp"})
    right = e20.history[columns].rename(columns={column: f"E20_{column}" for column in columns if column != "timestamp"})
    out = left.merge(right, on="timestamp", how="outer", validate="one_to_one")
    out = out.merge(pivot(a_trades, "A"), on="timestamp", how="left", validate="one_to_one")
    out = out.merge(pivot(e20.trades, "E20"), on="timestamp", how="left", validate="one_to_one")
    numeric = out.select_dtypes(include=[np.number]).columns
    out[numeric] = out[numeric].fillna(0.0)
    comparisons = [
        ("external_flow_match", "A_external_flow", "E20_external_flow"),
        ("intended_notional_match", "A_intended_dca", "E20_intended_dca"),
        ("committed_notional_match", "A_committed_dca", "E20_committed_dca"),
        ("executed_notional_match", "A_executed_dca", "E20_executed_dca"),
    ]
    for asset in ASSETS:
        for value in ("budget_usd", "quantity", "gross_notional"):
            a_col, e_col = f"A_{value}_{asset}", f"E20_{value}_{asset}"
            if a_col not in out:
                out[a_col] = 0.0
            if e_col not in out:
                out[e_col] = 0.0
            comparisons.append((f"{value}_{asset}_match", a_col, e_col))
    matches: list[str] = []
    for name, a_col, e_col in comparisons:
        out[name] = np.isclose(out[a_col].astype(float), out[e_col].astype(float), rtol=1e-11, atol=1e-9)
        matches.append(name)
    out["all_match"] = out[matches].all(axis=1)
    return out


def macro_fsm_audit(signals: pd.DataFrame, rules: dict[str, Any]) -> pd.DataFrame:
    transitions = signals.loc[signals["regime_before"] != signals["regime_after"]].copy()
    if transitions.empty:
        return pd.DataFrame(columns=["date", "from_state", "to_state", "allowed_transition"])
    out = pd.DataFrame(
        {
            "date": transitions["signal_date"],
            "strategy": transitions["strategy"],
            "from_state": transitions["regime_before"],
            "to_state": transitions["regime_after"],
            "reason": transitions["decision_reason"],
            "btc_price": transitions["btc_close"],
            "SMA20": transitions["sma20"],
            "SMA50": transitions["sma50"],
            "SMA200": transitions["sma200"],
            "crypto_exposure_before": transitions["crypto_exposure_before"],
            "crypto_exposure_after": transitions["crypto_exposure_after"],
            "cycle_id": transitions["cycle_id_after"],
        }
    )
    out["allowed_transition"] = [
        to_state in rules["allowed_transitions"][from_state]
        for from_state, to_state in zip(out["from_state"], out["to_state"])
    ]
    out["illegal_transition"] = ~out["allowed_transition"]
    return out


def exposure_audit(daily_by_strategy: dict[str, pd.DataFrame], floors: dict[str, float | None]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for strategy, daily in daily_by_strategy.items():
        columns = [
            "date", "portfolio_value", "btc_value", "eth_value", "eth_value", "bnb_value",
            "normal_cash", "pending_dca_cash", "tactical_cash", "normal_cash_ratio", "tactical_cash_ratio",
            "crypto_exposure", "macro_regime_previous", "macro_regime_current", "transition_reason", "sell_stage",
            "target_crypto_exposure", "active_exposure_target", "crash_override_active", "cycle_id",
            "cycle_confirmed", "days_in_current_regime", *[f"new_bull_gate_{gate}" for gate in range(1, 8)],
        ]
        # Preserve column order without retaining accidental duplicates.
        columns = list(dict.fromkeys(columns))
        out = daily[columns].copy()
        out.insert(1, "strategy", strategy)
        floor = floors[strategy]
        out["hard_floor"] = floor
        out["sell_time_floor_applicable"] = floor is not None
        out["daily_mark_to_market_floor_pass"] = True if floor is None else out["crypto_exposure"] >= float(floor) - 1e-10
        rows.append(out)
    return pd.concat(rows, ignore_index=True)


def _future_excursion(daily: pd.DataFrame, date: pd.Timestamp, price: float, days: int) -> tuple[float, float]:
    end = date + pd.Timedelta(days=days)
    future = daily.loc[(daily["signal_date"] > date) & (daily["signal_date"] <= end), "close"].astype(float)
    if future.empty or price <= 0:
        return np.nan, np.nan
    returns = future / price - 1.0
    return float(returns.min()), float(returns.max())


def cycle_quality_audit(result: V3BacktestResult, daily_features: pd.DataFrame) -> pd.DataFrame:
    if result.cycles.empty:
        return result.cycles.copy()
    cycles = result.cycles.copy()
    daily = daily_features.copy()
    daily["signal_date"] = pd.to_datetime(daily["signal_date"], utc=True)
    tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    rows: list[dict[str, Any]] = []
    for _, cycle in cycles.iterrows():
        row = cycle.to_dict()
        start = pd.Timestamp(cycle["cycle_start"])
        end = pd.Timestamp(cycle["cycle_end"])
        start_match = daily.loc[daily["signal_date"] == start, "close"]
        start_price = float(start_match.iloc[-1]) if not start_match.empty else np.nan
        row["duration_days"] = (end - start).total_seconds() / 86_400.0 if pd.notna(end) else np.nan
        row["cycle_start_btc_price"] = start_price
        cycle_trades = tactical.loc[tactical["sell_cycle_id"].eq(int(cycle["cycle_id"]))]
        row["tactical_cash_generated"] = float(cycle_trades.loc[cycle_trades["side"].eq("SELL"), "cash_change_usd"].sum())
        row["tactical_cash_redeployed"] = float(-cycle_trades.loc[cycle_trades["side"].eq("BUY"), "cash_change_usd"].sum())
        for horizon in (30, 90, 180):
            mae, mfe = _future_excursion(daily, start, start_price, horizon)
            row[f"subsequent_btc_{horizon}d_mae"] = mae
            row[f"subsequent_btc_{horizon}d_mfe"] = mfe
        row["cycle_outcome"] = cycle["status"]
        rows.append(row)
    return pd.DataFrame(rows)


def crash_override_audit(signals: pd.DataFrame, daily_features: pd.DataFrame) -> pd.DataFrame:
    events = signals.loc[signals["crash_override_event"].fillna(False).astype(bool)].copy()
    daily = daily_features.copy()
    daily["signal_date"] = pd.to_datetime(daily["signal_date"], utc=True)
    rows: list[dict[str, Any]] = []
    for _, event in events.iterrows():
        row = event.to_dict()
        date = pd.Timestamp(event["signal_date"])
        price = float(event["btc_close"])
        for horizon in (7, 30, 90):
            mae, mfe = _future_excursion(daily, date, price, horizon)
            row[f"btc_{horizon}d_mae"] = mae
            row[f"btc_{horizon}d_mfe"] = mfe
        rows.append(row)
    return pd.DataFrame(rows)


def buy_sell_conflict_audit(trades: pd.DataFrame, window_days: int = 7) -> pd.DataFrame:
    tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if tactical.empty:
        return pd.DataFrame(columns=["strategy", "conflict_type", "prior_timestamp", "later_timestamp"])
    events = tactical.groupby(["strategy", "tactical_event_id"], as_index=False).agg(
        timestamp=("timestamp", "min"), action=("action", "first"), side=("side", "first"),
        reason=("reason", "first"), signal_date=("signal_date", "first"),
        cycle_id=("sell_cycle_id", "first"), invalidation=("bearish_invalidation", "max"),
    )
    events["timestamp"] = pd.to_datetime(events["timestamp"], utc=True)
    rows: list[dict[str, Any]] = []
    for strategy, group in events.groupby("strategy"):
        ordered = group.sort_values("timestamp").reset_index(drop=True)
        for _, prior in ordered.iterrows():
            later = ordered.loc[
                (ordered["timestamp"] > prior["timestamp"])
                & (ordered["timestamp"] <= prior["timestamp"] + pd.Timedelta(days=window_days))
            ]
            if prior["side"] == "BUY":
                conflicts = later.loc[later["action"].eq("TACTICAL_SELL_DRIFT") & ~later["invalidation"].astype(bool)]
                conflict_type = "BUY_THEN_ORDINARY_DRIFT_SELL_WITHIN_7D"
            else:
                conflicts = later.loc[
                    later["side"].eq("BUY")
                    & ((later["reason"].eq(prior["reason"])) | (later["signal_date"].eq(prior["signal_date"])))
                ]
                conflict_type = "SELL_THEN_SAME_SIGNAL_BUY_WITHIN_7D"
            for _, item in conflicts.iterrows():
                rows.append(
                    {
                        "strategy": strategy,
                        "conflict_type": conflict_type,
                        "prior_timestamp": prior["timestamp"],
                        "prior_action": prior["action"],
                        "prior_reason": prior["reason"],
                        "later_timestamp": item["timestamp"],
                        "later_action": item["action"],
                        "later_reason": item["reason"],
                        "cycle_id": item["cycle_id"],
                    }
                )
    return pd.DataFrame(rows, columns=[
        "strategy", "conflict_type", "prior_timestamp", "prior_action", "prior_reason",
        "later_timestamp", "later_action", "later_reason", "cycle_id",
    ])
