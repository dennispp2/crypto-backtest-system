from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .engine import ASSETS, BacktestResult
from .metrics import calculate_summary


@dataclass(frozen=True)
class HedgeScenario:
    name: str
    hard_floor: float
    initial_capital: float = 20_000.0
    initial_crypto_fraction: float = 0.7
    capital_test: str = "test2_v2"
    variant: str = "primary"
    cost_case: str = "primary"
    fee: float = 0.001
    slippage: float = 0.0005
    cash_protection: bool = False
    sell_order: str = "overweight_with_bnb_tie_break"


@dataclass
class HedgeState:
    qty: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS})
    normal_cash: float = 0.0
    pending_dca_cash: float = 0.0
    tactical_cash: float = 0.0
    sell_stage: int = 0
    regime: str = "BULL"
    overheat_armed: bool = False
    arm_date: Any = None
    bull_start_date: Any = None
    last_signal_date: Any = None
    strong_confirmation_streak: int = 0
    active_cycle_id: int = 0
    next_cycle_id: int = 1
    buyback_done: dict[str, bool] = field(
        default_factory=lambda: {
            "ahr_030_035": False,
            "ahr_below_030": False,
            "ahr_extreme": False,
            "right_confirmation": False,
        }
    )


@dataclass
class V2BacktestResult:
    scenario: HedgeScenario
    summary: dict[str, Any]
    history: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    cycles: pd.DataFrame
    counters: dict[str, Any]


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _crypto_values(state: HedgeState, prices: dict[str, float]) -> dict[str, float]:
    return {asset: state.qty[asset] * prices[asset] for asset in ASSETS}


def _portfolio_value(state: HedgeState, prices: dict[str, float]) -> float:
    return (
        sum(_crypto_values(state, prices).values())
        + state.normal_cash
        + state.pending_dca_cash
        + state.tactical_cash
    )


def _crypto_exposure(state: HedgeState, prices: dict[str, float]) -> float:
    total = _portfolio_value(state, prices)
    return sum(_crypto_values(state, prices).values()) / total if total > 0 else 0.0


def _crypto_allocations(state: HedgeState, prices: dict[str, float]) -> dict[str, float]:
    values = _crypto_values(state, prices)
    total = sum(values.values())
    if total <= 0:
        return {asset: 0.0 for asset in ASSETS}
    return {asset: values[asset] / total for asset in ASSETS}


def _effective_stage_band(
    rules_v2: dict[str, Any], stage: int, hard_floor: float
) -> tuple[float, float, float]:
    base = rules_v2["stage_exposure"][str(stage)]
    base_target = float(base["target"])
    base_lower = float(base["lower"])
    base_upper = float(base["upper"])
    target = max(base_target, hard_floor)
    lower = max(base_lower, hard_floor)
    # Preserve the frozen target-to-upper slack when a sensitivity floor binds.
    upper = max(base_upper, target + max(0.0, base_upper - base_target))
    return target, lower, min(1.0, upper)


def _append_trade(
    rows: list[dict[str, Any]],
    *,
    state: HedgeState,
    prices: dict[str, float],
    timestamp: pd.Timestamp,
    scenario: HedgeScenario,
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
    signal_date: Any,
) -> None:
    rows.append(
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
            "sell_stage": state.sell_stage,
            "cycle_regime": state.regime,
            "sell_cycle_id": state.active_cycle_id,
            "signal_date": signal_date,
            "post_trade_crypto_exposure": _crypto_exposure(state, prices),
            "normal_cash_after": state.normal_cash,
            "pending_dca_cash_after": state.pending_dca_cash,
            "tactical_cash_after": state.tactical_cash,
        }
    )


def _buy(
    state: HedgeState,
    asset: str,
    budget: float,
    price: float,
    prices: dict[str, float],
    *,
    timestamp: pd.Timestamp,
    scenario: HedgeScenario,
    action: str,
    ledger: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
) -> float:
    if budget <= 0 or price <= 0:
        return 0.0
    if ledger == "normal":
        budget = min(budget, state.normal_cash)
    elif ledger == "pending":
        budget = min(budget, state.pending_dca_cash)
    elif ledger == "tactical":
        budget = min(budget, state.tactical_cash)
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
    elif ledger == "pending":
        state.pending_dca_cash -= budget
    else:
        state.tactical_cash -= budget
    state.qty[asset] += quantity
    _append_trade(
        trade_rows,
        state=state,
        prices=prices,
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
        signal_date=signal_date,
    )
    return budget


def _sell(
    state: HedgeState,
    asset: str,
    gross_notional: float,
    price: float,
    prices: dict[str, float],
    *,
    timestamp: pd.Timestamp,
    scenario: HedgeScenario,
    action: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
) -> float:
    available = state.qty[asset] * price
    gross = min(max(0.0, gross_notional), available)
    if gross <= 0 or price <= 0:
        return 0.0
    quantity = gross / price
    effective_price = price * (1.0 - scenario.slippage)
    before_fee = quantity * effective_price
    fee_cost = before_fee * scenario.fee
    proceeds = before_fee - fee_cost
    slippage_cost = quantity * (price - effective_price)
    state.qty[asset] -= quantity
    state.tactical_cash += proceeds
    _append_trade(
        trade_rows,
        state=state,
        prices=prices,
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
        ledger="tactical",
        signal_date=signal_date,
    )
    return gross


def _rank_sell_assets(
    state: HedgeState,
    prices: dict[str, float],
    rules_v2: dict[str, Any],
) -> list[str]:
    allocations = _crypto_allocations(state, prices)
    weights = rules_v2["target_weights"]
    secondary = {
        asset: len(rules_v2["secondary_sell_priority"]) - rank
        for rank, asset in enumerate(rules_v2["secondary_sell_priority"])
    }
    return sorted(
        ASSETS,
        key=lambda asset: (allocations[asset] - float(weights[asset]), secondary[asset]),
        reverse=True,
    )


def _gross_to_target_exposure(
    state: HedgeState,
    prices: dict[str, float],
    target: float,
    scenario: HedgeScenario,
) -> float:
    crypto = sum(_crypto_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total <= target:
        return 0.0
    conversion = (1.0 - scenario.slippage) * (1.0 - scenario.fee)
    cost_fraction = 1.0 - conversion
    denominator = max(1e-12, 1.0 - target * cost_fraction)
    return max(0.0, (crypto - target * total) / denominator)


def _sell_to_exposure_target(
    state: HedgeState,
    row: pd.Series,
    prices: dict[str, float],
    target: float,
    rules_v2: dict[str, Any],
    scenario: HedgeScenario,
    trade_rows: list[dict[str, Any]],
    *,
    action: str,
) -> tuple[float, str]:
    target = max(float(target), scenario.hard_floor)
    gross_needed = _gross_to_target_exposure(state, prices, target, scenario)
    gross_floor_limit = _gross_to_target_exposure(state, prices, scenario.hard_floor, scenario)
    gross_needed = min(gross_needed, gross_floor_limit)
    if gross_needed <= 1e-10:
        reason = "hard_floor_binding" if _crypto_exposure(state, prices) > target + 1e-8 else "none"
        return 0.0, reason
    minimums = rules_v2["modeled_min_notional_usdt"]
    sold = 0.0
    for asset in _rank_sell_assets(state, prices, rules_v2):
        remaining = gross_needed - sold
        if remaining <= 1e-8:
            break
        available = state.qty[asset] * prices[asset]
        gross = min(available, remaining)
        minimum = float(minimums[asset])
        if gross + 1e-10 < minimum:
            continue
        sold += _sell(
            state,
            asset,
            gross,
            prices[asset],
            prices,
            timestamp=row["open_time"],
            scenario=scenario,
            action=action,
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
    if sold <= 1e-10:
        return 0.0, "minimum_notional"
    if _crypto_exposure(state, prices) + 1e-10 < scenario.hard_floor:
        raise AssertionError("Tactical sell breached the hard exposure floor")
    remaining = _gross_to_target_exposure(state, prices, target, scenario)
    return sold, ("minimum_notional" if remaining >= min(map(float, minimums.values())) else "none")


def _buy_underweight(
    state: HedgeState,
    budget: float,
    prices: dict[str, float],
    row: pd.Series,
    rules_v2: dict[str, Any],
    scenario: HedgeScenario,
    trade_rows: list[dict[str, Any]],
    *,
    action: str,
) -> float:
    budget = min(float(budget), state.tactical_cash)
    minimum = min(float(v) for v in rules_v2["modeled_min_notional_usdt"].values())
    if budget + 1e-10 < minimum:
        return 0.0
    values = _crypto_values(state, prices)
    conversion = 1.0 / ((1.0 + scenario.slippage) * (1.0 + scenario.fee))
    post_crypto = sum(values.values()) + budget * conversion
    gaps = {
        asset: max(0.0, float(rules_v2["target_weights"][asset]) * post_crypto - values[asset])
        for asset in ASSETS
    }
    remaining = budget
    spent = 0.0
    for asset in sorted(ASSETS, key=lambda a: gaps[a], reverse=True):
        if remaining + 1e-10 < minimum:
            break
        desired_market_value = gaps[asset]
        desired_budget = desired_market_value / conversion if desired_market_value > 0 else remaining
        amount = min(remaining, desired_budget)
        if amount + 1e-10 < minimum:
            continue
        used = _buy(
            state,
            asset,
            amount,
            prices[asset],
            prices,
            timestamp=row["open_time"],
            scenario=scenario,
            action=action,
            ledger="tactical",
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
        spent += used
        remaining -= used
    if remaining + 1e-10 >= minimum:
        allocations = _crypto_allocations(state, prices)
        asset = min(ASSETS, key=lambda a: allocations[a] - float(rules_v2["target_weights"][a]))
        spent += _buy(
            state,
            asset,
            remaining,
            prices[asset],
            prices,
            timestamp=row["open_time"],
            scenario=scenario,
            action=action,
            ledger="tactical",
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
        )
    return spent


def _budget_to_exposure_target(
    state: HedgeState,
    prices: dict[str, float],
    target: float,
    scenario: HedgeScenario,
) -> float:
    crypto = sum(_crypto_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total >= target:
        return 0.0
    conversion = 1.0 / ((1.0 + scenario.slippage) * (1.0 + scenario.fee))
    denominator = conversion + target * (1.0 - conversion)
    return max(0.0, (target * total - crypto) / max(denominator, 1e-12))


def _new_cycle_record(state: HedgeState, signal_date: Any) -> dict[str, Any]:
    cycle_id = state.next_cycle_id
    state.next_cycle_id += 1
    state.active_cycle_id = cycle_id
    return {
        "cycle_id": cycle_id,
        "cycle_start": state.arm_date if pd.notna(state.arm_date) else signal_date,
        "cycle_end": pd.NaT,
        "BULL_date": state.bull_start_date,
        "LATE_BULL_date": state.arm_date,
        "DISTRIBUTION_date": signal_date,
        "BEAR_date": pd.NaT,
        "DEEP_BEAR_date": pd.NaT,
        "ACCUMULATION_date": pd.NaT,
        "NEW_BULL_date": pd.NaT,
        "stage_1_date": signal_date,
        "stage_2_date": pd.NaT,
        "stage_3_date": pd.NaT,
        "stage_4_date": pd.NaT,
        "reset_date": pd.NaT,
        "redeployment_complete_date": pd.NaT,
        "status": "OPEN",
    }


def _set_regime(
    state: HedgeState,
    regime: str,
    signal_date: Any,
    active_cycle: dict[str, Any] | None,
) -> None:
    state.regime = regime
    if active_cycle is not None:
        key = f"{regime}_date"
        if key in active_cycle and pd.isna(active_cycle[key]):
            active_cycle[key] = signal_date


def _reset_cycle(
    state: HedgeState,
    signal_date: Any,
    active_cycle: dict[str, Any],
) -> None:
    active_cycle["cycle_end"] = signal_date
    if pd.isna(active_cycle["reset_date"]):
        active_cycle["reset_date"] = signal_date
    active_cycle["redeployment_complete_date"] = signal_date
    active_cycle["status"] = "CLOSED"
    state.sell_stage = 0
    state.regime = "BULL"
    state.overheat_armed = False
    state.arm_date = None
    state.bull_start_date = signal_date
    state.strong_confirmation_streak = 0
    state.active_cycle_id = 0
    state.buyback_done = {
        "ahr_030_035": False,
        "ahr_below_030": False,
        "ahr_extreme": False,
        "right_confirmation": False,
    }


def _process_daily_signal(
    state: HedgeState,
    row: pd.Series,
    prices: dict[str, float],
    rules_v2: dict[str, Any],
    scenario: HedgeScenario,
    trade_rows: list[dict[str, Any]],
    cycle_rows: list[dict[str, Any]],
    counters: dict[str, Any],
) -> tuple[list[str], str, dict[str, Any] | None]:
    signal_date = row.get("signal_date")
    actions: list[str] = []
    exception_reason = "none"
    active_cycle = next(
        (record for record in reversed(cycle_rows) if record["cycle_id"] == state.active_cycle_id),
        None,
    )
    if _truth(row.get("strong_confirmation")):
        state.strong_confirmation_streak += 1
    else:
        state.strong_confirmation_streak = 0

    if state.sell_stage == 0 and state.active_cycle_id == 0:
        if _truth(row.get("overheat_gate")) and not state.overheat_armed:
            state.overheat_armed = True
            state.arm_date = signal_date
            state.regime = "LATE_BULL"
            actions.append("ARM_LATE_BULL")
        if state.overheat_armed and _truth(row.get("stage1_condition")):
            state.sell_stage = 1
            active_cycle = _new_cycle_record(state, signal_date)
            cycle_rows.append(active_cycle)
            _set_regime(state, "DISTRIBUTION", signal_date, active_cycle)
            counters["sell_stage_1_count"] += 1
            actions.append("STAGE_1")
    elif state.regime != "NEW_BULL":
        old_stage = state.sell_stage
        if old_stage == 1 and _truth(row.get("stage2_condition")):
            state.sell_stage = 2
            active_cycle["stage_2_date"] = signal_date
            _set_regime(state, "BEAR", signal_date, active_cycle)
        elif old_stage == 2 and _truth(row.get("stage3_condition")):
            state.sell_stage = 3
            active_cycle["stage_3_date"] = signal_date
            _set_regime(state, "BEAR", signal_date, active_cycle)
        elif old_stage == 3 and _truth(row.get("stage4_condition")):
            state.sell_stage = 4
            active_cycle["stage_4_date"] = signal_date
            _set_regime(state, "DEEP_BEAR", signal_date, active_cycle)
        if state.sell_stage > old_stage:
            counters[f"sell_stage_{state.sell_stage}_count"] += 1
            actions.append(f"STAGE_{state.sell_stage}")

    if state.sell_stage > 0 and state.regime != "NEW_BULL":
        target, _, upper = _effective_stage_band(rules_v2, state.sell_stage, scenario.hard_floor)
        stage_just_changed = any(action == f"STAGE_{state.sell_stage}" for action in actions)
        exposure = _crypto_exposure(state, prices)
        if stage_just_changed or exposure > upper + 1e-10:
            action = (
                f"TACTICAL_SELL_STAGE_{state.sell_stage}"
                if stage_just_changed
                else f"TACTICAL_SELL_DRIFT_STAGE_{state.sell_stage}"
            )
            sold, exception_reason = _sell_to_exposure_target(
                state,
                row,
                prices,
                target,
                rules_v2,
                scenario,
                trade_rows,
                action=action,
            )
            if sold > 0:
                counters["tactical_sell_events"] += 1
                actions.append(action)

        ahr = row.get("ahr999_fixed_arithmetic", np.nan)
        triggers: list[str] = []
        if pd.notna(ahr) and 0.30 <= float(ahr) <= 0.35 and not state.buyback_done["ahr_030_035"]:
            triggers.append("ahr_030_035")
        if pd.notna(ahr) and float(ahr) < 0.30 and not state.buyback_done["ahr_below_030"]:
            triggers.append("ahr_below_030")
        extreme_gate = _truth(row.get("BTC_daily_close") < row.get("bb_lower")) or (
            pd.notna(row.get("close_sma200_dev")) and float(row.get("close_sma200_dev")) <= -0.15
        )
        if (
            pd.notna(ahr)
            and float(ahr) <= 0.28
            and extreme_gate
            and not state.buyback_done["ahr_extreme"]
        ):
            triggers.append("ahr_extreme")
        for trigger in triggers:
            sleeve = sum(_crypto_values(state, prices).values()) + state.tactical_cash
            budget = min(
                state.tactical_cash,
                float(rules_v2["buyback_tranches"][trigger]) * sleeve,
            )
            spent = _buy_underweight(
                state,
                budget,
                prices,
                row,
                rules_v2,
                scenario,
                trade_rows,
                action=f"TACTICAL_BUYBACK_{trigger.upper()}",
            )
            if spent > 0:
                state.buyback_done[trigger] = True
                counters[f"{trigger}_buy_count"] += 1
                actions.append(f"BUYBACK_{trigger}")

        if _truth(row.get("right_confirmation")):
            _set_regime(state, "ACCUMULATION", signal_date, active_cycle)
            if not state.buyback_done["right_confirmation"]:
                sleeve = sum(_crypto_values(state, prices).values()) + state.tactical_cash
                budget = min(
                    state.tactical_cash,
                    float(rules_v2["buyback_tranches"]["right_confirmation"]) * sleeve,
                )
                spent = _buy_underweight(
                    state,
                    budget,
                    prices,
                    row,
                    rules_v2,
                    scenario,
                    trade_rows,
                    action="TACTICAL_BUYBACK_RIGHT_CONFIRMATION",
                )
                if spent > 0:
                    state.buyback_done["right_confirmation"] = True
                    counters["right_confirmation_count"] += 1
                    actions.append("BUYBACK_right_confirmation")
        elif state.regime == "ACCUMULATION" and state.sell_stage == 4 and _truth(row.get("stage4_condition")):
            _set_regime(state, "DEEP_BEAR", signal_date, active_cycle)

        required = int(rules_v2["new_bull"]["strong_confirmation_days"])
        if state.strong_confirmation_streak >= required:
            _set_regime(state, "NEW_BULL", signal_date, active_cycle)
            # A confirmed NEW_BULL invalidates the bearish sell stage immediately.
            # The cycle and one-shot flags stay live until tactical cash finishes
            # redeploying; this avoids both the old Stage-3/93%-exposure display bug
            # and premature trigger re-arming.
            state.sell_stage = 0
            if active_cycle is not None and pd.isna(active_cycle["reset_date"]):
                active_cycle["reset_date"] = signal_date
                active_cycle["status"] = "REDEPLOYING"
            actions.append("NEW_BULL_CONFIRMED")
            actions.append("SELL_STAGE_RESET")

    if state.active_cycle_id > 0 and state.regime == "NEW_BULL" and _truth(row.get("strong_confirmation")):
        completion_target = float(rules_v2["new_bull"]["completion_exposure"])
        minimum = min(float(v) for v in rules_v2["modeled_min_notional_usdt"].values())
        need = _budget_to_exposure_target(state, prices, completion_target, scenario)
        fraction = float(rules_v2["new_bull"]["daily_remaining_cash_fraction"])
        budget = min(need, fraction * state.tactical_cash)
        # Prevent a minimum-notional deadlock: if the fractional tranche falls
        # below the modeled exchange minimum while enough tactical cash remains,
        # execute one minimum-sized final tranche (capped by cash available).
        if 0.0 < budget < minimum and state.tactical_cash >= minimum:
            budget = min(state.tactical_cash, minimum)
        spent = _buy_underweight(
            state,
            budget,
            prices,
            row,
            rules_v2,
            scenario,
            trade_rows,
            action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
        )
        if spent > 0:
            counters["new_bull_redeploy_count"] += 1
            actions.append("NEW_BULL_REDEPLOY")
        if _crypto_exposure(state, prices) >= completion_target - 1e-8 or state.tactical_cash < minimum:
            if active_cycle is None:
                raise AssertionError("NEW_BULL reset attempted without an active cycle")
            completed_cycle_id = state.active_cycle_id
            _reset_cycle(state, signal_date, active_cycle)
            counters["cycle_reset_count"] += 1
            actions.append(f"CYCLE_RESET_{completed_cycle_id}")

    return actions, exception_reason, active_cycle


def _a_dca_trade_plan(a_result: BacktestResult) -> dict[pd.Timestamp, list[dict[str, Any]]]:
    plan: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    dca = a_result.trades.loc[a_result.trades["action"].eq("NORMAL_DCA")].copy()
    for timestamp, group in dca.groupby("timestamp", sort=True):
        plan[pd.Timestamp(timestamp)] = group[
            ["asset", "cash_change_usd", "quantity", "gross_notional_usd"]
        ].to_dict("records")
    return plan


def run_cycle_hedge_backtest(
    frame: pd.DataFrame,
    rules_v2: dict[str, Any],
    scenario: HedgeScenario,
    model_a: BacktestResult,
    *,
    record_signals: bool = True,
) -> V2BacktestResult:
    if frame.empty:
        raise ValueError("No formal-period 4H bars supplied")
    if len(frame) != len(model_a.history):
        raise ValueError("Model A history must align one-to-one with the challenger frame")
    if not pd.Series(frame["open_time"].to_numpy()).equals(
        pd.Series(model_a.history["timestamp"].to_numpy())
    ):
        raise ValueError("Model A timestamps do not align with the challenger frame")

    state = HedgeState(
        normal_cash=float(scenario.initial_capital),
        bull_start_date=pd.Timestamp(frame.iloc[0]["open_time"]).floor("D"),
    )
    trade_rows: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    cycle_rows: list[dict[str, Any]] = []
    counters: dict[str, Any] = {
        "sell_stage_1_count": 0,
        "sell_stage_2_count": 0,
        "sell_stage_3_count": 0,
        "sell_stage_4_count": 0,
        "ahr_030_035_buy_count": 0,
        "ahr_below_030_buy_count": 0,
        "ahr_extreme_buy_count": 0,
        "right_confirmation_count": 0,
        "new_bull_redeploy_count": 0,
        "cycle_reset_count": 0,
        "tactical_sell_events": 0,
        "dca_cash_protection_slowdowns": 0,
        "dca_cash_shortfall_count": 0,
        "ever_normal_cash_zero": False,
        "first_normal_cash_depletion": "",
    }
    dca_plan = _a_dca_trade_plan(model_a)
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS}
    for asset in ASSETS:
        budget = float(rules_v2["initial_allocation_usd"][asset])
        _buy(
            state,
            asset,
            budget,
            first_prices[asset],
            first_prices,
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

    for position, (_, row) in enumerate(frame.iterrows()):
        timestamp = pd.Timestamp(row["open_time"])
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS}
        a_history = model_a.history.iloc[position]
        external_flow = float(a_history["external_flow"])
        intended_dca = float(rules_v2["external_contribution_per_4h"]) * float(
            a_history["elapsed_4h_intervals"]
        )
        committed_dca = float(a_history["committed_dca"])
        state.normal_cash += external_flow

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        signal_actions: list[str] = []
        exception_reason = "none"
        before_regime = state.regime
        before_stage = state.sell_stage
        before_cycle = state.active_cycle_id
        if is_new_signal:
            signal_actions, exception_reason, _ = _process_daily_signal(
                state,
                row,
                prices_open,
                rules_v2,
                scenario,
                trade_rows,
                cycle_rows,
                counters,
            )
            state.last_signal_date = row.get("signal_date")

        if state.normal_cash + 1e-10 < committed_dca:
            counters["dca_cash_shortfall_count"] += 1
            if not counters["first_normal_cash_depletion"]:
                counters["first_normal_cash_depletion"] = timestamp.isoformat()
            raise AssertionError("Model E normal cash cannot replay Model A DCA")
        state.normal_cash -= committed_dca
        state.pending_dca_cash += committed_dca
        executed_dca = 0.0
        for instruction in dca_plan.get(timestamp, []):
            budget = -float(instruction["cash_change_usd"])
            executed_dca += _buy(
                state,
                str(instruction["asset"]),
                budget,
                prices_open[str(instruction["asset"])],
                prices_open,
                timestamp=timestamp,
                scenario=scenario,
                action="NORMAL_DCA",
                ledger="pending",
                trade_rows=trade_rows,
                signal_date=row.get("signal_date"),
            )
        if abs(executed_dca - float(a_history["executed_dca"])) > 1e-8:
            raise AssertionError("Model E executed DCA diverged from Model A")
        if state.normal_cash <= 1e-10:
            counters["ever_normal_cash_zero"] = True

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        values = _crypto_values(state, prices_close)
        crypto_value = sum(values.values())
        crypto_exposure = crypto_value / end_value if end_value > 0 else 0.0
        allocations = _crypto_allocations(state, prices_close)
        total_cash = state.normal_cash + state.pending_dca_cash + state.tactical_cash
        total_cash_ratio = total_cash / end_value if end_value > 0 else 0.0
        tactical_ratio = state.tactical_cash / end_value if end_value > 0 else 0.0
        if previous_closes is None:
            target_return = 0.0
        else:
            target_return = sum(
                float(rules_v2["target_weights"][asset])
                * (prices_close[asset] / previous_closes[asset] - 1.0)
                for asset in ASSETS
            )
        total_cash_drag_increment = total_cash_ratio * target_return
        tactical_cash_drag_increment = tactical_ratio * target_return
        target, lower, upper = _effective_stage_band(
            rules_v2, state.sell_stage, scenario.hard_floor
        )
        stage4_reason = "none"
        if state.sell_stage == 4 and crypto_exposure > upper + 1e-10:
            stage4_reason = exception_reason if exception_reason != "none" else (
                "signal_timing_between_daily_checks" if not is_new_signal else "execution_delay"
            )
        daily_floor_reason = "none"
        if crypto_exposure + 1e-10 < scenario.hard_floor:
            daily_floor_reason = "market_move_after_tactical_sell"
        history_rows.append(
            {
                "timestamp": timestamp,
                "portfolio_value": end_value,
                "btc_value": values["BTC"],
                "eth_value": values["ETH"],
                "bnb_value": values["BNB"],
                "unit_nav": unit_nav,
                "drawdown": drawdown,
                "twr_return": twr_return,
                "external_flow": external_flow,
                "elapsed_4h_intervals": int(a_history["elapsed_4h_intervals"]),
                "normal_cash": state.normal_cash,
                "pending_dca_cash": state.pending_dca_cash,
                "tactical_cash": state.tactical_cash,
                "normal_cash_ratio": state.normal_cash / end_value if end_value > 0 else 0.0,
                "total_cash_ratio": total_cash_ratio,
                "tactical_cash_ratio": tactical_ratio,
                "crypto_exposure": crypto_exposure,
                "BTC_allocation": allocations["BTC"],
                "ETH_allocation": allocations["ETH"],
                "BNB_allocation": allocations["BNB"],
                "BTC_close": prices_close["BTC"],
                "ETH_close": prices_close["ETH"],
                "BNB_close": prices_close["BNB"],
                "ahr999": row.get("ahr999_fixed_arithmetic", np.nan),
                "cycle_regime": state.regime,
                "sell_stage": state.sell_stage,
                "sell_cycle_id": state.active_cycle_id,
                "stage_target_exposure": target,
                "stage_lower_band": lower,
                "stage_upper_band": upper,
                "theoretical_dca": float(rules_v2["external_contribution_per_4h"]),
                "protected_dca": float(rules_v2["external_contribution_per_4h"]),
                "intended_dca": intended_dca,
                "committed_dca": committed_dca,
                "executed_dca": executed_dca,
                "target_basket_return": target_return,
                "cash_drag_increment": total_cash_drag_increment,
                "tactical_cash_drag_increment": tactical_cash_drag_increment,
                "daily_floor_breach_reason": daily_floor_reason,
                "stage4_upper_band_exception_reason": stage4_reason,
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
                    "ahr999": row.get("ahr999_fixed_arithmetic"),
                    "overheat_gate": row.get("overheat_gate"),
                    "stage1_condition": row.get("stage1_condition"),
                    "stage2_condition": row.get("stage2_condition"),
                    "stage3_condition": row.get("stage3_condition"),
                    "stage4_condition": row.get("stage4_condition"),
                    "right_confirmation": row.get("right_confirmation"),
                    "strong_confirmation": row.get("strong_confirmation"),
                    "regime_before": before_regime,
                    "regime_after": state.regime,
                    "sell_stage_before": before_stage,
                    "sell_stage_after": state.sell_stage,
                    "sell_cycle_id_before": before_cycle,
                    "sell_cycle_id_after": state.active_cycle_id,
                    "strong_confirmation_streak": state.strong_confirmation_streak,
                    "actions": "|".join(signal_actions),
                    "crypto_exposure_after": _crypto_exposure(state, prices_open),
                    "tactical_cash_after": state.tactical_cash,
                    "stage_target_exposure": target,
                    "stage_lower_band": lower,
                    "stage_upper_band": upper,
                    "exposure_exception_reason": exception_reason,
                }
            )
        previous_value = end_value
        previous_closes = prices_close

    final_signal_date = frame.iloc[-1].get("signal_date")
    for record in cycle_rows:
        if record["status"] != "CLOSED":
            record["cycle_end"] = final_signal_date

    history = pd.DataFrame(history_rows)
    trades = pd.DataFrame(trade_rows)
    signals = pd.DataFrame(signal_rows)
    cycles = pd.DataFrame(cycle_rows)
    summary = calculate_summary(
        history,
        trades,
        scenario=scenario,
        counters=counters,
        rules=rules_v2,
    )
    return V2BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history,
        trades=trades,
        signals=signals,
        cycles=cycles,
        counters=counters,
    )
