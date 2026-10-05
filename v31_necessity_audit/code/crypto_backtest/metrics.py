from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


def _xnpv(rate: float, cashflows: np.ndarray, years: np.ndarray) -> float:
    if rate <= -1.0:
        return np.inf
    return float(np.sum(cashflows / np.power(1.0 + rate, years)))


def xirr(timestamps: pd.Series, cashflows: np.ndarray) -> float:
    times = pd.to_datetime(timestamps, utc=True)
    years = (times - times.iloc[0]).dt.total_seconds().to_numpy() / (365.25 * 86_400.0)
    values = np.asarray(cashflows, dtype=float)
    if not ((values < 0).any() and (values > 0).any()):
        return float("nan")
    low, high = -0.9999, 10.0
    f_low = _xnpv(low, values, years)
    f_high = _xnpv(high, values, years)
    while np.sign(f_low) == np.sign(f_high) and high < 1e8:
        high *= 10.0
        f_high = _xnpv(high, values, years)
    if np.sign(f_low) == np.sign(f_high):
        return float("nan")
    for _ in range(200):
        mid = (low + high) / 2.0
        f_mid = _xnpv(mid, values, years)
        if abs(f_mid) < 1e-8:
            return mid
        if np.sign(f_mid) == np.sign(f_low):
            low, f_low = mid, f_mid
        else:
            high = mid
    return (low + high) / 2.0


def calculate_summary(
    history: pd.DataFrame,
    trades: pd.DataFrame,
    *,
    scenario: Any,
    counters: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    if history.empty:
        raise ValueError("Backtest history is empty")
    first_ts = history["timestamp"].iloc[0]
    last_ts = history["timestamp"].iloc[-1]
    elapsed_years = max(
        (last_ts - first_ts).total_seconds() / (rules["annual_days"] * 86_400.0),
        1.0 / (rules["annual_days"] * rules["bars_per_day"]),
    )
    returns = history["twr_return"].replace([np.inf, -np.inf], np.nan).dropna()
    annual_factor = rules["annual_days"] * rules["bars_per_day"]
    twr_cagr = float(history["unit_nav"].iloc[-1] ** (1.0 / elapsed_years) - 1.0)
    ann_vol = float(returns.std(ddof=1) * np.sqrt(annual_factor)) if len(returns) > 1 else float("nan")
    mean_ann = float(returns.mean() * annual_factor) if len(returns) else float("nan")
    sharpe = mean_ann / ann_vol if ann_vol and np.isfinite(ann_vol) else float("nan")
    downside = returns.loc[returns < 0]
    downside_dev = float(np.sqrt((downside.pow(2).mean())) * np.sqrt(annual_factor)) if len(downside) else float("nan")
    sortino = mean_ann / downside_dev if downside_dev and np.isfinite(downside_dev) else float("nan")
    max_dd = float(history["drawdown"].min())
    calmar = twr_cagr / abs(max_dd) if max_dd < 0 else float("nan")
    ulcer = float(np.sqrt(np.mean(np.square(history["drawdown"].to_numpy(dtype=float)))))

    initial = float(scenario.initial_capital)
    periodic = float(history["external_flow"].sum())
    total_contributions = initial + periodic
    final_value = float(history["portfolio_value"].iloc[-1])
    net_profit = final_value - total_contributions
    flow_times = pd.concat(
        [
            pd.Series([first_ts]),
            history["timestamp"].reset_index(drop=True),
            pd.Series([last_ts]),
        ],
        ignore_index=True,
    )
    flow_values = np.r_[ -initial, -history["external_flow"].to_numpy(dtype=float), final_value]
    money_weighted = xirr(flow_times, flow_values)

    if trades.empty:
        turnover_notional = 0.0
        trading_costs = 0.0
    else:
        turnover_notional = float(trades["gross_notional_usd"].sum())
        trading_costs = float(trades["cost_usd"].sum())
    average_value = float(history["portfolio_value"].mean())
    turnover = turnover_notional / average_value if average_value else float("nan")
    cash_drag_factor = float(np.prod(1.0 + history["cash_drag_increment"].fillna(0.0).clip(lower=-0.999999)) - 1.0)

    summary = {
        "capital_test": scenario.capital_test,
        "strategy": scenario.name,
        "variant": scenario.variant,
        "cost_case": scenario.cost_case,
        "cash_protection": scenario.cash_protection,
        "sell_order": scenario.sell_order,
        "start": first_ts.isoformat(),
        "end": last_ts.isoformat(),
        "initial_capital": initial,
        "periodic_external_contributions": periodic,
        "external_contributions": total_contributions,
        "final_portfolio_value": final_value,
        "net_profit": net_profit,
        "xirr": money_weighted,
        "time_weighted_cagr": twr_cagr,
        "maximum_drawdown": max_dd,
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
        "sortino": sortino,
        "calmar": calmar,
        "ulcer_index": ulcer,
        "turnover": turnover,
        "total_trading_costs": trading_costs,
        "average_cash_ratio": float(history["normal_cash_ratio"].mean()),
        "minimum_cash_ratio": float(history["normal_cash_ratio"].min()),
        "average_total_cash_ratio": float(history["total_cash_ratio"].mean()),
        "average_tactical_cash": float(history["tactical_cash"].mean()),
        "average_tactical_cash_ratio": float(history["tactical_cash_ratio"].mean()),
        "time_in_tactical_cash": float((history["tactical_cash"] > 1e-9).mean()),
        "cash_drag": cash_drag_factor,
        "cash_drag_usd_approx": cash_drag_factor * average_value,
        "sell_stage_1_count": int(counters.get("sell_stage_1_count", 0)),
        "sell_stage_2_count": int(counters.get("sell_stage_2_count", 0)),
        "sell_stage_3_count": int(counters.get("sell_stage_3_count", 0)),
        "sell_stage_4_count": int(counters.get("sell_stage_4_count", 0)),
        "ahr_030_035_buy_count": int(counters.get("ahr_030_035_buy_count", 0)),
        "ahr_below_030_buy_count": int(counters.get("ahr_below_030_buy_count", 0)),
        "ahr_extreme_buy_count": int(counters.get("ahr_extreme_buy_count", 0)),
        "right_confirmation_count": int(counters.get("right_confirmation_count", 0)),
        "dca_cash_protection_slowdowns": int(counters.get("dca_cash_protection_slowdowns", 0)),
        "dca_cash_shortfall_count": int(counters.get("dca_cash_shortfall_count", 0)),
        "ever_normal_cash_zero": bool(counters.get("ever_normal_cash_zero", False)),
        "first_normal_cash_depletion": counters.get("first_normal_cash_depletion", ""),
    }
    return summary


def daily_history(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = work["timestamp"].dt.floor("D")
    aggregations = {
        "portfolio_value": "last",
        "unit_nav": "last",
        "drawdown": "last",
        "normal_cash": "last",
        "pending_dca_cash": "last",
        "tactical_cash": "last",
        "normal_cash_ratio": "last",
        "total_cash_ratio": "last",
        "tactical_cash_ratio": "last",
        "sell_stage": "last",
        "theoretical_dca": "last",
        "protected_dca": "last",
        "committed_dca": "sum",
        "executed_dca": "sum",
        "BTC_allocation": "last",
        "ETH_allocation": "last",
        "BNB_allocation": "last",
        "BTC_close": "last",
        "ETH_close": "last",
        "BNB_close": "last",
        "ahr999": "last",
        "external_flow": "sum",
        "twr_return": lambda x: float(np.prod(1.0 + x) - 1.0),
    }
    return work.groupby("date", as_index=False).agg(aggregations)

