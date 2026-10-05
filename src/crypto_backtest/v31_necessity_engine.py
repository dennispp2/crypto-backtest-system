from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd

from .metrics import calculate_summary
from .v31_engine import (
    ASSETS_V31,
    V31BacktestResult,
    V31Scenario,
    V31State,
    _allocations,
    _buy,
    _buy_to_target,
    _exposure,
    _pending_cash,
    _portfolio_value,
    _reclassify_temp_to_bear,
    _sell_to_target,
    _temp_cash,
    _values,
)


BEAR_STATES = {"EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION"}
NEW_BULL_ACTION = "TACTICAL_BUYBACK_NEW_BULL_REDEPLOY"
TEMP_UNWIND_ACTION = "TACTICAL_BUY_TEMPORARY_HEDGE_UNWIND"


@dataclass
class CounterfactualState(V31State):
    new_bull_redeploy_remaining: int = 0


def signal_type_for(action: str, reason: str) -> str:
    if action == "TACTICAL_BUYBACK_AHR999_TO_35":
        return "AHR_VALUE_BUY"
    if action.startswith("TACTICAL_BUYBACK_RIGHT_TO_"):
        return "RIGHT_SIDE_BUY"
    if action == NEW_BULL_ACTION:
        return "NEW_BULL_REDEPLOY"
    if action.startswith("TACTICAL_SELL_CRASH"):
        return "CRASH_SELL"
    if "BEARISH_REBREAK" in reason:
        return "BEARISH_REBREAK_SELL"
    if action.startswith("TACTICAL_SELL_STAGE"):
        return "STAGE_RISK_SELL"
    if action.startswith("TACTICAL_SELL"):
        return "OTHER_RISK_SELL"
    if action == TEMP_UNWIND_ACTION:
        return "TEMPORARY_HEDGE_UNWIND"
    return "OTHER_TACTICAL"


def frozen_tactical_events(shadow: V31BacktestResult) -> pd.DataFrame:
    tactical = shadow.trades.loc[
        shadow.trades["action"].str.startswith("TACTICAL", na=False)
    ].copy()
    tactical["timestamp"] = pd.to_datetime(tactical["timestamp"], utc=True)
    tactical["signal_date"] = pd.to_datetime(tactical["signal_date"], utc=True)
    events = tactical.groupby(
        ["tactical_event_id", "timestamp", "action", "side", "ledger", "reason", "cycle_id"],
        as_index=False,
        dropna=False,
    ).agg(
        signal_date=("signal_date", "first"),
        target_exposure=("target_crypto_exposure", "first"),
        exposure_before=("before_crypto_exposure", "first"),
        exposure_after=("after_crypto_exposure", "last"),
        btc_notional=("gross_notional_usd", lambda x: float(x[tactical.loc[x.index, "asset"].eq("BTC")].sum())),
        eth_notional=("gross_notional_usd", lambda x: float(x[tactical.loc[x.index, "asset"].eq("ETH")].sum())),
        gross_notional=("gross_notional_usd", "sum"),
        fee=("fee_usd", "sum"),
        slippage=("slippage_usd", "sum"),
        cost=("cost_usd", "sum"),
        temporary_lot_id=("temporary_lot_id", "first"),
        trade_rows=("asset", "size"),
        shadow_state=("fsm_state", "first"),
        shadow_stage=("fsm_stage", "first"),
    ).sort_values(["timestamp", "tactical_event_id"]).reset_index(drop=True)
    events["tactical_event_id"] = events["tactical_event_id"].astype(int)
    events["signal_type"] = [
        signal_type_for(str(action), str(reason))
        for action, reason in zip(events["action"], events["reason"])
    ]
    return events


def _event_map(events: pd.DataFrame) -> dict[pd.Timestamp, list[dict[str, Any]]]:
    return {
        pd.Timestamp(timestamp): frame.sort_values("tactical_event_id").to_dict("records")
        for timestamp, frame in events.groupby("timestamp", sort=True)
    }


def _actual_temp_lot(state: CounterfactualState, shadow_lot_id: Any) -> dict[str, Any] | None:
    try:
        requested = int(float(shadow_lot_id))
    except (TypeError, ValueError):
        requested = -1
    for lot in state.temporary_lots:
        if lot["status"] == "OPEN" and int(lot["lot_id"]) == requested:
            return lot
    return next((lot for lot in state.temporary_lots if lot["status"] == "OPEN"), None)


def _execute_event(
    state: CounterfactualState,
    event: dict[str, Any],
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
) -> tuple[bool, str]:
    action = str(event["action"])
    side = str(event["side"])
    target = float(event["target_exposure"])
    if side == "SELL":
        if action == "TACTICAL_SELL_STAGE2":
            _reclassify_temp_to_bear(state, row, cash_events, "EARLY_BEAR_CONFIRMED")
        sold, outcome, _ = _sell_to_target(
            state,
            row,
            prices,
            target,
            rules,
            scenario,
            trades,
            action=action,
            reason=str(event["reason"]),
            ledger=str(event["ledger"]),
        )
        if str(event["ledger"]) == "temporary_hedge" and state.macro_state in BEAR_STATES:
            _reclassify_temp_to_bear(state, row, cash_events, "CRASH_DURING_CONFIRMED_BEAR")
        if sold <= 0:
            return False, "SHADOW_SELL_PRESENT_NO_TRADE_ALREADY_AT_OR_BELOW_TARGET"
        return True, outcome

    if action == TEMP_UNWIND_ACTION:
        lot = _actual_temp_lot(state, event.get("temporary_lot_id"))
        if lot is None:
            return False, "SHADOW_BUY_PRESENT_NO_OPEN_TEMPORARY_LOT"
        remaining = int(lot.get("counterfactual_unwind_remaining", 5))
        cap = float(lot["cash_remaining"]) / max(1, remaining)
        spent, outcome = _buy_to_target(
            state,
            row,
            prices,
            target,
            rules,
            scenario,
            trades,
            action=action,
            reason=str(event["reason"]),
            ledger="temporary_hedge",
            temp_lot=lot,
            budget_cap=cap,
        )
        lot["counterfactual_unwind_remaining"] = remaining - 1
        return spent > 0, outcome if spent > 0 else "SHADOW_BUY_PRESENT_NO_TRADE_ALREADY_AT_OR_ABOVE_TARGET"

    budget_cap = None
    if action == NEW_BULL_ACTION:
        budget_cap = state.tactical_bear_cash / max(1, state.new_bull_redeploy_remaining)
    spent, outcome = _buy_to_target(
        state,
        row,
        prices,
        target,
        rules,
        scenario,
        trades,
        action=action,
        reason=str(event["reason"]),
        ledger="tactical_bear",
        budget_cap=budget_cap,
    )
    if action == NEW_BULL_ACTION and state.new_bull_redeploy_remaining > 0:
        state.new_bull_redeploy_remaining -= 1
    if spent <= 0:
        return False, "SHADOW_BUY_PRESENT_NO_TRADE_ALREADY_AT_OR_ABOVE_TARGET"
    return True, outcome


def _history_row(
    state: CounterfactualState,
    row: pd.Series,
    prices_close: dict[str, float],
    rules: dict[str, Any],
    *,
    end_value: float,
    unit_nav: float,
    drawdown: float,
    twr_return: float,
    external_flow: float,
    elapsed: int,
    committed: float,
    executed_dca: float,
    dca_alloc: dict[str, float],
    previous_closes: dict[str, float] | None,
    shadow_row: pd.Series,
) -> dict[str, Any]:
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
    return {
        "timestamp": pd.Timestamp(row["open_time"]),
        "portfolio_value": end_value,
        "btc_value": values["BTC"],
        "eth_value": values["ETH"],
        "unit_nav": unit_nav,
        "drawdown": drawdown,
        "twr_return": twr_return,
        "external_flow": external_flow,
        "elapsed_4h_intervals": elapsed,
        "normal_cash": state.normal_cash,
        "pending_dca_cash": pending_cash,
        "tactical_bear_cash": state.tactical_bear_cash,
        "temporary_hedge_cash": temporary_cash,
        "tactical_cash": tactical_cash,
        "normal_cash_ratio": state.normal_cash / end_value,
        "tactical_bear_cash_ratio": state.tactical_bear_cash / end_value,
        "temporary_hedge_cash_ratio": temporary_cash / end_value,
        "tactical_cash_ratio": tactical_cash / end_value,
        "total_cash_ratio": total_cash / end_value,
        "crypto_exposure": crypto_value / end_value,
        "BTC_allocation": allocations["BTC"],
        "ETH_allocation": allocations["ETH"],
        "BTC_close": prices_close["BTC"],
        "ETH_close": prices_close["ETH"],
        "macro_state": shadow_row["macro_state"],
        "sell_stage": shadow_row["sell_stage"],
        "active_target": shadow_row["active_target"],
        "cycle_id": shadow_row["cycle_id"],
        "theoretical_dca": float(rules["external_contribution_per_4h"]),
        "protected_dca": float(rules["external_contribution_per_4h"]),
        "committed_dca": committed,
        "executed_dca": executed_dca,
        "dca_alloc_BTC": dca_alloc["BTC"],
        "dca_alloc_ETH": dca_alloc["ETH"],
        "target_basket_return": basket_return,
        "cash_drag_increment": (total_cash / end_value) * basket_return,
        "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
    }


def run_frozen_shadow_counterfactual(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
    shadow: V31BacktestResult,
    deleted_event_ids: Iterable[int] = (),
) -> tuple[V31BacktestResult, pd.DataFrame]:
    """Replay frozen V3.1 tactical instructions while deleting selected portfolio events."""
    deleted = {int(value) for value in deleted_event_ids}
    state = CounterfactualState(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    counters = {"dca_cash_shortfall_count": 0}

    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
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
            trades=trades,
            signal_date=first.get("signal_date"),
            reason="FRESH_2020_START",
        )

    events = frozen_tactical_events(shadow)
    events_by_time = _event_map(events)
    a_history = model_a.history.set_index("timestamp")
    dca = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")].copy()
    a_dca = {
        (pd.Timestamp(ts), str(asset)): float(-group["cash_change_usd"].sum())
        for (ts, asset), group in dca.groupby(["timestamp", "asset"])
    }
    shadow_history = shadow.history.set_index("timestamp")
    shadow_signals = shadow.signals.set_index("execution_4h_open")
    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    previous_timestamp: pd.Timestamp | None = None
    unit_nav = 1.0
    peak_nav = 1.0

    for _, source_row in frame.iterrows():
        row = source_row.copy()
        row["strategy_name"] = scenario.name
        timestamp = pd.Timestamp(row["open_time"])
        elapsed = 1 if previous_timestamp is None else max(
            1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4)))
        )
        external_flow = float(rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}
        shadow_row = shadow_history.loc[timestamp]
        state.macro_state = str(shadow_row["macro_state"])
        state.stage = int(shadow_row["sell_stage"])
        state.active_target = float(shadow_row["active_target"])
        state.active_cycle_id = int(shadow_row["cycle_id"])

        if timestamp in shadow_signals.index:
            signal_actions = str(shadow_signals.loc[timestamp].get("actions", ""))
            if "NEW_BULL_CONFIRMED" in signal_actions:
                state.new_bull_redeploy_remaining = int(rules["new_bull"]["redeploy_trading_days"])

        for event in events_by_time.get(timestamp, []):
            event_id = int(event["tactical_event_id"])
            before = _exposure(state, prices_open)
            if event_id in deleted:
                if str(event["action"]) == NEW_BULL_ACTION and state.new_bull_redeploy_remaining > 0:
                    state.new_bull_redeploy_remaining -= 1
                audit_rows.append({
                    "timestamp": timestamp,
                    "shadow_event_id": event_id,
                    "shadow_action": event["action"],
                    "shadow_signal_type": event["signal_type"],
                    "shadow_target": event["target_exposure"],
                    "counterfactual_action": "NONE",
                    "counterfactual_decision": "DELETE_SELECTED_EVENT",
                    "decision_reason": "PORTFOLIO_EVENT_DELETED_BTC_AND_ETH_TOGETHER",
                    "actual_exposure_before": before,
                    "actual_exposure_after": before,
                    "actual_filled": False,
                    "directly_deleted": True,
                    "indirect_no_fill": False,
                })
                continue
            prior_actual_id = int(state.tactical_event_id)
            filled, outcome = _execute_event(
                state, event, row, prices_open, rules, scenario, trades, cash_events
            )
            after = _exposure(state, prices_open)
            audit_rows.append({
                "timestamp": timestamp,
                "shadow_event_id": event_id,
                "shadow_action": event["action"],
                "shadow_signal_type": event["signal_type"],
                "shadow_target": event["target_exposure"],
                "counterfactual_action": event["action"] if filled else "NO_TRADE",
                "counterfactual_decision": "EXECUTE" if filled else "SHADOW_PRESENT_NO_FILL",
                "decision_reason": outcome,
                "actual_exposure_before": before,
                "actual_exposure_after": after,
                "actual_filled": bool(filled),
                "actual_tactical_event_id": int(state.tactical_event_id) if filled else "",
                "directly_deleted": False,
                "indirect_no_fill": bool(not filled and int(state.tactical_event_id) == prior_actual_id),
            })

        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("Counterfactual cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(arow[f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
        for asset in ASSETS_V31:
            state.pending[asset] += dca_alloc[asset]
        executed_dca = 0.0
        for asset in ASSETS_V31:
            budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
                executed_dca += _buy(
                    state,
                    asset,
                    budget,
                    prices_open[asset],
                    prices_open,
                    timestamp=timestamp,
                    scenario=scenario,
                    action="NORMAL_DCA",
                    ledger="pending",
                    trades=trades,
                    signal_date=row.get("signal_date"),
                    reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed_dca - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("Counterfactual Fixed DCA execution differs from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        histories.append(_history_row(
            state,
            row,
            prices_close,
            rules,
            end_value=end_value,
            unit_nav=unit_nav,
            drawdown=drawdown,
            twr_return=twr_return,
            external_flow=external_flow,
            elapsed=elapsed,
            committed=committed,
            executed_dca=executed_dca,
            dca_alloc=dca_alloc,
            previous_closes=previous_closes,
            shadow_row=shadow_row,
        ))
        previous_value = end_value
        previous_closes = prices_close
        previous_timestamp = timestamp

    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=rules)
    result = V31BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history,
        trades=trade_frame,
        signals=shadow.signals.copy(),
        transitions=shadow.transitions.copy(),
        cycles=shadow.cycles.copy(),
        temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events),
        counters=counters,
    )
    return result, pd.DataFrame(audit_rows)


__all__ = [
    "CounterfactualState",
    "frozen_tactical_events",
    "run_frozen_shadow_counterfactual",
    "signal_type_for",
]
