from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .engine import ASSETS, BacktestResult
from .metrics import calculate_summary


@dataclass(frozen=True)
class V3Scenario:
    name: str
    hard_floor: float
    initial_capital: float = 20_000.0
    initial_crypto_fraction: float = 0.7
    capital_test: str = "test2_v3"
    variant: str = "primary"
    cost_case: str = "primary"
    fee: float = 0.001
    slippage: float = 0.0005
    cash_protection: bool = False
    sell_order: str = "overweight_then_technical_weakness"


@dataclass
class V3State:
    qty: dict[str, float] = field(default_factory=lambda: {asset: 0.0 for asset in ASSETS})
    normal_cash: float = 0.0
    pending_dca_cash: float = 0.0
    tactical_cash: float = 0.0
    macro_regime: str = "BULL"
    sell_stage: int = 0
    active_exposure_target: float = 0.95
    active_cycle_id: int = 0
    next_cycle_id: int = 1
    last_signal_date: Any = None
    signal_index: int = 0
    regime_days: int = 0
    late_bull_absent_days: int = 0
    ordinary_risk_off_lock_days: int = 0
    last_tactical_trade_at: Any = None
    last_tactical_buy_at: Any = None
    last_drift_sell_at: Any = None
    tactical_event_id: int = 0
    redeploy_cycle_id: int = 0
    redeploy_days_remaining: int = 0
    bear_low_price: float = float("inf")
    bear_low_date: Any = None
    new_bull_gate_7: bool = False
    buyback_done: dict[str, bool] = field(
        default_factory=lambda: {
            "ahr_030_035": False,
            "ahr_below_030": False,
            "ahr_extreme": False,
            "right_recovery": False,
        }
    )


@dataclass
class V3BacktestResult:
    scenario: V3Scenario
    summary: dict[str, Any]
    history: pd.DataFrame
    trades: pd.DataFrame
    signals: pd.DataFrame
    cycles: pd.DataFrame
    counters: dict[str, Any]


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _values(state: V3State, prices: dict[str, float]) -> dict[str, float]:
    return {asset: state.qty[asset] * prices[asset] for asset in ASSETS}


def _portfolio_value(state: V3State, prices: dict[str, float]) -> float:
    return sum(_values(state, prices).values()) + state.normal_cash + state.pending_dca_cash + state.tactical_cash


def _exposure(state: V3State, prices: dict[str, float]) -> float:
    total = _portfolio_value(state, prices)
    return sum(_values(state, prices).values()) / total if total > 0 else 0.0


def _allocations(state: V3State, prices: dict[str, float]) -> dict[str, float]:
    values = _values(state, prices)
    crypto = sum(values.values())
    return {asset: values[asset] / crypto if crypto > 0 else 0.0 for asset in ASSETS}


def _days_since(timestamp: pd.Timestamp, prior: Any) -> float:
    if prior is None or pd.isna(prior):
        return float("nan")
    return (timestamp - pd.Timestamp(prior)).total_seconds() / 86_400.0


def _append_trade(
    rows: list[dict[str, Any]],
    *,
    state: V3State,
    prices: dict[str, float],
    timestamp: pd.Timestamp,
    scenario: V3Scenario,
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
    reason: str = "",
    event_before_exposure: float = np.nan,
    target_exposure: float = np.nan,
    days_since_previous_tactical_trade: float = np.nan,
    tactical_event_id: int = 0,
    invalidation: bool = False,
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
            "reason": reason,
            "macro_regime": state.macro_regime,
            "sell_stage": state.sell_stage,
            "sell_cycle_id": state.active_cycle_id if state.active_cycle_id else state.redeploy_cycle_id,
            "signal_date": signal_date,
            "before_crypto_exposure": event_before_exposure,
            "target_crypto_exposure": target_exposure,
            "after_crypto_exposure": _exposure(state, prices),
            "active_exposure_target": state.active_exposure_target,
            "days_since_previous_tactical_trade": days_since_previous_tactical_trade,
            "tactical_event_id": tactical_event_id,
            "bearish_invalidation": invalidation,
            "normal_cash_after": state.normal_cash,
            "pending_dca_cash_after": state.pending_dca_cash,
            "tactical_cash_after": state.tactical_cash,
        }
    )


def _buy(
    state: V3State,
    asset: str,
    budget: float,
    price: float,
    prices: dict[str, float],
    *,
    timestamp: pd.Timestamp,
    scenario: V3Scenario,
    action: str,
    ledger: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
    reason: str = "",
    event_before_exposure: float = np.nan,
    target_exposure: float = np.nan,
    days_since_previous_tactical_trade: float = np.nan,
    tactical_event_id: int = 0,
) -> float:
    if budget <= 0 or price <= 0:
        return 0.0
    available = {
        "normal": state.normal_cash,
        "pending": state.pending_dca_cash,
        "tactical": state.tactical_cash,
    }.get(ledger)
    if available is None:
        raise ValueError(f"Unknown buy ledger: {ledger}")
    budget = min(float(budget), float(available))
    if budget <= 0:
        return 0.0
    effective = price * (1.0 + scenario.slippage)
    quantity = budget / (effective * (1.0 + scenario.fee))
    gross = quantity * price
    slippage = quantity * (effective - price)
    fee = quantity * effective * scenario.fee
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
        effective_price=effective,
        gross_notional=gross,
        cash_change=-budget,
        fee_usd=fee,
        slippage_usd=slippage,
        ledger=ledger,
        signal_date=signal_date,
        reason=reason,
        event_before_exposure=event_before_exposure,
        target_exposure=target_exposure,
        days_since_previous_tactical_trade=days_since_previous_tactical_trade,
        tactical_event_id=tactical_event_id,
    )
    return budget


def _sell(
    state: V3State,
    asset: str,
    gross: float,
    price: float,
    prices: dict[str, float],
    *,
    timestamp: pd.Timestamp,
    scenario: V3Scenario,
    action: str,
    trade_rows: list[dict[str, Any]],
    signal_date: Any,
    reason: str,
    event_before_exposure: float,
    target_exposure: float,
    days_since_previous_tactical_trade: float,
    tactical_event_id: int,
    invalidation: bool,
) -> float:
    available = state.qty[asset] * price
    gross = min(max(0.0, float(gross)), available)
    if gross <= 0 or price <= 0:
        return 0.0
    quantity = gross / price
    effective = price * (1.0 - scenario.slippage)
    before_fee = quantity * effective
    fee = before_fee * scenario.fee
    proceeds = before_fee - fee
    slippage = quantity * (price - effective)
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
        effective_price=effective,
        gross_notional=gross,
        cash_change=proceeds,
        fee_usd=fee,
        slippage_usd=slippage,
        ledger="tactical",
        signal_date=signal_date,
        reason=reason,
        event_before_exposure=event_before_exposure,
        target_exposure=target_exposure,
        days_since_previous_tactical_trade=days_since_previous_tactical_trade,
        tactical_event_id=tactical_event_id,
        invalidation=invalidation,
    )
    return gross


def _gross_to_target(state: V3State, prices: dict[str, float], target: float, scenario: V3Scenario) -> float:
    crypto = sum(_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total <= target:
        return 0.0
    conversion = (1.0 - scenario.slippage) * (1.0 - scenario.fee)
    cost_fraction = 1.0 - conversion
    return max(0.0, (crypto - target * total) / max(1e-12, 1.0 - target * cost_fraction))


def _budget_to_target(state: V3State, prices: dict[str, float], target: float, scenario: V3Scenario) -> float:
    crypto = sum(_values(state, prices).values())
    total = _portfolio_value(state, prices)
    if total <= 0 or crypto / total >= target:
        return 0.0
    conversion = 1.0 / ((1.0 + scenario.slippage) * (1.0 + scenario.fee))
    return max(0.0, (target * total - crypto) / max(1e-12, conversion + target * (1.0 - conversion)))


def _tactical_guard(state: V3State, prices: dict[str, float], target: float, notional: float, rules: dict[str, Any]) -> tuple[bool, str]:
    guard = rules["turnover_guard"]
    total = _portfolio_value(state, prices)
    gap = abs(_exposure(state, prices) - target)
    minimum = max(float(guard["minimum_notional_usd"]), float(guard["minimum_portfolio_fraction"]) * total)
    if gap + 1e-12 < float(guard["minimum_exposure_gap"]):
        return False, "exposure_gap_below_guard"
    if notional + 1e-10 < minimum:
        return False, "notional_below_guard"
    return True, "pass"


def _rank_sell_assets(state: V3State, prices: dict[str, float], row: pd.Series, rules: dict[str, Any]) -> list[str]:
    allocations = _allocations(state, prices)
    weights = rules["target_weights"]
    return sorted(
        ASSETS,
        key=lambda asset: (
            allocations[asset] - float(weights[asset]),
            float(row.get(f"{asset}_weakness_score", 0.0) if pd.notna(row.get(f"{asset}_weakness_score", 0.0)) else 0.0),
            asset,
        ),
        reverse=True,
    )


def _sell_to_target(
    state: V3State,
    row: pd.Series,
    prices: dict[str, float],
    target: float,
    rules: dict[str, Any],
    scenario: V3Scenario,
    trade_rows: list[dict[str, Any]],
    *,
    action: str,
    reason: str,
    invalidation: bool,
) -> tuple[float, str]:
    target = max(float(target), scenario.hard_floor)
    before = _exposure(state, prices)
    gross = min(
        _gross_to_target(state, prices, target, scenario),
        _gross_to_target(state, prices, scenario.hard_floor, scenario),
    )
    passed, guard_reason = _tactical_guard(state, prices, target, gross, rules)
    if not passed:
        return 0.0, guard_reason
    timestamp = pd.Timestamp(row["open_time"])
    since = _days_since(timestamp, state.last_tactical_trade_at)
    state.tactical_event_id += 1
    event_id = state.tactical_event_id
    sold = 0.0
    minimums = rules["modeled_min_notional_usdt"]
    for asset in _rank_sell_assets(state, prices, row, rules):
        remaining = gross - sold
        if remaining <= 1e-8:
            break
        amount = min(state.qty[asset] * prices[asset], remaining)
        if amount + 1e-10 < float(minimums[asset]):
            continue
        sold += _sell(
            state,
            asset,
            amount,
            prices[asset],
            prices,
            timestamp=timestamp,
            scenario=scenario,
            action=action,
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
            reason=reason,
            event_before_exposure=before,
            target_exposure=target,
            days_since_previous_tactical_trade=since,
            tactical_event_id=event_id,
            invalidation=invalidation,
        )
    if sold > 0:
        state.last_tactical_trade_at = timestamp
        if action == "TACTICAL_SELL_DRIFT":
            state.last_drift_sell_at = timestamp
    if _exposure(state, prices) + 1e-10 < scenario.hard_floor:
        raise AssertionError("Tactical sell breached the sell-time hard floor")
    return sold, "executed" if sold > 0 else "minimum_notional"


def _buy_underweight_to_target(
    state: V3State,
    row: pd.Series,
    prices: dict[str, float],
    target: float,
    rules: dict[str, Any],
    scenario: V3Scenario,
    trade_rows: list[dict[str, Any]],
    *,
    action: str,
    reason: str,
    budget_cap: float | None = None,
) -> tuple[float, str]:
    target = min(float(target), 0.95)
    before = _exposure(state, prices)
    needed = min(_budget_to_target(state, prices, target, scenario), state.tactical_cash)
    if budget_cap is not None:
        needed = min(needed, float(budget_cap))
    passed, guard_reason = _tactical_guard(state, prices, target, needed, rules)
    if not passed:
        return 0.0, guard_reason
    timestamp = pd.Timestamp(row["open_time"])
    since = _days_since(timestamp, state.last_tactical_trade_at)
    state.tactical_event_id += 1
    event_id = state.tactical_event_id
    values = _values(state, prices)
    conversion = 1.0 / ((1.0 + scenario.slippage) * (1.0 + scenario.fee))
    post_crypto = sum(values.values()) + needed * conversion
    gaps = {asset: max(0.0, float(rules["target_weights"][asset]) * post_crypto - values[asset]) for asset in ASSETS}
    minimums = rules["modeled_min_notional_usdt"]
    minimum = min(float(value) for value in minimums.values())
    remaining = needed
    spent = 0.0
    for asset in sorted(ASSETS, key=lambda item: (gaps[item], item), reverse=True):
        if remaining + 1e-10 < minimum:
            break
        amount = min(remaining, gaps[asset] / conversion if gaps[asset] > 0 else remaining)
        if amount + 1e-10 < float(minimums[asset]):
            continue
        used = _buy(
            state,
            asset,
            amount,
            prices[asset],
            prices,
            timestamp=timestamp,
            scenario=scenario,
            action=action,
            ledger="tactical",
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
            reason=reason,
            event_before_exposure=before,
            target_exposure=target,
            days_since_previous_tactical_trade=since,
            tactical_event_id=event_id,
        )
        spent += used
        remaining -= used
    if remaining + 1e-10 >= minimum:
        allocations = _allocations(state, prices)
        asset = min(ASSETS, key=lambda item: allocations[item] - float(rules["target_weights"][item]))
        spent += _buy(
            state,
            asset,
            remaining,
            prices[asset],
            prices,
            timestamp=timestamp,
            scenario=scenario,
            action=action,
            ledger="tactical",
            trade_rows=trade_rows,
            signal_date=row.get("signal_date"),
            reason=reason,
            event_before_exposure=before,
            target_exposure=target,
            days_since_previous_tactical_trade=since,
            tactical_event_id=event_id,
        )
    if spent > 0:
        state.last_tactical_trade_at = timestamp
        state.last_tactical_buy_at = timestamp
    return spent, "executed" if spent > 0 else "minimum_notional"


def _stage_target(stage: int, scenario: V3Scenario, rules: dict[str, Any]) -> float:
    if stage == 4:
        key = f"{scenario.hard_floor:.1f}"
        return float(rules["stage4_target_by_floor"][key])
    return float(rules["stage_exposure_targets"][str(stage)])


def _macro_target(state: V3State, scenario: V3Scenario, rules: dict[str, Any]) -> float:
    if state.macro_regime == "NEW_BULL":
        return float(rules["new_bull"]["completion_exposure"])
    if state.macro_regime in {"BULL", "LATE_BULL"}:
        return float(rules["stage_exposure_targets"]["0"])
    return _stage_target(state.sell_stage, scenario, rules)


def _new_cycle(
    state: V3State,
    row: pd.Series,
    trigger: str,
    *,
    confirmed: bool = False,
) -> dict[str, Any]:
    cycle_id = state.next_cycle_id
    state.next_cycle_id += 1
    state.active_cycle_id = cycle_id
    state.buyback_done = {key: False for key in state.buyback_done}
    return {
        "cycle_id": cycle_id,
        "cycle_start": row.get("signal_date"),
        "start_execution": row.get("open_time"),
        "start_trigger": trigger,
        "cycle_confirmed": confirmed,
        "cycle_confirmed_date": row.get("signal_date") if confirmed else pd.NaT,
        "cycle_end": pd.NaT,
        "reset_date": pd.NaT,
        "redeployment_complete_date": pd.NaT,
        "redeployment_interrupted_date": pd.NaT,
        "status": "OPEN",
        "stage_1_date": pd.NaT,
        "stage_1_execution": pd.NaT,
        "stage_1_btc_price": np.nan,
        "stage_1_portfolio_exposure": np.nan,
        "stage_2_date": pd.NaT,
        "stage_2_execution": pd.NaT,
        "stage_2_btc_price": np.nan,
        "stage_2_portfolio_exposure": np.nan,
        "stage_3_date": pd.NaT,
        "stage_3_execution": pd.NaT,
        "stage_3_btc_price": np.nan,
        "stage_3_portfolio_exposure": np.nan,
        "stage_4_date": pd.NaT,
        "stage_4_execution": pd.NaT,
        "stage_4_btc_price": np.nan,
        "stage_4_portfolio_exposure": np.nan,
        "NEW_BULL_date": pd.NaT,
        "NEW_BULL_execution": pd.NaT,
    }


def _active_cycle(state: V3State, cycles: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in reversed(cycles) if item["cycle_id"] == state.active_cycle_id), None)


def _record_stage(cycle: dict[str, Any], stage: int, row: pd.Series, state: V3State, prices: dict[str, float]) -> None:
    if pd.notna(cycle[f"stage_{stage}_date"]):
        return
    cycle[f"stage_{stage}_date"] = row.get("signal_date")
    cycle[f"stage_{stage}_execution"] = row.get("open_time")
    cycle[f"stage_{stage}_btc_price"] = float(row.get("BTC_daily_close"))
    cycle[f"stage_{stage}_portfolio_exposure"] = _exposure(state, prices)


def _transition(state: V3State, to_state: str, reason: str, rules: dict[str, Any]) -> None:
    from_state = state.macro_regime
    if to_state not in rules["allowed_transitions"][from_state]:
        raise AssertionError(f"Illegal FSM transition: {from_state} -> {to_state} ({reason})")
    if to_state != from_state:
        state.macro_regime = to_state
        state.regime_days = 0


def _enter_new_bull(state: V3State, cycle: dict[str, Any], row: pd.Series, rules: dict[str, Any]) -> None:
    cycle["NEW_BULL_date"] = row.get("signal_date")
    cycle["NEW_BULL_execution"] = row.get("open_time")
    cycle["status"] = "NEW_BULL_REDEPLOYING"
    state.redeploy_cycle_id = state.active_cycle_id
    state.redeploy_days_remaining = int(rules["new_bull"]["redeploy_trading_days"])
    state.sell_stage = 0
    state.active_exposure_target = float(rules["new_bull"]["completion_exposure"])
    state.ordinary_risk_off_lock_days = int(rules["new_bull"]["post_confirmation_ordinary_risk_off_lock_days"])


def _process_signal(
    state: V3State,
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: V3Scenario,
    trades: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
) -> tuple[list[str], str]:
    actions: list[str] = []
    state.signal_index += 1
    state.regime_days += 1
    if state.ordinary_risk_off_lock_days > 0:
        state.ordinary_risk_off_lock_days -= 1

    previous_state = state.macro_regime
    next_state = previous_state
    transition_reason = "STATE_PERSISTENCE"
    crash_event = _truth(row.get("crash_override_event"))
    crash_raw = _truth(row.get("crash_override_raw"))
    risk_off_decision = ""
    stage_event: int | None = None
    cycle = _active_cycle(state, cycles)

    signal_date = pd.Timestamp(row.get("signal_date"))
    signal_close = float(row.get("BTC_daily_close"))
    if previous_state in {"BEAR", "DEEP_BEAR", "ACCUMULATION"}:
        if signal_close < state.bear_low_price:
            state.bear_low_price = signal_close
            state.bear_low_date = signal_date
    days_since_bear_low = (
        (signal_date - pd.Timestamp(state.bear_low_date)).total_seconds() / 86_400.0
        if state.bear_low_date is not None and pd.notna(state.bear_low_date)
        else float("nan")
    )
    state.new_bull_gate_7 = bool(
        np.isfinite(days_since_bear_low)
        and days_since_bear_low >= float(rules["new_bull"]["minimum_days_since_bear_low"])
    )

    ahr = float(row.get("ahr999_fixed_arithmetic")) if pd.notna(row.get("ahr999_fixed_arithmetic")) else np.nan
    no_new_low_10d = bool(np.isfinite(days_since_bear_low) and days_since_bear_low >= 10.0)
    value_structure = (
        signal_close <= float(rules["macro"]["price_to_sma200_deep_bear"]) * float(row.get("sma200"))
        or float(row.get("BTC_daily_low")) <= float(row.get("bb_lower"))
        or float(row.get("peak_to_close_drawdown_90d")) <= float(rules["macro"]["drawdown_90d"])
        or no_new_low_10d
    )
    value_path = bool(np.isfinite(ahr) and ahr <= 0.35 and value_structure)
    right_path = _truth(row.get("right_recovery_confirmed")) and not _truth(row.get("new_bull_confirmed"))
    accumulation_entry = value_path or right_path

    if previous_state == "BULL":
        if state.ordinary_risk_off_lock_days == 0 and _truth(row.get("distribution_confirmed")):
            next_state, transition_reason = "DISTRIBUTION", "DISTRIBUTION_2D_CONFIRMED"
        elif _truth(row.get("late_bull_condition")):
            next_state, transition_reason = "LATE_BULL", "LATE_BULL_CONTEXT_CONFIRMED"
    elif previous_state == "LATE_BULL":
        if state.ordinary_risk_off_lock_days == 0 and _truth(row.get("distribution_confirmed")):
            next_state, transition_reason = "DISTRIBUTION", "DISTRIBUTION_2D_CONFIRMED"
        else:
            state.late_bull_absent_days = 0 if _truth(row.get("late_bull_condition")) else state.late_bull_absent_days + 1
            if (
                state.late_bull_absent_days >= int(rules["macro"]["late_bull_invalidation_days"])
                and state.regime_days >= int(rules["macro"]["late_bull_min_persistence_days"])
                and _truth(row.get("bull_condition"))
            ):
                next_state, transition_reason = "BULL", "LATE_BULL_CONTEXT_CLEARED"
    elif previous_state == "DISTRIBUTION":
        if _truth(row.get("stage2_confirmed")):
            next_state, transition_reason = "EARLY_BEAR", "EARLY_BEAR_2D_CONFIRMED"
        elif _truth(row.get("distribution_invalidation_confirmed")) and not bool((cycle or {}).get("cycle_confirmed", False)):
            next_state, transition_reason = "BULL", "DISTRIBUTION_INVALIDATED_3D"
    elif previous_state == "EARLY_BEAR":
        if _truth(row.get("stage3_confirmed")):
            next_state, transition_reason = "BEAR", "MACRO_BEAR_2D_CONFIRMED"
        elif _truth(row.get("early_bear_repair_confirmed")):
            next_state, transition_reason = "DISTRIBUTION", "EARLY_BEAR_SHORT_TERM_REPAIR_3D"
    elif previous_state == "BEAR":
        if _truth(row.get("deep_bear_confirmed")):
            next_state, transition_reason = "DEEP_BEAR", "DEEP_BEAR_3D_CONFIRMED"
        elif accumulation_entry:
            next_state = "ACCUMULATION"
            transition_reason = "ACCUMULATION_VALUE_PATH" if value_path else "ACCUMULATION_RIGHT_SIDE_PATH"
    elif previous_state == "DEEP_BEAR":
        if accumulation_entry:
            next_state = "ACCUMULATION"
            transition_reason = "ACCUMULATION_VALUE_PATH" if value_path else "ACCUMULATION_RIGHT_SIDE_PATH"
        elif _truth(row.get("deep_bear_exit_confirmed")):
            next_state, transition_reason = "BEAR", "DEEP_BEAR_CONDITION_CLEARED_3D"
    elif previous_state == "ACCUMULATION":
        if _truth(row.get("accumulation_failure_raw")):
            if _truth(row.get("deep_bear_confirmed")):
                next_state, transition_reason = "DEEP_BEAR", "ACCUMULATION_FAILURE_DEEP_BEAR"
            else:
                next_state, transition_reason = "BEAR", "ACCUMULATION_FAILURE_BEAR"
        elif _truth(row.get("new_bull_confirmed")) and state.new_bull_gate_7:
            next_state, transition_reason = "NEW_BULL", "NEW_BULL_ALL_7_GATES_CONFIRMED"
    elif previous_state == "NEW_BULL":
        if _truth(row.get("failed_new_bull_raw")):
            next_state, transition_reason = "EARLY_BEAR", "FAILED_NEW_BULL"
        elif (
            state.regime_days >= int(rules["new_bull"]["post_confirmation_ordinary_risk_off_lock_days"])
            and not crash_raw
            and signal_close > float(row.get("sma200"))
            and _truth(row.get("new_bull_gate_3_sma50_up"))
            and not _truth(row.get("stage3_raw"))
            and not _truth(row.get("deep_bear_raw"))
        ):
            next_state, transition_reason = "BULL", "NEW_BULL_PROTECTION_COMPLETE"

    if next_state != previous_state:
        _transition(state, next_state, transition_reason, rules)
        actions.append(f"FSM_{previous_state}_TO_{next_state}")

        if previous_state in {"BULL", "LATE_BULL"} and next_state == "DISTRIBUTION":
            cycle = _new_cycle(state, row, "DISTRIBUTION_CANDIDATE", confirmed=False)
            cycles.append(cycle)
            state.sell_stage = 1
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(1, scenario, rules))
            stage_event = 1
            risk_off_decision = "stage_1_distribution"
            counters["sell_stage_1_count"] += 1
        elif previous_state == "DISTRIBUTION" and next_state == "EARLY_BEAR":
            cycle = _active_cycle(state, cycles)
            if cycle is None:
                raise AssertionError("DISTRIBUTION -> EARLY_BEAR without candidate cycle")
            first_confirmation = not bool(cycle["cycle_confirmed"])
            cycle["cycle_confirmed"] = True
            if first_confirmation:
                cycle["cycle_confirmed_date"] = row.get("signal_date")
            cycle["status"] = "CONFIRMED"
            state.sell_stage = 2
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(2, scenario, rules))
            stage_event = 2
            risk_off_decision = "stage_2_early_bear"
            counters["sell_stage_2_count"] += 1
            if first_confirmation:
                counters["confirmed_macro_cycle_count"] += 1
        elif previous_state == "DISTRIBUTION" and next_state == "BULL":
            cycle = _active_cycle(state, cycles)
            if cycle is None:
                raise AssertionError("DISTRIBUTION invalidation without candidate cycle")
            cycle["cycle_end"] = row.get("signal_date")
            cycle["reset_date"] = row.get("signal_date")
            cycle["status"] = "ABORTED_DISTRIBUTION"
            state.active_cycle_id = 0
            state.sell_stage = 0
            state.active_exposure_target = float(rules["stage_exposure_targets"]["0"])
            counters["aborted_distribution_count"] += 1
        elif previous_state == "EARLY_BEAR" and next_state == "DISTRIBUTION":
            state.sell_stage = 1
        elif previous_state == "EARLY_BEAR" and next_state == "BEAR":
            state.sell_stage = 3
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(3, scenario, rules))
            state.bear_low_price = signal_close
            state.bear_low_date = signal_date
            stage_event = 3
            risk_off_decision = "stage_3_macro_bear"
            counters["sell_stage_3_count"] += 1
        elif previous_state == "BEAR" and next_state == "DEEP_BEAR":
            state.sell_stage = 4
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(4, scenario, rules))
            stage_event = 4
            risk_off_decision = "stage_4_deep_bear"
            counters["sell_stage_4_count"] += 1
        elif previous_state == "DEEP_BEAR" and next_state == "BEAR":
            state.sell_stage = 3
        elif previous_state == "ACCUMULATION" and next_state in {"BEAR", "DEEP_BEAR"}:
            state.sell_stage = 4 if next_state == "DEEP_BEAR" else 3
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(state.sell_stage, scenario, rules))
            risk_off_decision = transition_reason.lower()
            if next_state == "DEEP_BEAR":
                stage_event = 4
        elif previous_state == "ACCUMULATION" and next_state == "NEW_BULL":
            cycle = _active_cycle(state, cycles)
            if cycle is None or not bool(cycle["cycle_confirmed"]):
                raise AssertionError("ACCUMULATION -> NEW_BULL without confirmed cycle")
            _enter_new_bull(state, cycle, row, rules)
            counters["new_bull_count"] += 1
            actions.append("SELL_STAGE_RESET")
        elif previous_state == "NEW_BULL" and next_state == "BULL":
            cycle = _active_cycle(state, cycles)
            if cycle is None:
                raise AssertionError("NEW_BULL -> BULL without active cycle")
            cycle["cycle_end"] = row.get("signal_date")
            cycle["reset_date"] = row.get("signal_date")
            cycle["status"] = "CLOSED"
            state.active_cycle_id = 0
            state.redeploy_cycle_id = 0
            state.redeploy_days_remaining = 0
            state.sell_stage = 0
            state.active_exposure_target = float(rules["stage_exposure_targets"]["0"])
        elif previous_state == "NEW_BULL" and next_state == "EARLY_BEAR":
            old_cycle = _active_cycle(state, cycles)
            if old_cycle is not None:
                old_cycle["cycle_end"] = row.get("signal_date")
                old_cycle["reset_date"] = row.get("signal_date")
                old_cycle["redeployment_interrupted_date"] = row.get("signal_date")
                old_cycle["status"] = "FAILED_NEW_BULL"
            state.active_cycle_id = 0
            state.redeploy_cycle_id = 0
            state.redeploy_days_remaining = 0
            cycle = _new_cycle(state, row, "FAILED_NEW_BULL", confirmed=True)
            cycles.append(cycle)
            state.sell_stage = 2
            state.active_exposure_target = min(state.active_exposure_target, _stage_target(2, scenario, rules))
            stage_event = 2
            risk_off_decision = "failed_new_bull_early_bear"
            counters["sell_stage_2_count"] += 1
            counters["confirmed_macro_cycle_count"] += 1

    if crash_event:
        counters["crash_override_event_count"] += 1
        state.active_exposure_target = min(state.active_exposure_target, _stage_target(2, scenario, rules))
        actions.append("CRASH_OVERRIDE_EVENT")
        if not risk_off_decision:
            risk_off_decision = "crash_override_overlay"

    urgent_risk_off = bool(risk_off_decision or crash_event)
    if urgent_risk_off:
        action = "TACTICAL_SELL_CRASH_OVERRIDE" if crash_event else (
            f"TACTICAL_SELL_STAGE_{stage_event}" if stage_event is not None else "TACTICAL_SELL_INVALIDATION"
        )
        sold, guard_reason = _sell_to_target(
            state,
            row,
            prices,
            state.active_exposure_target,
            rules,
            scenario,
            trades,
            action=action,
            reason=risk_off_decision,
            invalidation=True,
        )
        actions.append(f"{action}:{guard_reason}")
        if sold > 0:
            counters["tactical_sell_events"] += 1
        cycle = _active_cycle(state, cycles)
        if cycle is not None and stage_event is not None:
            _record_stage(cycle, stage_event, row, state, prices)

    cycle = _active_cycle(state, cycles)
    if cycle is not None and state.macro_regime == "ACCUMULATION" and not urgent_risk_off:
        extreme_price = (
            signal_close <= float(row.get("bb_lower"))
            or signal_close <= float(rules["macro"]["price_to_sma200_deep_bear"]) * float(row.get("sma200"))
        )
        candidates: list[tuple[float, str]] = []
        if np.isfinite(ahr) and ahr <= float(rules["buyback"]["ahr_extreme"]["upper_inclusive"]) and extreme_price and not state.buyback_done["ahr_extreme"]:
            candidates.append((float(rules["buyback"]["ahr_extreme"]["active_target"]), "ahr_extreme"))
        if np.isfinite(ahr) and ahr < float(rules["buyback"]["ahr_below_030"]["upper_exclusive"]) and not state.buyback_done["ahr_below_030"]:
            candidates.append((float(rules["buyback"]["ahr_below_030"]["active_target"]), "ahr_below_030"))
        if (
            np.isfinite(ahr)
            and float(rules["buyback"]["ahr_030_035"]["lower_inclusive"]) <= ahr <= float(rules["buyback"]["ahr_030_035"]["upper_inclusive"])
            and not state.buyback_done["ahr_030_035"]
        ):
            candidates.append((float(rules["buyback"]["ahr_030_035"]["active_target"]), "ahr_030_035"))
        if right_path and not state.buyback_done["right_recovery"]:
            candidates.append((float(rules["buyback"]["right_recovery"]["active_target"]), "right_recovery"))
        candidates = [(target, trigger) for target, trigger in candidates if target > state.active_exposure_target + 1e-12]
        if candidates:
            target, trigger = max(candidates, key=lambda item: (item[0], item[1]))
            spent, guard_reason = _buy_underweight_to_target(
                state,
                row,
                prices,
                target,
                rules,
                scenario,
                trades,
                action=f"TACTICAL_BUYBACK_{trigger.upper()}",
                reason=trigger,
            )
            actions.append(f"BUYBACK_{trigger}:{guard_reason}")
            if spent > 0:
                state.active_exposure_target = target
                state.buyback_done[trigger] = True
                counters[f"{trigger}_buy_count"] += 1
                counters["tactical_buy_events"] += 1

    if state.macro_regime == "NEW_BULL" and state.redeploy_days_remaining > 0:
        completion = float(rules["new_bull"]["completion_exposure"])
        budget_cap = state.tactical_cash / state.redeploy_days_remaining
        spent, guard_reason = _buy_underweight_to_target(
            state,
            row,
            prices,
            completion,
            rules,
            scenario,
            trades,
            action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
            reason=f"new_bull_redeploy_day_{int(rules['new_bull']['redeploy_trading_days']) - state.redeploy_days_remaining + 1}",
            budget_cap=budget_cap,
        )
        actions.append(f"NEW_BULL_REDEPLOY:{guard_reason}")
        if spent > 0:
            counters["new_bull_redeploy_events"] += 1
        state.redeploy_days_remaining -= 1
        if state.redeploy_days_remaining == 0 or _exposure(state, prices) >= completion - 1e-8:
            cycle = _active_cycle(state, cycles)
            if cycle is not None:
                cycle["redeployment_complete_date"] = row.get("signal_date")
                cycle["status"] = "NEW_BULL_PROTECTION"
            state.redeploy_days_remaining = 0
            actions.append("NEW_BULL_REDEPLOY_COMPLETE")

    guard = rules["turnover_guard"]
    if (
        state.active_cycle_id > 0
        and not urgent_risk_off
        and state.macro_regime in {"DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR"}
    ):
        current = _exposure(state, prices)
        sell_wait = _days_since(pd.Timestamp(row["open_time"]), state.last_drift_sell_at)
        buy_wait = _days_since(pd.Timestamp(row["open_time"]), state.last_tactical_buy_at)
        if (
            current > state.active_exposure_target + float(guard["drift_sell_gap"])
            and (np.isnan(sell_wait) or sell_wait >= float(guard["tactical_cooldown_days"]))
            and (np.isnan(buy_wait) or buy_wait >= float(guard["buyback_to_drift_sell_block_days"]))
        ):
            sold, guard_reason = _sell_to_target(
                state,
                row,
                prices,
                state.active_exposure_target,
                rules,
                scenario,
                trades,
                action="TACTICAL_SELL_DRIFT",
                reason="ordinary_drift_above_active_target",
                invalidation=False,
            )
            actions.append(f"TACTICAL_SELL_DRIFT:{guard_reason}")
            if sold > 0:
                counters["tactical_sell_events"] += 1

    return actions, transition_reason


def _dca_plan(model_a: BacktestResult) -> dict[pd.Timestamp, list[dict[str, Any]]]:
    plan: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    dca = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")].copy()
    for timestamp, group in dca.groupby("timestamp", sort=True):
        plan[pd.Timestamp(timestamp)] = group[["asset", "cash_change_usd"]].to_dict("records")
    return plan


def run_macro_cycle_hedge(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: V3Scenario,
    model_a: BacktestResult,
    *,
    record_signals: bool = True,
) -> V3BacktestResult:
    if frame.empty:
        raise ValueError("No formal-period bars supplied")
    if len(frame) != len(model_a.history):
        raise ValueError("Model A history does not align with V3 frame")
    if not pd.Series(frame["open_time"].to_numpy()).equals(pd.Series(model_a.history["timestamp"].to_numpy())):
        raise ValueError("Model A timestamps do not align with V3 frame")

    state = V3State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    history_rows: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    counters: dict[str, Any] = {
        "sell_stage_1_count": 0,
        "sell_stage_2_count": 0,
        "sell_stage_3_count": 0,
        "sell_stage_4_count": 0,
        "ahr_030_035_buy_count": 0,
        "ahr_below_030_buy_count": 0,
        "ahr_extreme_buy_count": 0,
        "right_recovery_buy_count": 0,
        "new_bull_count": 0,
        "new_bull_redeploy_events": 0,
        "confirmed_macro_cycle_count": 0,
        "aborted_distribution_count": 0,
        "crash_override_event_count": 0,
        "tactical_sell_events": 0,
        "tactical_buy_events": 0,
        "dca_cash_shortfall_count": 0,
    }
    dca_plan = _dca_plan(model_a)
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS}
    for asset in ASSETS:
        _buy(
            state,
            asset,
            float(rules["initial_allocation_usd"][asset]),
            first_prices[asset],
            first_prices,
            timestamp=pd.Timestamp(first["open_time"]),
            scenario=scenario,
            action="INITIAL_ALLOCATION",
            ledger="normal",
            trade_rows=trades,
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
        a_row = model_a.history.iloc[position]
        external_flow = float(a_row["external_flow"])
        committed = float(a_row["committed_dca"])
        intended = float(rules["external_contribution_per_4h"]) * float(a_row["elapsed_4h_intervals"])
        state.normal_cash += external_flow

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_regime = state.macro_regime
        before_stage = state.sell_stage
        before_target = state.active_exposure_target
        before_cycle = state.active_cycle_id
        before_exposure = _exposure(state, prices_open)
        actions: list[str] = []
        decision = "none"
        if is_new_signal:
            actions, decision = _process_signal(state, row, prices_open, rules, scenario, trades, cycles, counters)
            state.last_signal_date = row.get("signal_date")

        if state.normal_cash + 1e-10 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3 normal cash cannot replay Model A DCA")
        state.normal_cash -= committed
        state.pending_dca_cash += committed
        executed = 0.0
        for instruction in dca_plan.get(timestamp, []):
            asset = str(instruction["asset"])
            budget = -float(instruction["cash_change_usd"])
            executed += _buy(
                state,
                asset,
                budget,
                prices_open[asset],
                prices_open,
                timestamp=timestamp,
                scenario=scenario,
                action="NORMAL_DCA",
                ledger="pending",
                trade_rows=trades,
                signal_date=row.get("signal_date"),
            )
        if abs(executed - float(a_row["executed_dca"])) > 1e-8:
            raise AssertionError("V3 executed DCA diverged from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        values = _values(state, prices_close)
        crypto_value = sum(values.values())
        crypto_exposure = crypto_value / end_value if end_value > 0 else 0.0
        allocations = _allocations(state, prices_close)
        total_cash = state.normal_cash + state.pending_dca_cash + state.tactical_cash
        tactical_ratio = state.tactical_cash / end_value if end_value > 0 else 0.0
        if previous_closes is None:
            target_return = 0.0
        else:
            target_return = sum(
                float(rules["target_weights"][asset]) * (prices_close[asset] / previous_closes[asset] - 1.0)
                for asset in ASSETS
            )
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
                "elapsed_4h_intervals": int(a_row["elapsed_4h_intervals"]),
                "normal_cash": state.normal_cash,
                "pending_dca_cash": state.pending_dca_cash,
                "tactical_cash": state.tactical_cash,
                "normal_cash_ratio": state.normal_cash / end_value if end_value > 0 else 0.0,
                "total_cash_ratio": total_cash / end_value if end_value > 0 else 0.0,
                "tactical_cash_ratio": tactical_ratio,
                "crypto_exposure": crypto_exposure,
                "BTC_allocation": allocations["BTC"],
                "ETH_allocation": allocations["ETH"],
                "BNB_allocation": allocations["BNB"],
                "BTC_close": prices_close["BTC"],
                "ETH_close": prices_close["ETH"],
                "BNB_close": prices_close["BNB"],
                "BTC_signal_close": row.get("BTC_daily_close"),
                "BTC_signal_low": row.get("BTC_daily_low"),
                "sma10": row.get("sma10"),
                "sma20": row.get("sma20"),
                "sma50": row.get("sma50"),
                "sma200": row.get("sma200"),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "macro_regime_previous": before_regime,
                "macro_regime_current": state.macro_regime,
                "macro_regime": state.macro_regime,
                "transition_reason": decision,
                "sell_stage": state.sell_stage,
                "sell_cycle_id": state.active_cycle_id,
                "redeploy_cycle_id": state.redeploy_cycle_id,
                "cycle_confirmed": bool((_active_cycle(state, cycles) or {}).get("cycle_confirmed", False)),
                "days_in_current_regime": state.regime_days,
                "target_crypto_exposure": _macro_target(state, scenario, rules),
                "active_exposure_target": state.active_exposure_target,
                "crash_override": _truth(row.get("crash_override_raw")),
                "crash_override_event": _truth(row.get("crash_override_event")) if is_new_signal else False,
                "ordinary_risk_off_lock_days": state.ordinary_risk_off_lock_days,
                "redeploy_days_remaining": state.redeploy_days_remaining,
                "new_bull_gate_1": _truth(row.get("new_bull_gate_1_above_sma200")),
                "new_bull_gate_2": _truth(row.get("new_bull_gate_2_sma200_flat")),
                "new_bull_gate_3": _truth(row.get("new_bull_gate_3_sma50_up")),
                "new_bull_gate_4": _truth(row.get("new_bull_gate_4_alignment")),
                "new_bull_gate_5": _truth(row.get("new_bull_gate_5_close_above_sma50")),
                "new_bull_gate_6": _truth(row.get("new_bull_gate_6_crash_free")),
                "new_bull_gate_7": state.new_bull_gate_7,
                "theoretical_dca": float(rules["external_contribution_per_4h"]),
                "protected_dca": float(rules["external_contribution_per_4h"]),
                "intended_dca": intended,
                "committed_dca": committed,
                "executed_dca": executed,
                "target_basket_return": target_return,
                "cash_drag_increment": (total_cash / end_value if end_value > 0 else 0.0) * target_return,
                "tactical_cash_drag_increment": tactical_ratio * target_return,
                "daily_floor_breach_reason": "market_move_after_tactical_sell" if crypto_exposure < scenario.hard_floor - 1e-10 else "none",
            }
        )

        if is_new_signal and record_signals:
            signal_rows.append(
                {
                    "signal_date": row.get("signal_date"),
                    "signal_available_at": row.get("signal_available_at"),
                    "execution_4h_open": timestamp,
                    "btc_close": row.get("BTC_daily_close"),
                    "btc_low": row.get("BTC_daily_low"),
                    "sma10": row.get("sma10"),
                    "sma20": row.get("sma20"),
                    "sma50": row.get("sma50"),
                    "sma200": row.get("sma200"),
                    "bb_lower": row.get("bb_lower"),
                    "ahr999": row.get("ahr999_fixed_arithmetic"),
                    "bull_condition": row.get("bull_condition"),
                    "late_bull_condition": row.get("late_bull_condition"),
                    "distribution_confirmed": row.get("distribution_confirmed"),
                    "stage2_confirmed": row.get("stage2_confirmed"),
                    "stage3_condition_count": row.get("stage3_condition_count"),
                    "stage3_confirmed": row.get("stage3_confirmed"),
                    "deep_bear_confirmed": row.get("deep_bear_confirmed"),
                    "crash_rule_a": row.get("crash_rule_a"),
                    "crash_rule_b": row.get("crash_rule_b"),
                    "crash_rule_c": row.get("crash_rule_c"),
                    "crash_override_raw": row.get("crash_override_raw"),
                    "crash_override_event": row.get("crash_override_event"),
                    "right_recovery_confirmed": row.get("right_recovery_confirmed"),
                    "new_bull_gate_1_above_sma200": row.get("new_bull_gate_1_above_sma200"),
                    "new_bull_gate_2_sma200_flat": row.get("new_bull_gate_2_sma200_flat"),
                    "new_bull_gate_3_sma50_up": row.get("new_bull_gate_3_sma50_up"),
                    "new_bull_gate_4_alignment": row.get("new_bull_gate_4_alignment"),
                    "new_bull_gate_5_close_above_sma50": row.get("new_bull_gate_5_close_above_sma50"),
                    "new_bull_gate_6_crash_free": row.get("new_bull_gate_6_crash_free"),
                    "new_bull_gate_7_days_since_bear_low": state.new_bull_gate_7,
                    "new_bull_confirmed": row.get("new_bull_confirmed"),
                    "regime_before": before_regime,
                    "regime_after": state.macro_regime,
                    "sell_stage_before": before_stage,
                    "sell_stage_after": state.sell_stage,
                    "active_target_before": before_target,
                    "active_target_after": state.active_exposure_target,
                    "cycle_id_before": before_cycle,
                    "cycle_id_after": state.active_cycle_id,
                    "crypto_exposure_before": before_exposure,
                    "actions": "|".join(actions),
                    "decision_reason": decision,
                    "cycle_confirmed": bool((_active_cycle(state, cycles) or {}).get("cycle_confirmed", False)),
                    "days_in_current_regime": state.regime_days,
                    "target_crypto_exposure": _macro_target(state, scenario, rules),
                    "crypto_exposure_after": _exposure(state, prices_open),
                    "tactical_cash_after": state.tactical_cash,
                    "ordinary_risk_off_lock_days": state.ordinary_risk_off_lock_days,
                    "redeploy_days_remaining": state.redeploy_days_remaining,
                }
            )
        previous_value = end_value
        previous_closes = prices_close

    final_signal = frame.iloc[-1].get("signal_date")
    for cycle in cycles:
        if pd.isna(cycle["cycle_end"]):
            cycle["cycle_end"] = final_signal
            cycle["status"] = "OPEN_AT_END"
    history = pd.DataFrame(history_rows)
    trade_frame = pd.DataFrame(trades)
    signal_frame = pd.DataFrame(signal_rows)
    cycle_frame = pd.DataFrame(cycles)
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=rules)
    return V3BacktestResult(scenario, summary, history, trade_frame, signal_frame, cycle_frame, counters)
