from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .metrics import calculate_summary


ASSETS = ("BTC", "ETH", "BNB")


@dataclass(frozen=True)
class Scenario:
    name: str
    capital_test: str
    initial_capital: float
    initial_crypto_fraction: float
    dynamic_dca: bool = False
    tactical: bool = False
    annual_rebalance: bool = False
    cash_protection: bool = True
    sell_order: str = "overweight"
    fee: float = 0.001
    slippage: float = 0.0005
    cost_case: str = "primary"
    variant: str = "primary"
    dca_mid: float | None = None
    dca_low: float | None = None


@dataclass
class PortfolioState:
    qty: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS})
    normal_cash: float = 0.0
    tactical_cash: float = 0.0
    pending: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS})
    sell_stage: int = 0
    overheat_seen: bool = False
    last_signal_date: Any = None
    cycle_reference_value: float = 0.0
    buyback_done: dict[str, bool] = field(
        default_factory=lambda: {
            "ahr_030_035": False,
            "ahr_below_030": False,
            "ahr_extreme": False,
            "right_confirmation": False,
        }
    )


@dataclass
class BacktestResult:
    scenario: Scenario
    summary: dict[str, Any]
    history: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    counters: dict[str, Any]


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _crypto_values(state: PortfolioState, prices: dict[str, float]) -> dict[str, float]:
    return {asset: state.qty[asset] * prices[asset] for asset in ASSETS}


def _portfolio_value(state: PortfolioState, prices: dict[str, float]) -> float:
    return sum(_crypto_values(state, prices).values()) + state.normal_cash + state.tactical_cash + sum(state.pending.values())


def _allocations(state: PortfolioState, prices: dict[str, float]) -> dict[str, float]:
    values = _crypto_values(state, prices)
    total = sum(values.values())
    if total <= 0:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: values[asset] / total for asset in ASSETS}


def _append_trade(
    trade_rows: list[dict[str, Any]],
    *,
    timestamp: pd.Timestamp,
    scenario: Scenario,
    action: str,
    side: str,
    asset: str,
    quantity: float,
    raw_price: float,
    effective_price: float,
    gross_notional: float,
    cash_change: float,
    fee_usd: float,
    slippage_usd: float,
    ledger: str,
    sell_stage: int,
    signal_date: Any,
) -> None:
    trade_rows.append(
        {
            "timestamp": timestamp,
            "capital_test": scenario.capital_test,
            "strategy": scenario.name,
            "variant": scenario.variant,
            "cost_case": scenario.cost_case,
            "action": action,
            "side": side,
            "asset": asset,
            "quantity": quantity,
            "raw_open_price": raw_price,
            "effective_price": effective_price,
            "gross_notional_usd": gross_notional,
            "cash_change_usd": cash_change,
            "fee_usd": fee_usd,
            "slippage_usd": slippage_usd,
            "cost_usd": fee_usd + slippage_usd,
            "ledger": ledger,
            "sell_stage": sell_stage,
            "signal_date": signal_date,
        }
    )


def _buy(
    state: PortfolioState,
    asset: str,
    budget: float,
    price: float,
    *,
    timestamp: pd.Timestamp,
    scenario: Scenario,
    action: str,
    ledger: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
) -> float:
    if budget <= 0 or price <= 0:
        return 0.0
    if ledger == "normal":
        budget = min(budget, state.normal_cash)
    elif ledger == "tactical":
        budget = min(budget, state.tactical_cash)
    elif ledger == "pending":
        budget = min(budget, state.pending[asset])
    else:
        raise ValueError(f"Unknown buy ledger: {ledger}")
    if budget <= 0:
        return 0.0
    effective_price = price * (1.0 + scenario.slippage)
    quantity = budget / (effective_price * (1.0 + scenario.fee))
    gross = quantity * price
    slippage_cost = quantity * (effective_price - price)
    fee_cost = quantity * effective_price * scenario.fee
    if ledger == "normal":
        state.normal_cash -= budget
    elif ledger == "tactical":
        state.tactical_cash -= budget
    else:
        state.pending[asset] -= budget
    state.qty[asset] += quantity
    _append_trade(
        trade_rows,
        timestamp=timestamp,
        scenario=scenario,
        action=action,
        side="BUY",
        asset=asset,
        quantity=quantity,
        raw_price=price,
        effective_price=effective_price,
        gross_notional=gross,
        cash_change=-budget,
        fee_usd=fee_cost,
        slippage_usd=slippage_cost,
        ledger=ledger,
        sell_stage=state.sell_stage,
        signal_date=signal_date,
    )
    return budget


def _sell(
    state: PortfolioState,
    asset: str,
    gross_notional: float,
    price: float,
    *,
    timestamp: pd.Timestamp,
    scenario: Scenario,
    action: str,
    ledger: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
) -> float:
    available_gross = state.qty[asset] * price
    gross = min(max(gross_notional, 0.0), available_gross)
    if gross <= 0 or price <= 0:
        return 0.0
    quantity = gross / price
    effective_price = price * (1.0 - scenario.slippage)
    before_fee = quantity * effective_price
    fee_cost = before_fee * scenario.fee
    proceeds = before_fee - fee_cost
    slippage_cost = quantity * (price - effective_price)
    state.qty[asset] -= quantity
    if ledger == "tactical":
        state.tactical_cash += proceeds
    elif ledger == "normal":
        state.normal_cash += proceeds
    else:
        raise ValueError(f"Unknown sell ledger: {ledger}")
    _append_trade(
        trade_rows,
        timestamp=timestamp,
        scenario=scenario,
        action=action,
        side="SELL",
        asset=asset,
        quantity=quantity,
        raw_price=price,
        effective_price=effective_price,
        gross_notional=gross,
        cash_change=proceeds,
        fee_usd=fee_cost,
        slippage_usd=slippage_cost,
        ledger=ledger,
        sell_stage=state.sell_stage,
        signal_date=signal_date,
    )
    return proceeds


def _rank_sell_assets(
    state: PortfolioState,
    prices: dict[str, float],
    rules: dict[str, Any],
    row: pd.Series,
    mode: str,
) -> list[str]:
    alloc = _allocations(state, prices)
    if mode == "overweight_weakness":
        def score(asset: str) -> tuple[float, float]:
            weakness = row.get(f"{asset}_weakness_score", 0.0)
            weakness = float(weakness) if pd.notna(weakness) else 0.0
            deviation = alloc[asset] - rules["target_weights"][asset]
            return (2.0 * weakness + deviation, deviation)
        return sorted(ASSETS, key=score, reverse=True)
    return sorted(
        ASSETS,
        key=lambda asset: alloc[asset] - rules["target_weights"][asset],
        reverse=True,
    )


def _sell_to_stage_target(
    state: PortfolioState,
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: Scenario,
    trade_rows: list[dict[str, Any]],
) -> None:
    target = float(rules["sell_stage_targets"][str(state.sell_stage)])
    sleeve = sum(_crypto_values(state, prices).values()) + state.tactical_cash
    desired_tactical = target * sleeve
    proceeds_needed = max(0.0, desired_tactical - state.tactical_cash)
    if proceeds_needed <= 1e-9:
        return
    conversion = (1.0 - scenario.slippage) * (1.0 - scenario.fee)
    gross_needed = proceeds_needed / conversion
    for asset in _rank_sell_assets(state, prices, rules, row, scenario.sell_order):
        if gross_needed <= 1e-8:
            break
        available = state.qty[asset] * prices[asset]
        gross = min(available, gross_needed)
        proceeds = _sell(
            state,
            asset,
            gross,
            prices[asset],
            timestamp=row["open_time"],
            scenario=scenario,
            action=f"TACTICAL_SELL_STAGE_{state.sell_stage}",
            ledger="tactical",
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
        gross_needed -= proceeds / conversion


def _buy_underweight(
    state: PortfolioState,
    budget: float,
    prices: dict[str, float],
    rules: dict[str, Any],
    *,
    row: pd.Series,
    scenario: Scenario,
    action: str,
    ledger: str,
    trade_rows: list[dict[str, Any]],
) -> float:
    if budget <= 0:
        return 0.0
    values = _crypto_values(state, prices)
    post_total = sum(values.values()) + budget
    gaps = {
        asset: max(0.0, rules["target_weights"][asset] * post_total - values[asset])
        for asset in ASSETS
    }
    remaining = budget
    spent = 0.0
    for asset in sorted(ASSETS, key=lambda x: gaps[x], reverse=True):
        if remaining <= 1e-9:
            break
        amount = min(remaining, gaps[asset] if gaps[asset] > 0 else remaining)
        used = _buy(
            state,
            asset,
            amount,
            prices[asset],
            timestamp=row["open_time"],
            scenario=scenario,
            action=action,
            ledger=ledger,
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
        spent += used
        remaining -= used
    if remaining > 1e-8:
        asset = min(
            ASSETS,
            key=lambda x: _allocations(state, prices)[x] - rules["target_weights"][x],
        )
        spent += _buy(
            state,
            asset,
            remaining,
            prices[asset],
            timestamp=row["open_time"],
            scenario=scenario,
            action=action,
            ledger=ledger,
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
    return spent


def _reset_cycle(state: PortfolioState) -> None:
    state.sell_stage = 0
    state.overheat_seen = False
    state.cycle_reference_value = 0.0
    state.buyback_done = {
        "ahr_030_035": False,
        "ahr_below_030": False,
        "ahr_extreme": False,
        "right_confirmation": False,
    }


def _process_signal(
    state: PortfolioState,
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: Scenario,
    trade_rows: list[dict[str, Any]],
    counters: dict[str, Any],
) -> tuple[str, list[str]]:
    actions: list[str] = []
    stage_action = ""
    overheat_before = state.overheat_seen
    old_stage = state.sell_stage
    if scenario.dynamic_dca or scenario.tactical:
        if old_stage == 0 and overheat_before and _truth(row.get("stage1_condition")):
            state.sell_stage = 1
        elif old_stage == 1 and _truth(row.get("stage2_condition")):
            state.sell_stage = 2
        elif old_stage == 2 and _truth(row.get("stage3_condition")):
            state.sell_stage = 3
        elif old_stage == 3 and _truth(row.get("stage4_condition")):
            state.sell_stage = 4
        if _truth(row.get("overheat_gate")):
            state.overheat_seen = True
        if state.sell_stage > old_stage:
            stage_action = f"STAGE_{state.sell_stage}"
            counters[f"sell_stage_{state.sell_stage}_count"] += 1
            if scenario.tactical:
                if old_stage == 0:
                    state.cycle_reference_value = sum(_crypto_values(state, prices).values()) + state.tactical_cash
                _sell_to_stage_target(state, row, prices, rules, scenario, trade_rows)
            actions.append(stage_action)

    if scenario.tactical and state.tactical_cash > 1e-9:
        ahr = row.get("ahr999_fixed_arithmetic", np.nan)
        minimum = min(rules["modeled_min_notional_usdt"].values())
        triggers: list[str] = []
        if pd.notna(ahr) and 0.30 <= float(ahr) <= 0.35 and not state.buyback_done["ahr_030_035"]:
            triggers.append("ahr_030_035")
        if pd.notna(ahr) and float(ahr) < 0.30 and not state.buyback_done["ahr_below_030"]:
            triggers.append("ahr_below_030")
        extreme_gate = _truth(row.get("BTC_daily_close", np.nan) < row.get("bb_lower", np.nan)) or (
            pd.notna(row.get("close_sma200_dev")) and float(row.get("close_sma200_dev")) <= -0.15
        )
        if pd.notna(ahr) and float(ahr) <= 0.28 and extreme_gate and not state.buyback_done["ahr_extreme"]:
            triggers.append("ahr_extreme")
        prior_undervaluation_buy = any(
            state.buyback_done[key]
            for key in ("ahr_030_035", "ahr_below_030", "ahr_extreme")
        )
        if (
            prior_undervaluation_buy
            and _truth(row.get("right_confirmation"))
            and not state.buyback_done["right_confirmation"]
        ):
            triggers.append("right_confirmation")
        right_executed = False
        for trigger in triggers:
            current_sleeve_value = sum(_crypto_values(state, prices).values()) + state.tactical_cash
            max_budget = rules["buyback_tranches"][trigger] * current_sleeve_value
            budget = min(state.tactical_cash, max_budget)
            if budget >= minimum:
                _buy_underweight(
                    state,
                    budget,
                    prices,
                    rules,
                    row=row,
                    scenario=scenario,
                    action=f"TACTICAL_BUYBACK_{trigger.upper()}",
                    ledger="tactical",
                    trade_rows=trade_rows,
                )
                state.buyback_done[trigger] = True
                counters[f"{trigger}_buy_count" if trigger != "right_confirmation" else "right_confirmation_count"] += 1
                actions.append(f"BUYBACK_{trigger}")
                right_executed = right_executed or trigger == "right_confirmation"
        if right_executed or (state.tactical_cash < minimum and any(state.buyback_done.values())):
            _reset_cycle(state)
            actions.append("CYCLE_RESET")
    return stage_action, actions


def _dca_rate(state: PortfolioState, row: pd.Series, rules: dict[str, Any], scenario: Scenario) -> float:
    if not scenario.dynamic_dca:
        return float(rules["external_contribution_per_4h"])
    rates = rules["dca_rates"]
    if state.sell_stage >= 1:
        theoretical = rates["sell_stage"]
    elif _truth(row.get("overheat_gate")):
        theoretical = rates["overheat_pre_sell"]
    else:
        ahr = row.get("ahr999_fixed_arithmetic", np.nan)
        if pd.notna(ahr) and float(ahr) < 0.30:
            theoretical = scenario.dca_low if scenario.dca_low is not None else rates["ahr_below_030"]
        elif pd.notna(ahr) and 0.30 <= float(ahr) <= 0.35:
            theoretical = scenario.dca_mid if scenario.dca_mid is not None else rates["ahr_030_035"]
        else:
            theoretical = rates["normal"]
    return float(min(theoretical, rates["hard_max"]))


def _cash_cap(cash_ratio: float, rules: dict[str, Any]) -> float:
    for band in rules["cash_protection_caps"]:
        if cash_ratio >= float(band["min_ratio"]):
            return float(band["max_dca"])
    return 1.0


def _commit_and_execute_dca(
    state: PortfolioState,
    amount: float,
    prices: dict[str, float],
    row: pd.Series,
    rules: dict[str, Any],
    scenario: Scenario,
    trade_rows: list[dict[str, Any]],
) -> tuple[float, float]:
    committed = min(max(amount, 0.0), state.normal_cash)
    if committed <= 0:
        return 0.0, 0.0
    alloc = _allocations(state, prices)
    within = all(
        abs(alloc[asset] - rules["target_weights"][asset]) <= rules["allocation_tolerance"]
        for asset in ASSETS
    )
    if within:
        allocation = {asset: committed * rules["target_weights"][asset] for asset in ASSETS}
    else:
        most_underweight = min(
            ASSETS,
            key=lambda asset: alloc[asset] - rules["target_weights"][asset],
        )
        allocation = {asset: committed if asset == most_underweight else 0.0 for asset in ASSETS}
    state.normal_cash -= committed
    for asset, value in allocation.items():
        state.pending[asset] += value

    executed = 0.0
    for asset in ASSETS:
        minimum = float(rules["modeled_min_notional_usdt"][asset])
        if state.pending[asset] + 1e-10 >= minimum:
            budget = state.pending[asset]
            executed += _buy(
                state,
                asset,
                budget,
                prices[asset],
                timestamp=row["open_time"],
                scenario=scenario,
                action="NORMAL_DCA",
                ledger="pending",
                trade_rows=trade_rows,
                signal_date=row.get("signal_date"),
            )
    return committed, executed


def _annual_rebalance(
    state: PortfolioState,
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: Scenario,
    trade_rows: list[dict[str, Any]],
) -> None:
    values = _crypto_values(state, prices)
    total = sum(values.values())
    if total <= 0:
        return
    proceeds = 0.0
    for asset in ASSETS:
        target = rules["target_weights"][asset] * total
        excess = values[asset] - target
        if excess >= rules["modeled_min_notional_usdt"][asset]:
            proceeds += _sell(
                state,
                asset,
                excess,
                prices[asset],
                timestamp=row["open_time"],
                scenario=scenario,
                action="ANNUAL_REBALANCE",
                ledger="normal",
                trade_rows=trade_rows,
                signal_date=row.get("signal_date"),
            )
    available = min(proceeds, state.normal_cash)
    if available > 0:
        _buy_underweight(
            state,
            available,
            prices,
            rules,
            row=row,
            scenario=scenario,
            action="ANNUAL_REBALANCE",
            ledger="normal",
            trade_rows=trade_rows,
        )


def run_backtest(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: Scenario,
    *,
    record_signals: bool = True,
) -> BacktestResult:
    if frame.empty:
        raise ValueError("No 4H bars supplied")
    state = PortfolioState(normal_cash=float(scenario.initial_capital))
    trade_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    counters: dict[str, Any] = {
        "sell_stage_1_count": 0,
        "sell_stage_2_count": 0,
        "sell_stage_3_count": 0,
        "sell_stage_4_count": 0,
        "ahr_030_035_buy_count": 0,
        "ahr_below_030_buy_count": 0,
        "ahr_extreme_buy_count": 0,
        "right_confirmation_count": 0,
        "dca_cash_protection_slowdowns": 0,
        "dca_cash_shortfall_count": 0,
        "ever_normal_cash_zero": False,
        "first_normal_cash_depletion": "",
    }
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS}
    initial_crypto_budget = scenario.initial_capital * scenario.initial_crypto_fraction
    for asset in ASSETS:
        _buy(
            state,
            asset,
            initial_crypto_budget * rules["target_weights"][asset],
            first_prices[asset],
            timestamp=first["open_time"],
            scenario=scenario,
            action="INITIAL_ALLOCATION",
            ledger="normal",
            trade_rows=trade_rows,
            signal_date=first.get("signal_date"),
        )

    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    unit_nav = 1.0
    peak_nav = 1.0
    previous_year: int | None = None
    base_periodic_flow = float(rules["external_contribution_per_4h"])
    previous_timestamp: pd.Timestamp | None = None

    for _, row in frame.iterrows():
        timestamp = row["open_time"]
        elapsed_intervals = (
            1
            if previous_timestamp is None
            else max(1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4))))
        )
        periodic_flow = base_periodic_flow * elapsed_intervals
        open_prices = {asset: float(row[f"{asset}_open"]) for asset in ASSETS}
        close_prices = {asset: float(row[f"{asset}_close"]) for asset in ASSETS}
        state.normal_cash += periodic_flow

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        stage_action = ""
        signal_actions: list[str] = []
        if is_new_signal:
            stage_action, signal_actions = _process_signal(
                state, row, open_prices, rules, scenario, trade_rows, counters
            )
            state.last_signal_date = row.get("signal_date")

        year = timestamp.year
        if scenario.annual_rebalance and previous_year is not None and year != previous_year:
            _annual_rebalance(state, row, open_prices, rules, scenario, trade_rows)
            signal_actions.append("ANNUAL_REBALANCE")
        previous_year = year

        value_before_dca = _portfolio_value(state, open_prices)
        cash_ratio_before = state.normal_cash / value_before_dca if value_before_dca > 0 else 0.0
        theoretical = _dca_rate(state, row, rules, scenario)
        protected = theoretical
        if scenario.dynamic_dca and scenario.cash_protection:
            protected = min(theoretical, _cash_cap(cash_ratio_before, rules))
            if protected + 1e-12 < theoretical:
                counters["dca_cash_protection_slowdowns"] += elapsed_intervals
        # During a missing common market bar, contributions and intended DCA
        # accumulate; execution waits for the next real cross-asset 4H open.
        committed_request = protected * elapsed_intervals
        if state.normal_cash + 1e-12 < committed_request:
            counters["dca_cash_shortfall_count"] += 1
            if not counters["first_normal_cash_depletion"]:
                counters["first_normal_cash_depletion"] = timestamp.isoformat()
        committed, executed = _commit_and_execute_dca(
            state,
            committed_request,
            open_prices,
            row,
            rules,
            scenario,
            trade_rows,
        )
        if state.normal_cash <= 1e-10:
            counters["ever_normal_cash_zero"] = True

        end_value = _portfolio_value(state, close_prices)
        denominator = previous_value + periodic_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        allocations = _allocations(state, close_prices)
        total_pending = sum(state.pending.values())
        normal_ratio = state.normal_cash / end_value if end_value > 0 else 0.0
        total_cash = state.normal_cash + total_pending + state.tactical_cash
        total_cash_ratio = total_cash / end_value if end_value > 0 else 0.0
        tactical_ratio = state.tactical_cash / end_value if end_value > 0 else 0.0
        if previous_closes is None:
            target_return = 0.0
        else:
            target_return = sum(
                rules["target_weights"][asset] * (close_prices[asset] / previous_closes[asset] - 1.0)
                for asset in ASSETS
            )
        cash_drag_increment = total_cash_ratio * target_return
        history_rows.append(
            {
                "timestamp": timestamp,
                "portfolio_value": end_value,
                "unit_nav": unit_nav,
                "drawdown": drawdown,
                "twr_return": twr_return,
                "external_flow": periodic_flow,
                "elapsed_4h_intervals": elapsed_intervals,
                "normal_cash": state.normal_cash,
                "pending_dca_cash": total_pending,
                "tactical_cash": state.tactical_cash,
                "normal_cash_ratio": normal_ratio,
                "total_cash_ratio": total_cash_ratio,
                "tactical_cash_ratio": tactical_ratio,
                "sell_stage": state.sell_stage,
                "theoretical_dca": theoretical,
                "protected_dca": protected,
                "committed_dca": committed,
                "executed_dca": executed,
                "BTC_allocation": allocations["BTC"],
                "ETH_allocation": allocations["ETH"],
                "BNB_allocation": allocations["BNB"],
                "BTC_close": close_prices["BTC"],
                "ETH_close": close_prices["ETH"],
                "BNB_close": close_prices["BNB"],
                "ahr999": row.get("ahr999_fixed_arithmetic", np.nan),
                "target_basket_return": target_return,
                "cash_drag_increment": cash_drag_increment,
            }
        )
        if is_new_signal and record_signals:
            signal_rows.append(
                {
                    "signal_date": row.get("signal_date"),
                    "signal_available_at": row.get("signal_available_at"),
                    "execution_4h_open": timestamp,
                    "daily_source": row.get("daily_source"),
                    "btc_close": row.get("BTC_daily_close"),
                    "sma10": row.get("sma10"),
                    "sma20": row.get("sma20"),
                    "sma50": row.get("sma50"),
                    "sma200": row.get("sma200"),
                    "bollinger_upper": row.get("bb_upper"),
                    "bollinger_lower": row.get("bb_lower"),
                    "ahr999": row.get("ahr999_fixed_arithmetic"),
                    "overheat_gate": row.get("overheat_gate"),
                    "overheat_count": row.get("overheat_count"),
                    "long_upper_wick": row.get("long_upper_wick"),
                    "failed_breakout": row.get("failed_breakout"),
                    "stage1_condition": row.get("stage1_condition"),
                    "stage2_condition": row.get("stage2_condition"),
                    "stage3_condition": row.get("stage3_condition"),
                    "stage4_condition": row.get("stage4_condition"),
                    "right_confirmation": row.get("right_confirmation"),
                    "stage_action": stage_action,
                    "actions": "|".join(signal_actions),
                    "resulting_sell_stage": state.sell_stage,
                    "tactical_cash_after": state.tactical_cash,
                }
            )
        previous_value = end_value
        previous_closes = close_prices
        previous_timestamp = timestamp

    history = pd.DataFrame(history_rows)
    trades = pd.DataFrame(trade_rows)
    signals = pd.DataFrame(signal_rows)
    summary = calculate_summary(
        history,
        trades,
        scenario=scenario,
        counters=counters,
        rules=rules,
    )
    return BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history,
        trades=trades,
        signals=signals,
        counters=counters,
    )
