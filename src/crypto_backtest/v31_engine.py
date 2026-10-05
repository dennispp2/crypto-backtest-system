from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .metrics import calculate_summary


ASSETS_V31 = ("BTC", "ETH")


@dataclass(frozen=True)
class V31Scenario:
    name: str
    model: str
    use_fsm: bool
    use_ai: bool
    hard_floor: float = 0.20
    initial_capital: float = 20_000.0
    initial_crypto_fraction: float = 0.70
    capital_test: str = "test2_v3_1"
    variant: str = "primary"
    cost_case: str = "primary"
    fee: float = 0.001
    slippage: float = 0.0005
    cash_protection: bool = False
    sell_order: str = "fixed_62_5_37_5"


@dataclass
class V31State:
    qty: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS_V31})
    normal_cash: float = 20_000.0
    pending: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS_V31})
    tactical_bear_cash: float = 0.0
    temporary_lots: list[dict[str, Any]] = field(default_factory=list)
    macro_state: str = "BULL"
    stage: int = 0
    active_target: float = 0.95
    active_cycle_id: int = 0
    next_cycle_id: int = 1
    last_signal_date: Any = None
    signal_index: int = 0
    regime_days: int = 0
    macro_cooldown_days: int = 0
    redeploy_days_remaining: int = 0
    accumulation_lock_until: Any = None
    last_drift_sell_at: Any = None
    bear_low_price: float = float("inf")
    bear_low_date: Any = None
    right_50_done: bool = False
    right_60_done: bool = False
    crash_armed: bool = True
    crash_clear_days: int = 5
    crash_level1_days_remaining: int = 0
    crash_level2_fired: bool = False
    tactical_event_id: int = 0
    temp_lot_id: int = 0


@dataclass
class V31BacktestResult:
    scenario: V31Scenario
    summary: dict[str, Any]
    history: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    transitions: pd.DataFrame
    cycles: pd.DataFrame
    temporary_lots: pd.DataFrame
    cash_events: pd.DataFrame
    counters: dict[str, Any]


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _temp_cash(state: V31State) -> float:
    return float(sum(float(lot["cash_remaining"]) for lot in state.temporary_lots if lot["status"] == "OPEN"))


def _pending_cash(state: V31State) -> float:
    return float(sum(state.pending.values()))


def _values(state: V31State, prices: dict[str, float]) -> dict[str, float]:
    return {asset: state.qty[asset] * prices[asset] for asset in ASSETS_V31}


def _portfolio_value(state: V31State, prices: dict[str, float]) -> float:
    return (
        sum(_values(state, prices).values()) + state.normal_cash + _pending_cash(state)
        + state.tactical_bear_cash + _temp_cash(state)
    )


def _exposure(state: V31State, prices: dict[str, float]) -> float:
    total = _portfolio_value(state, prices)
    return sum(_values(state, prices).values()) / total if total > 0 else 0.0


def _allocations(state: V31State, prices: dict[str, float]) -> dict[str, float]:
    values = _values(state, prices)
    total = sum(values.values())
    return {asset: values[asset] / total if total > 0 else 0.0 for asset in ASSETS_V31}


def _days_since(timestamp: pd.Timestamp, prior: Any) -> float:
    if prior is None or pd.isna(prior):
        return float("nan")
    return (timestamp - pd.Timestamp(prior)).total_seconds() / 86_400.0


def _gross_to_target(state: V31State, prices: dict[str, float], target: float, scenario: V31Scenario) -> float:
    crypto = sum(_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total <= target:
        return 0.0
    conversion = (1.0 - scenario.slippage) * (1.0 - scenario.fee)
    cost_fraction = 1.0 - conversion
    return max(0.0, (crypto - target * total) / max(1e-12, 1.0 - target * cost_fraction))


def _budget_to_target(state: V31State, prices: dict[str, float], target: float, scenario: V31Scenario) -> float:
    crypto = sum(_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total >= target:
        return 0.0
    conversion = 1.0 / ((1.0 + scenario.slippage) * (1.0 + scenario.fee))
    return max(0.0, (target * total - crypto) / max(1e-12, conversion + target * (1.0 - conversion)))


def _cash_snapshot(state: V31State) -> dict[str, float]:
    return {
        "normal_cash_after": state.normal_cash,
        "pending_dca_cash_after": _pending_cash(state),
        "tactical_bear_cash_after": state.tactical_bear_cash,
        "temporary_hedge_cash_after": _temp_cash(state),
    }


def _append_trade(
    rows: list[dict[str, Any]], *, state: V31State, prices: dict[str, float],
    timestamp: pd.Timestamp, scenario: V31Scenario, action: str, side: str,
    asset: str, quantity: float, raw_price: float, effective_price: float,
    gross_notional: float, cash_change: float, fee: float, slippage: float,
    ledger: str, signal_date: Any, reason: str, event_before: float = np.nan,
    target: float = np.nan, temp_lot_id: Any = "",
) -> None:
    rows.append({
        "timestamp": timestamp, "strategy": scenario.name, "model": scenario.model,
        "action": action, "side": side, "asset": asset, "quantity": quantity,
        "raw_open_price": raw_price, "effective_price": effective_price,
        "gross_notional_usd": gross_notional, "cash_change_usd": cash_change,
        "fee_usd": fee, "slippage_usd": slippage, "cost_usd": fee + slippage,
        "ledger": ledger, "reason": reason, "signal_date": signal_date,
        "fsm_state": state.macro_state, "fsm_stage": state.stage,
        "cycle_id": state.active_cycle_id,
        "tactical_event_id": state.tactical_event_id if action.startswith("TACTICAL") else 0,
        "temporary_lot_id": temp_lot_id,
        "before_crypto_exposure": event_before, "target_crypto_exposure": target,
        "after_crypto_exposure": _exposure(state, prices), **_cash_snapshot(state),
    })


def _buy(
    state: V31State, asset: str, budget: float, price: float, prices: dict[str, float],
    *, timestamp: pd.Timestamp, scenario: V31Scenario, action: str, ledger: str,
    trades: list[dict[str, Any]], signal_date: Any, reason: str = "",
    event_before: float = np.nan, target: float = np.nan,
    temp_lot: dict[str, Any] | None = None,
) -> float:
    if ledger == "normal":
        available = state.normal_cash
    elif ledger == "pending":
        available = state.pending[asset]
    elif ledger == "tactical_bear":
        available = state.tactical_bear_cash
    elif ledger == "temporary_hedge" and temp_lot is not None:
        available = float(temp_lot["cash_remaining"])
    else:
        raise ValueError(f"Invalid buy ledger {ledger}")
    budget = min(max(0.0, float(budget)), float(available))
    if budget <= 0 or price <= 0:
        return 0.0
    effective = price * (1.0 + scenario.slippage)
    quantity = budget / (effective * (1.0 + scenario.fee))
    gross = quantity * price
    slippage = quantity * (effective - price)
    fee = quantity * effective * scenario.fee
    if ledger == "normal":
        state.normal_cash -= budget
    elif ledger == "pending":
        state.pending[asset] -= budget
    elif ledger == "tactical_bear":
        state.tactical_bear_cash -= budget
    else:
        assert temp_lot is not None
        temp_lot["cash_remaining"] -= budget
    state.qty[asset] += quantity
    _append_trade(
        trades, state=state, prices=prices, timestamp=timestamp, scenario=scenario,
        action=action, side="BUY", asset=asset, quantity=quantity, raw_price=price,
        effective_price=effective, gross_notional=gross, cash_change=-budget,
        fee=fee, slippage=slippage, ledger=ledger, signal_date=signal_date,
        reason=reason, event_before=event_before, target=target,
        temp_lot_id=temp_lot["lot_id"] if temp_lot is not None else "",
    )
    return budget


def _sell(
    state: V31State, asset: str, gross: float, price: float, prices: dict[str, float],
    *, timestamp: pd.Timestamp, scenario: V31Scenario, action: str, ledger: str,
    trades: list[dict[str, Any]], signal_date: Any, reason: str,
    event_before: float, target: float, temp_lot: dict[str, Any] | None,
) -> float:
    gross = min(max(0.0, float(gross)), state.qty[asset] * price)
    if gross <= 0 or price <= 0:
        return 0.0
    quantity = gross / price
    effective = price * (1.0 - scenario.slippage)
    pre_fee = quantity * effective
    fee = pre_fee * scenario.fee
    proceeds = pre_fee - fee
    slippage = quantity * (price - effective)
    state.qty[asset] -= quantity
    if ledger == "tactical_bear":
        state.tactical_bear_cash += proceeds
    elif ledger == "temporary_hedge" and temp_lot is not None:
        temp_lot["cash_remaining"] += proceeds
        temp_lot["original_proceeds"] += proceeds
    else:
        raise ValueError(f"Invalid sell ledger {ledger}")
    _append_trade(
        trades, state=state, prices=prices, timestamp=timestamp, scenario=scenario,
        action=action, side="SELL", asset=asset, quantity=quantity, raw_price=price,
        effective_price=effective, gross_notional=gross, cash_change=proceeds,
        fee=fee, slippage=slippage, ledger=ledger, signal_date=signal_date,
        reason=reason, event_before=event_before, target=target,
        temp_lot_id=temp_lot["lot_id"] if temp_lot is not None else "",
    )
    return gross


def _guard(
    state: V31State, prices: dict[str, float], target: float,
    notional: float, rules: dict[str, Any],
) -> tuple[bool, str]:
    gate = rules["turnover_guard"]
    gap = abs(_exposure(state, prices) - target)
    minimum = max(
        float(gate["minimum_notional_usd"]),
        float(gate["minimum_portfolio_fraction"]) * _portfolio_value(state, prices),
    )
    if gap + 1e-12 < float(gate["minimum_exposure_gap"]):
        return False, "EXPOSURE_GAP_BELOW_5PP"
    if notional + 1e-10 < minimum:
        return False, "NOTIONAL_BELOW_GUARD"
    return True, "PASS"


def _new_temp_lot(state: V31State, row: pd.Series, source: str) -> dict[str, Any]:
    state.temp_lot_id += 1
    lot = {
        "lot_id": state.temp_lot_id, "source": source,
        "cycle_id": state.active_cycle_id,
        "created_signal_date": row.get("signal_date"),
        "created_signal_index": state.signal_index,
        "original_proceeds": 0.0, "cash_remaining": 0.0,
        "unwind_started_date": pd.NaT, "unwind_days_remaining": 0,
        "closed_date": pd.NaT, "status": "OPEN", "closure_reason": "",
        "bear_confirmed": False, "maximum_age_calendar_days": 0.0,
        "ever_over_30_without_bear": False,
    }
    state.temporary_lots.append(lot)
    return lot


def _split_amount(total: float, weights: dict[str, float], capacities: dict[str, float]) -> dict[str, float]:
    amounts = {asset: min(total * float(weights[asset]), capacities[asset]) for asset in ASSETS_V31}
    remaining = total - sum(amounts.values())
    for asset in ASSETS_V31:
        if remaining <= 1e-10:
            break
        extra = min(remaining, max(0.0, capacities[asset] - amounts[asset]))
        amounts[asset] += extra
        remaining -= extra
    return amounts


def _sell_to_target(
    state: V31State, row: pd.Series, prices: dict[str, float], target: float,
    rules: dict[str, Any], scenario: V31Scenario, trades: list[dict[str, Any]],
    *, action: str, reason: str, ledger: str,
) -> tuple[float, str, dict[str, Any] | None]:
    target = max(float(target), scenario.hard_floor)
    gross = min(
        _gross_to_target(state, prices, target, scenario),
        _gross_to_target(state, prices, scenario.hard_floor, scenario),
    )
    passed, why = _guard(state, prices, target, gross, rules)
    if not passed:
        return 0.0, why, None
    before = _exposure(state, prices)
    state.tactical_event_id += 1
    temp_lot = _new_temp_lot(state, row, reason) if ledger == "temporary_hedge" else None
    capacities = {asset: state.qty[asset] * prices[asset] for asset in ASSETS_V31}
    amounts = _split_amount(gross, rules["target_weights"], capacities)
    sold = 0.0
    for asset in ASSETS_V31:
        if amounts[asset] + 1e-10 < float(rules["modeled_min_notional_usdt"][asset]):
            continue
        sold += _sell(
            state, asset, amounts[asset], prices[asset], prices,
            timestamp=pd.Timestamp(row["open_time"]), scenario=scenario,
            action=action, ledger=ledger, trades=trades,
            signal_date=row.get("signal_date"), reason=reason,
            event_before=before, target=target, temp_lot=temp_lot,
        )
    if sold <= 0 and temp_lot is not None:
        state.temporary_lots.remove(temp_lot)
        temp_lot = None
    if _exposure(state, prices) < scenario.hard_floor - 1e-9:
        raise AssertionError("Tactical sell breached the sell-time hard floor")
    return sold, "EXECUTED" if sold > 0 else "MINIMUM_NOTIONAL", temp_lot


def _buy_to_target(
    state: V31State, row: pd.Series, prices: dict[str, float], target: float,
    rules: dict[str, Any], scenario: V31Scenario, trades: list[dict[str, Any]],
    *, action: str, reason: str, ledger: str,
    temp_lot: dict[str, Any] | None = None, budget_cap: float | None = None,
) -> tuple[float, str]:
    if ledger == "tactical_bear":
        available = state.tactical_bear_cash
    elif ledger == "temporary_hedge" and temp_lot is not None:
        available = float(temp_lot["cash_remaining"])
    else:
        raise ValueError(f"Invalid tactical buy ledger {ledger}")
    needed = min(_budget_to_target(state, prices, min(float(target), 0.95), scenario), available)
    if budget_cap is not None:
        needed = min(needed, float(budget_cap))
    passed, why = _guard(state, prices, float(target), needed, rules)
    if not passed:
        return 0.0, why
    before = _exposure(state, prices)
    state.tactical_event_id += 1
    budgets = {asset: needed * float(rules["target_weights"][asset]) for asset in ASSETS_V31}
    spent = 0.0
    for asset in ASSETS_V31:
        if budgets[asset] + 1e-10 < float(rules["modeled_min_notional_usdt"][asset]):
            continue
        spent += _buy(
            state, asset, budgets[asset], prices[asset], prices,
            timestamp=pd.Timestamp(row["open_time"]), scenario=scenario,
            action=action, ledger=ledger, trades=trades,
            signal_date=row.get("signal_date"), reason=reason,
            event_before=before, target=target, temp_lot=temp_lot,
        )
    return spent, "EXECUTED" if spent > 0 else "MINIMUM_NOTIONAL"


def _transition(
    state: V31State, to_state: str, reason: str, row: pd.Series,
    rules: dict[str, Any], transitions: list[dict[str, Any]],
    *, ai_intervention: str = "NONE",
) -> None:
    before = state.macro_state
    allowed = rules["allowed_transitions"].get(before, [])
    if to_state not in allowed:
        raise AssertionError(f"Illegal V3.1 FSM transition {before} -> {to_state}")
    transitions.append({
        "strategy": row.get("strategy_name", ""),
        "signal_date": row.get("signal_date"),
        "execution_4h_open": row.get("open_time"),
        "from_state": before, "to_state": to_state, "reason": reason,
        "cycle_id": state.active_cycle_id, "ai_intervention": ai_intervention,
    })
    state.macro_state = to_state
    state.regime_days = 0


def _new_cycle(state: V31State, row: pd.Series, prices: dict[str, float]) -> dict[str, Any]:
    cycle_id = state.next_cycle_id
    state.next_cycle_id += 1
    state.active_cycle_id = cycle_id
    state.right_50_done = False
    state.right_60_done = False
    state.bear_low_price = float("inf")
    state.bear_low_date = None
    peak = float(row.get("cycle_peak_90d", row.get("BTC_daily_close", prices["BTC"])))
    result: dict[str, Any] = {
        "cycle_id": cycle_id, "start": row.get("signal_date"), "end": pd.NaT,
        "status": "OPEN", "confirmed": False, "confirmed_date": pd.NaT,
        "cycle_peak_price": peak, "temporary_hedge_amount": 0.0,
        "new_bull_date": pd.NaT,
    }
    for stage in range(1, 5):
        for field_name in ("date", "btc_price", "eth_price", "exposure", "tactical_cash", "bear_risk"):
            result[f"stage{stage}_{field_name}"] = pd.NaT if field_name == "date" else np.nan
    return result


def _cycle(state: V31State, cycles: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in reversed(cycles) if item["cycle_id"] == state.active_cycle_id), None)


def _record_stage(
    cycle: dict[str, Any] | None, stage: int, row: pd.Series,
    state: V31State, prices: dict[str, float],
) -> None:
    if cycle is None or pd.notna(cycle[f"stage{stage}_date"]):
        return
    cycle[f"stage{stage}_date"] = row.get("signal_date")
    cycle[f"stage{stage}_btc_price"] = row.get("BTC_daily_close")
    cycle[f"stage{stage}_eth_price"] = prices["ETH"]
    cycle[f"stage{stage}_exposure"] = _exposure(state, prices)
    cycle[f"stage{stage}_tactical_cash"] = state.tactical_bear_cash + _temp_cash(state)
    cycle[f"stage{stage}_bear_risk"] = row.get("bear_risk", np.nan)


def _reclassify_temp_to_bear(
    state: V31State, row: pd.Series, cash_events: list[dict[str, Any]], reason: str,
) -> float:
    amount = 0.0
    for lot in state.temporary_lots:
        if lot["status"] != "OPEN":
            continue
        amount += float(lot["cash_remaining"])
        lot["cash_remaining"] = 0.0
        lot["status"] = "RECLASSIFIED_TO_BEAR"
        lot["closed_date"] = row.get("signal_date")
        lot["closure_reason"] = reason
        lot["bear_confirmed"] = True
    if amount > 0:
        state.tactical_bear_cash += amount
        cash_events.append({
            "strategy": row.get("strategy_name", ""), "date": row.get("signal_date"),
            "event": "TEMPORARY_TO_TACTICAL_BEAR", "amount_usd": amount,
            "reason": reason, "cycle_id": state.active_cycle_id,
        })
    return amount


def _update_temp_lots(state: V31State, row: pd.Series, rules: dict[str, Any]) -> None:
    limit = float(rules["temporary_hedge"]["maximum_unconfirmed_survival_calendar_days"])
    date = pd.Timestamp(row.get("signal_date"))
    for lot in state.temporary_lots:
        if lot["status"] != "OPEN":
            continue
        age = (date - pd.Timestamp(lot["created_signal_date"])).total_seconds() / 86_400.0
        lot["maximum_age_calendar_days"] = max(float(lot["maximum_age_calendar_days"]), age)
        if not lot["bear_confirmed"] and age > limit:
            lot["ever_over_30_without_bear"] = True


def _process_temp_unwind(
    state: V31State, row: pd.Series, prices: dict[str, float], rules: dict[str, Any],
    scenario: V31Scenario, trades: list[dict[str, Any]], actions: list[str],
) -> None:
    if state.macro_state != "BULL" or not _truth(row.get("bull_5_confirmed")):
        return
    observation = int(rules["temporary_hedge"]["observation_trading_days"])
    unwind_days = int(rules["temporary_hedge"]["unwind_trading_days"])
    for lot in state.temporary_lots:
        if lot["status"] != "OPEN" or lot["bear_confirmed"]:
            continue
        if state.signal_index - int(lot["created_signal_index"]) < observation:
            continue
        if lot["unwind_days_remaining"] == 0 and pd.isna(lot["unwind_started_date"]):
            lot["unwind_started_date"] = row.get("signal_date")
            lot["unwind_days_remaining"] = unwind_days
        if lot["unwind_days_remaining"] <= 0:
            continue
        cap = float(lot["cash_remaining"]) / float(lot["unwind_days_remaining"])
        spent, outcome = _buy_to_target(
            state, row, prices, 0.95, rules, scenario, trades,
            action="TACTICAL_BUY_TEMPORARY_HEDGE_UNWIND",
            reason=f"temporary_lot_{lot['lot_id']}_five_day_unwind",
            ledger="temporary_hedge", temp_lot=lot, budget_cap=cap,
        )
        lot["unwind_days_remaining"] -= 1
        actions.append(f"TEMP_UNWIND_LOT_{lot['lot_id']}:{outcome}")
        if float(lot["cash_remaining"]) <= 1e-8:
            lot["cash_remaining"] = 0.0
            lot["status"] = "UNWOUND"
            lot["closed_date"] = row.get("signal_date")
            lot["closure_reason"] = "FIVE_DAY_UNWIND"
        elif lot["unwind_days_remaining"] == 0:
            lot["unwind_started_date"] = pd.NaT


def _is_lock_active(state: V31State, timestamp: pd.Timestamp) -> bool:
    return bool(state.accumulation_lock_until is not None and timestamp < pd.Timestamp(state.accumulation_lock_until))


def _start_lock(state: V31State, row: pd.Series, rules: dict[str, Any]) -> None:
    state.accumulation_lock_until = pd.Timestamp(row["open_time"]) + pd.Timedelta(
        days=int(rules["buyback"]["accumulation_lock_calendar_days"])
    )


def _stage_sell(
    state: V31State, stage: int, row: pd.Series, prices: dict[str, float],
    rules: dict[str, Any], scenario: V31Scenario, trades: list[dict[str, Any]],
    cycles: list[dict[str, Any]], actions: list[str], *, reason: str, temporary: bool,
) -> None:
    state.stage = stage
    state.active_target = float(rules["stage_targets"][str(stage)])
    _record_stage(_cycle(state, cycles), stage, row, state, prices)
    _, outcome, lot = _sell_to_target(
        state, row, prices, state.active_target, rules, scenario, trades,
        action=f"TACTICAL_SELL_STAGE{stage}", reason=reason,
        ledger="temporary_hedge" if temporary else "tactical_bear",
    )
    if lot is not None:
        cycle = _cycle(state, cycles)
        if cycle is not None:
            cycle["temporary_hedge_amount"] += float(lot["original_proceeds"])
    actions.append(f"STAGE{stage}_SELL:{outcome}")


def _bear_risk_high(row: pd.Series, rules: dict[str, Any], scenario: V31Scenario) -> bool:
    return bool(
        scenario.use_ai and _truth(row.get("ai_enabled"))
        and pd.notna(row.get("bear_risk"))
        and float(row["bear_risk"]) >= float(rules["ai"]["high_risk_threshold"])
    )


def _run_macro_fsm(
    state: V31State, row: pd.Series, prices: dict[str, float], rules: dict[str, Any],
    scenario: V31Scenario, trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]], cycles: list[dict[str, Any]],
    cash_events: list[dict[str, Any]], counters: dict[str, Any], actions: list[str],
) -> tuple[str, str]:
    ai_intervention, ai_reason = "NONE", ""
    current = state.macro_state
    start_state = current
    timestamp = pd.Timestamp(row["open_time"])
    active_cycle = _cycle(state, cycles)
    if active_cycle is not None:
        active_cycle["cycle_peak_price"] = max(
            float(active_cycle["cycle_peak_price"]), float(row["BTC_daily_close"])
        )
    if current in {"BEAR", "DEEP_BEAR", "ACCUMULATION"}:
        close = float(row["BTC_daily_close"])
        if close < state.bear_low_price:
            state.bear_low_price = close
            state.bear_low_date = row.get("signal_date")

    if start_state == "BULL" and state.macro_cooldown_days <= 0 and _truth(row.get("distribution_confirmed")):
        cycles.append(_new_cycle(state, row, prices))
        _transition(state, "DISTRIBUTION", "DISTRIBUTION_CONFIRMED", row, rules, transitions)
        _stage_sell(
            state, 1, row, prices, rules, scenario, trades, cycles, actions,
            reason="DISTRIBUTION_STAGE1", temporary=True,
        )
        counters["stage1_count"] += 1
        current = state.macro_state

    if start_state == "DISTRIBUTION":
        active_cycle = _cycle(state, cycles)
        abort_allowed = active_cycle is not None and not bool(active_cycle["confirmed"])
        if _truth(row.get("distribution_abort_confirmed")) and abort_allowed:
            _transition(state, "BULL", "ABORTED_DISTRIBUTION", row, rules, transitions)
            if active_cycle is not None:
                active_cycle["end"] = row.get("signal_date")
                active_cycle["status"] = "ABORTED_DISTRIBUTION"
            state.active_cycle_id = 0
            state.stage = 0
            state.active_target = 0.95
            counters["aborted_distribution_count"] += 1
            actions.append("ABORTED_DISTRIBUTION")
        elif _truth(row.get("early_bear_confirmed")):
            _transition(state, "EARLY_BEAR", "EARLY_BEAR_CONFIRMED", row, rules, transitions)
            active_cycle = _cycle(state, cycles)
            if active_cycle is not None and not bool(active_cycle["confirmed"]):
                active_cycle["confirmed"] = True
                active_cycle["confirmed_date"] = row.get("signal_date")
            _reclassify_temp_to_bear(state, row, cash_events, "EARLY_BEAR_CONFIRMED")
            _stage_sell(
                state, 2, row, prices, rules, scenario, trades, cycles, actions,
                reason="EARLY_BEAR_STAGE2", temporary=False,
            )
            counters["stage2_count"] += 1
        current = state.macro_state

    if start_state == "EARLY_BEAR":
        if _truth(row.get("stage3_confirmed")):
            _transition(state, "BEAR", "BEAR_STAGE3_CONFIRMED", row, rules, transitions)
            _stage_sell(
                state, 3, row, prices, rules, scenario, trades, cycles, actions,
                reason="BEAR_STAGE3", temporary=False,
            )
            counters["stage3_count"] += 1
        elif _truth(row.get("early_bear_repair_confirmed")):
            _transition(state, "DISTRIBUTION", "EARLY_BEAR_REPAIR", row, rules, transitions)
            state.stage = 1
            state.active_target = 0.85
            actions.append("EARLY_BEAR_TO_DISTRIBUTION")
        current = state.macro_state

    if start_state == "BEAR":
        active_cycle = _cycle(state, cycles)
        cycle_dd = (
            float(row["BTC_daily_close"]) / float(active_cycle["cycle_peak_price"]) - 1.0
            if active_cycle is not None else np.nan
        )
        market_acceleration = bool(
            _truth(row.get("bear_acceleration_market_raw"))
            and cycle_dd <= float(rules["macro"]["drawdown_cycle_acceleration"])
        )
        structural = _truth(row.get("deep_bear_structural_confirmed"))
        ai_acceleration = bool(
            _bear_risk_high(row, rules, scenario)
            and float(row["BTC_daily_close"]) < float(row["sma200"])
            and not structural and not market_acceleration
        )
        if structural or market_acceleration or ai_acceleration:
            reason = (
                "AI_STAGE4_ACCELERATION" if ai_acceleration else
                "FSM_BEAR_ACCELERATION" if market_acceleration else
                "FSM_STRUCTURAL_STAGE4"
            )
            if ai_acceleration:
                ai_intervention = "AI_STAGE4_ACCELERATION"
                ai_reason = "risk>=0.70_and_close_below_sma200"
                counters["ai_stage4_acceleration_count"] += 1
            _transition(
                state, "DEEP_BEAR", reason, row, rules, transitions,
                ai_intervention=ai_intervention,
            )
            _stage_sell(
                state, 4, row, prices, rules, scenario, trades, cycles, actions,
                reason=reason, temporary=False,
            )
            counters["stage4_count"] += 1
        elif (
            pd.notna(row.get("ahr999_fixed_arithmetic"))
            and float(row["ahr999_fixed_arithmetic"]) <= float(rules["buyback"]["ahr999_threshold"])
        ):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, rules, transitions)
            state.active_target = float(rules["buyback"]["value_target"])
            spent, outcome = _buy_to_target(
                state, row, prices, state.active_target, rules, scenario, trades,
                action="TACTICAL_BUYBACK_AHR999_TO_35", reason="AHR999<=0.35",
                ledger="tactical_bear",
            )
            if spent > 0:
                _start_lock(state, row, rules)
                counters["value_buyback_count"] += 1
            actions.append(f"AHR999_TO35:{outcome}")
        current = state.macro_state

    if start_state == "DEEP_BEAR":
        if (
            pd.notna(row.get("ahr999_fixed_arithmetic"))
            and float(row["ahr999_fixed_arithmetic"]) <= float(rules["buyback"]["ahr999_threshold"])
        ):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, rules, transitions)
            state.active_target = float(rules["buyback"]["value_target"])
            spent, outcome = _buy_to_target(
                state, row, prices, state.active_target, rules, scenario, trades,
                action="TACTICAL_BUYBACK_AHR999_TO_35", reason="AHR999<=0.35",
                ledger="tactical_bear",
            )
            if spent > 0:
                _start_lock(state, row, rules)
                counters["value_buyback_count"] += 1
            actions.append(f"AHR999_TO35:{outcome}")
        elif _truth(row.get("deep_bear_exit_confirmed")):
            _transition(state, "BEAR", "DEEP_BEAR_STRUCTURAL_EXIT", row, rules, transitions)
            state.stage = 3
            state.active_target = 0.55
            actions.append("DEEP_BEAR_TO_BEAR_NO_AUTO_BUY")
        current = state.macro_state

    if start_state == "ACCUMULATION":
        lock_active = _is_lock_active(state, timestamp)
        lower_low = _truth(row.get("confirmed_lower_low"))
        if lock_active and lower_low:
            state.accumulation_lock_until = timestamp
            lock_active = False
            actions.append("ACCUMULATION_LOCK_RELEASE_LOWER_LOW")
        if not lock_active and (lower_low or _truth(row.get("deep_bear_structural_confirmed"))):
            to_state = "DEEP_BEAR" if _truth(row.get("deep_bear_structural_confirmed")) else "BEAR"
            _transition(state, to_state, "ACCUMULATION_BEARISH_REBREAK", row, rules, transitions)
            stage = 4 if to_state == "DEEP_BEAR" else 3
            _stage_sell(
                state, stage, row, prices, rules, scenario, trades, cycles, actions,
                reason="ACCUMULATION_BEARISH_REBREAK", temporary=False,
            )
        else:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            gate7 = bool(
                pd.notna(days_since_low)
                and days_since_low >= float(rules["new_bull"]["minimum_calendar_days_since_bear_low"])
            )
            if _truth(row.get("new_bull_first_six")) and gate7:
                _transition(state, "NEW_BULL", "NEW_BULL_ALL_SEVEN_GATES", row, rules, transitions)
                state.stage = 0
                state.active_target = 0.95
                state.redeploy_days_remaining = int(rules["new_bull"]["redeploy_trading_days"])
                active_cycle = _cycle(state, cycles)
                if active_cycle is not None:
                    active_cycle["new_bull_date"] = row.get("signal_date")
                counters["new_bull_count"] += 1
                actions.append("NEW_BULL_CONFIRMED")
            else:
                desired: float | None = None
                if (
                    state.active_target <= 0.35 + 1e-10
                    and _truth(row.get("right_50_confirmed"))
                    and not state.right_50_done
                ):
                    desired = 0.50
                elif (
                    state.active_target >= 0.50 - 1e-10
                    and state.active_target < 0.60 - 1e-10
                    and _truth(row.get("right_60_confirmed"))
                    and not state.right_60_done
                ):
                    desired = 0.60
                if desired is not None and _bear_risk_high(row, rules, scenario):
                    ai_intervention = "AI_BUYBACK_CAP"
                    ai_reason = f"risk>=0.70_blocked_target_{desired:.2f}"
                    counters["ai_buyback_cap_count"] += 1
                    actions.append(f"AI_BUYBACK_CAP_BLOCK_{desired:.2f}")
                elif desired is not None:
                    state.active_target = desired
                    spent, outcome = _buy_to_target(
                        state, row, prices, desired, rules, scenario, trades,
                        action=f"TACTICAL_BUYBACK_RIGHT_TO_{int(desired * 100)}",
                        reason=f"RIGHT_SIDE_TO_{int(desired * 100)}",
                        ledger="tactical_bear",
                    )
                    if spent > 0:
                        if desired == 0.50:
                            state.right_50_done = True
                        else:
                            state.right_60_done = True
                        _start_lock(state, row, rules)
                        counters["right_buyback_count"] += 1
                    actions.append(f"RIGHT_TO_{int(desired * 100)}:{outcome}")
        current = state.macro_state

    if current == "NEW_BULL":
        if state.redeploy_days_remaining > 0:
            cap = state.tactical_bear_cash / float(state.redeploy_days_remaining)
            spent, outcome = _buy_to_target(
                state, row, prices, 0.95, rules, scenario, trades,
                action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
                reason="TEN_DAY_NEW_BULL_REDEPLOY", ledger="tactical_bear",
                budget_cap=cap,
            )
            state.redeploy_days_remaining -= 1
            if spent > 0:
                counters["new_bull_redeploy_count"] += 1
            actions.append(f"NEW_BULL_REDEPLOY:{outcome}")
        if state.redeploy_days_remaining == 0:
            active_cycle = _cycle(state, cycles)
            _transition(state, "BULL", "NEW_BULL_REDEPLOY_COMPLETE", row, rules, transitions)
            if active_cycle is not None:
                active_cycle["end"] = row.get("signal_date")
                active_cycle["status"] = "COMPLETED_NEW_BULL"
            state.active_cycle_id = 0
            state.stage = 0
            state.active_target = 0.95
            state.macro_cooldown_days = int(rules["new_bull"]["macro_cooldown_trading_days"])
            actions.append("NEW_BULL_COMPLETE_COOLDOWN_30")

    return ai_intervention, ai_reason


def _process_crash(
    state: V31State, row: pd.Series, prices: dict[str, float], rules: dict[str, Any],
    scenario: V31Scenario, trades: list[dict[str, Any]],
    cash_events: list[dict[str, Any]], counters: dict[str, Any], actions: list[str],
) -> None:
    crash = rules["crash_brake"]
    raw_l1 = _truth(row.get("crash_level1_raw"))
    if raw_l1:
        state.crash_clear_days = 0
    else:
        state.crash_clear_days += 1
        if state.crash_clear_days >= int(crash["rearm_clear_days"]):
            state.crash_armed = True

    triggered_l1 = False
    if raw_l1 and state.crash_armed:
        state.crash_armed = False
        state.crash_level1_days_remaining = int(crash["level1_active_trading_days"])
        state.crash_level2_fired = False
        sold, outcome, _ = _sell_to_target(
            state, row, prices, float(crash["level1_target"]), rules, scenario, trades,
            action="TACTICAL_SELL_CRASH_L1", reason="CRASH_BRAKE_LEVEL1",
            ledger="temporary_hedge",
        )
        triggered_l1 = True
        counters["crash_level1_count"] += 1
        actions.append(f"CRASH_L1:{outcome}")
        if sold > 0 and state.macro_state in {"EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION"}:
            _reclassify_temp_to_bear(state, row, cash_events, "CRASH_DURING_CONFIRMED_BEAR")

    if (
        state.crash_level1_days_remaining > 0
        and not state.crash_level2_fired
        and _truth(row.get("crash_level2_market_raw"))
    ):
        sold, outcome, _ = _sell_to_target(
            state, row, prices, float(crash["level2_target"]), rules, scenario, trades,
            action="TACTICAL_SELL_CRASH_L2", reason="CRASH_BRAKE_LEVEL2",
            ledger="temporary_hedge",
        )
        state.crash_level2_fired = True
        state.accumulation_lock_until = pd.Timestamp(row["open_time"])
        counters["crash_level2_count"] += 1
        actions.append(f"CRASH_L2:{outcome}")
        if sold > 0 and state.macro_state in {"EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION"}:
            _reclassify_temp_to_bear(state, row, cash_events, "CRASH_DURING_CONFIRMED_BEAR")

    if state.crash_level1_days_remaining > 0 and not triggered_l1:
        state.crash_level1_days_remaining -= 1


def _process_drift(
    state: V31State, row: pd.Series, prices: dict[str, float], rules: dict[str, Any],
    scenario: V31Scenario, trades: list[dict[str, Any]],
    counters: dict[str, Any], actions: list[str],
) -> None:
    if state.macro_state not in {"DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR"}:
        return
    timestamp = pd.Timestamp(row["open_time"])
    if _is_lock_active(state, timestamp):
        return
    wait = _days_since(timestamp, state.last_drift_sell_at)
    if _exposure(state, prices) <= state.active_target + float(rules["turnover_guard"]["drift_sell_gap"]):
        return
    if pd.notna(wait) and wait < float(rules["turnover_guard"]["drift_sell_cooldown_calendar_days"]):
        return
    sold, outcome, _ = _sell_to_target(
        state, row, prices, state.active_target, rules, scenario, trades,
        action="TACTICAL_SELL_DRIFT", reason="DRIFT_ABOVE_ACTIVE_TARGET_PLUS_10PP",
        ledger="tactical_bear",
    )
    if sold > 0:
        state.last_drift_sell_at = timestamp
        counters["drift_sell_count"] += 1
    actions.append(f"DRIFT_SELL:{outcome}")


def _commit_model_a_dca(
    state: V31State, amount: float, prices: dict[str, float], rules: dict[str, Any],
) -> dict[str, float]:
    committed = min(max(0.0, amount), state.normal_cash)
    allocations = _allocations(state, prices)
    within = all(
        abs(allocations[asset] - float(rules["target_weights"][asset]))
        <= float(rules["allocation_tolerance"])
        for asset in ASSETS_V31
    )
    if within:
        plan = {asset: committed * float(rules["target_weights"][asset]) for asset in ASSETS_V31}
    else:
        most_underweight = min(
            ASSETS_V31,
            key=lambda asset: allocations[asset] - float(rules["target_weights"][asset]),
        )
        plan = {asset: committed if asset == most_underweight else 0.0 for asset in ASSETS_V31}
    state.normal_cash -= committed
    for asset in ASSETS_V31:
        state.pending[asset] += plan[asset]
    return plan


def run_v31_backtest(
    frame: pd.DataFrame, rules: dict[str, Any], scenario: V31Scenario,
    *, model_a: V31BacktestResult | None = None,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.1 bars")
    if scenario.model != "A" and model_a is None:
        raise ValueError("Models B/C require Model A's frozen DCA plan")
    state = V31State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    counters = {key: 0 for key in [
        "stage1_count", "stage2_count", "stage3_count", "stage4_count",
        "aborted_distribution_count", "value_buyback_count", "right_buyback_count",
        "new_bull_count", "new_bull_redeploy_count", "crash_level1_count",
        "crash_level2_count", "drift_sell_count", "ai_stage4_acceleration_count",
        "ai_buyback_cap_count", "dca_cash_shortfall_count",
    ]}

    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(rules["initial_allocation_usd"][asset]),
            first_prices[asset], first_prices, timestamp=pd.Timestamp(first["open_time"]),
            scenario=scenario, action="INITIAL_ALLOCATION", ledger="normal",
            trades=trades, signal_date=first.get("signal_date"), reason="FRESH_2020_START",
        )

    a_history = model_a.history.set_index("timestamp") if model_a is not None else None
    a_dca: dict[tuple[pd.Timestamp, str], float] | None = None
    if model_a is not None:
        dca = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")].copy()
        a_dca = {
            (pd.Timestamp(ts), str(asset)): float(-group["cash_change_usd"].sum())
            for (ts, asset), group in dca.groupby(["timestamp", "asset"])
        }

    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    previous_timestamp: pd.Timestamp | None = None
    unit_nav, peak_nav = 1.0, 1.0

    for _, source_row in frame.iterrows():
        row = source_row.copy()
        row["strategy_name"] = scenario.name
        timestamp = pd.Timestamp(row["open_time"])
        elapsed = (
            1 if previous_timestamp is None
            else max(1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4))))
        )
        external_flow = float(rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_state, before_stage, before_target = state.macro_state, state.stage, state.active_target
        before_exposure = _exposure(state, prices_open)
        actions: list[str] = []
        ai_intervention, ai_reason = "NONE", ""
        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, rules)
            if scenario.use_fsm:
                ai_intervention, ai_reason = _run_macro_fsm(
                    state, row, prices_open, rules, scenario, trades,
                    transitions, cycles, cash_events, counters, actions,
                )
                _process_crash(
                    state, row, prices_open, rules, scenario, trades,
                    cash_events, counters, actions,
                )
                _process_temp_unwind(state, row, prices_open, rules, scenario, trades, actions)
                _process_drift(state, row, prices_open, rules, scenario, trades, counters, actions)
                if state.macro_cooldown_days > 0:
                    state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        committed = external_flow
        dca_alloc = {asset: 0.0 for asset in ASSETS_V31}
        if scenario.model == "A":
            dca_alloc = _commit_model_a_dca(state, committed, prices_open, rules)
        else:
            assert a_history is not None
            arow = a_history.loc[timestamp]
            committed = float(arow["committed_dca"])
            if state.normal_cash + 1e-9 < committed:
                counters["dca_cash_shortfall_count"] += 1
                raise AssertionError("Tactical strategy cannot replay Model A DCA commitment")
            state.normal_cash -= committed
            for asset in ASSETS_V31:
                dca_alloc[asset] = float(arow[f"dca_alloc_{asset}"])
                state.pending[asset] += dca_alloc[asset]

        executed = 0.0
        for asset in ASSETS_V31:
            if scenario.model == "A":
                budget = (
                    state.pending[asset]
                    if state.pending[asset] + 1e-10 >= float(rules["modeled_min_notional_usdt"][asset])
                    else 0.0
                )
            else:
                assert a_dca is not None
                budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
                executed += _buy(
                    state, asset, budget, prices_open[asset], prices_open,
                    timestamp=timestamp, scenario=scenario, action="NORMAL_DCA",
                    ledger="pending", trades=trades, signal_date=row.get("signal_date"),
                    reason="FIXED_USD_2_PER_4H",
                )
        if scenario.model != "A" and abs(executed - float(a_history.loc[timestamp, "executed_dca"])) > 1e-8:
            raise AssertionError("Executed DCA differs from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        values = _values(state, prices_close)
        crypto_value = sum(values.values())
        allocations = _allocations(state, prices_close)
        pending_cash = _pending_cash(state)
        temporary_cash = _temp_cash(state)
        tactical_cash = state.tactical_bear_cash + temporary_cash
        total_cash = state.normal_cash + pending_cash + tactical_cash
        basket_return = 0.0 if previous_closes is None else sum(
            float(rules["target_weights"][asset])
            * (prices_close[asset] / previous_closes[asset] - 1.0)
            for asset in ASSETS_V31
        )
        histories.append({
            "timestamp": timestamp, "portfolio_value": end_value,
            "btc_value": values["BTC"], "eth_value": values["ETH"],
            "unit_nav": unit_nav, "drawdown": drawdown, "twr_return": twr_return,
            "external_flow": external_flow, "elapsed_4h_intervals": elapsed,
            "normal_cash": state.normal_cash, "pending_dca_cash": pending_cash,
            "tactical_bear_cash": state.tactical_bear_cash,
            "temporary_hedge_cash": temporary_cash, "tactical_cash": tactical_cash,
            "normal_cash_ratio": state.normal_cash / end_value,
            "tactical_bear_cash_ratio": state.tactical_bear_cash / end_value,
            "temporary_hedge_cash_ratio": temporary_cash / end_value,
            "tactical_cash_ratio": tactical_cash / end_value,
            "total_cash_ratio": total_cash / end_value,
            "crypto_exposure": crypto_value / end_value,
            "BTC_allocation": allocations["BTC"], "ETH_allocation": allocations["ETH"],
            "BTC_close": prices_close["BTC"], "ETH_close": prices_close["ETH"],
            "BTC_signal_close": row.get("BTC_daily_close"),
            "sma10": row.get("sma10"), "sma20": row.get("sma20"),
            "sma50": row.get("sma50"), "sma200": row.get("sma200"),
            "ahr999": row.get("ahr999_fixed_arithmetic"),
            "bear_risk": row.get("bear_risk") if scenario.use_ai else np.nan,
            "ai_enabled": bool(row.get("ai_enabled")) if scenario.use_ai and pd.notna(row.get("ai_enabled")) else False,
            "ai_intervention": ai_intervention if is_new_signal else "NONE",
            "macro_state_previous": before_state if scenario.use_fsm else "N/A",
            "macro_state": state.macro_state if scenario.use_fsm else "N/A",
            "sell_stage": state.stage if scenario.use_fsm else 0,
            "active_target": state.active_target if scenario.use_fsm else np.nan,
            "cycle_id": state.active_cycle_id if scenario.use_fsm else 0,
            "macro_cooldown_days": state.macro_cooldown_days,
            "accumulation_lock": _is_lock_active(state, timestamp),
            "crash_level1_active": state.crash_level1_days_remaining > 0,
            "theoretical_dca": float(rules["external_contribution_per_4h"]),
            "protected_dca": float(rules["external_contribution_per_4h"]),
            "committed_dca": committed, "executed_dca": executed,
            "dca_alloc_BTC": dca_alloc["BTC"], "dca_alloc_ETH": dca_alloc["ETH"],
            "target_basket_return": basket_return,
            "cash_drag_increment": (total_cash / end_value) * basket_return,
            "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
            "daily_floor_breach_reason": (
                "market_move_after_tactical_sell"
                if scenario.use_fsm and crypto_value / end_value < scenario.hard_floor - 1e-10
                else "none"
            ),
        })

        if is_new_signal:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            signals.append({
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"),
                "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "eth_execution_price": prices_open["ETH"],
                "sma10": row.get("sma10"), "sma20": row.get("sma20"),
                "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "bear_risk": row.get("bear_risk") if scenario.use_ai else np.nan,
                "ai_enabled": bool(row.get("ai_enabled")) if scenario.use_ai and pd.notna(row.get("ai_enabled")) else False,
                "ai_intervention": ai_intervention, "ai_intervention_reason": ai_reason,
                "state_before": before_state if scenario.use_fsm else "N/A",
                "state_after": state.macro_state if scenario.use_fsm else "N/A",
                "stage_before": before_stage if scenario.use_fsm else 0,
                "stage_after": state.stage if scenario.use_fsm else 0,
                "active_target_before": before_target if scenario.use_fsm else np.nan,
                "active_target_after": state.active_target if scenario.use_fsm else np.nan,
                "crypto_exposure_before": before_exposure,
                "crypto_exposure_after": _exposure(state, prices_open),
                "tactical_bear_cash_after": state.tactical_bear_cash,
                "temporary_hedge_cash_after": _temp_cash(state),
                "actions": "|".join(actions),
                "distribution_confirmed": row.get("distribution_confirmed"),
                "early_bear_confirmed": row.get("early_bear_confirmed"),
                "stage3_confirmed": row.get("stage3_confirmed"),
                "deep_bear_structural_confirmed": row.get("deep_bear_structural_confirmed"),
                "crash_level1_raw": row.get("crash_level1_raw"),
                "crash_level2_market_raw": row.get("crash_level2_market_raw"),
                "right_50_confirmed": row.get("right_50_confirmed"),
                "right_60_confirmed": row.get("right_60_confirmed"),
                **{f"new_bull_gate_{i}": row.get(f"new_bull_gate_{i}") for i in range(1, 7)},
                "new_bull_gate_7": bool(
                    pd.notna(days_since_low)
                    and days_since_low >= float(rules["new_bull"]["minimum_calendar_days_since_bear_low"])
                ),
            })

        previous_value = end_value
        previous_closes = prices_close
        previous_timestamp = timestamp

    final_signal_date = frame.iloc[-1].get("signal_date")
    for item in cycles:
        if pd.isna(item["end"]):
            item["end"] = final_signal_date
            item["status"] = "OPEN_AT_END"
    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history, trades=trade_frame,
        signals=pd.DataFrame(signals), transitions=pd.DataFrame(transitions),
        cycles=pd.DataFrame(cycles), temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events), counters=counters,
    )
