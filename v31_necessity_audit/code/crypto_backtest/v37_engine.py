from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

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
    _is_lock_active,
    _pending_cash,
    _portfolio_value,
    _reclassify_temp_to_bear,
    _sell_to_target,
    _temp_cash,
    _values,
)


AHR_ACTION = "TACTICAL_BUYBACK_AHR999_TO_35"
RIGHT_ACTIONS = {"TACTICAL_BUYBACK_RIGHT_TO_50", "TACTICAL_BUYBACK_RIGHT_TO_60"}
NEW_BULL_ACTION = "TACTICAL_BUYBACK_NEW_BULL_REDEPLOY"
TEMP_UNWIND_ACTION = "TACTICAL_BUY_TEMPORARY_HEDGE_UNWIND"
BEAR_STATES = {"EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION"}


@dataclass
class V37OverlayState(V31State):
    ahr_cooldown_until: Any = None
    pending_ahr_buy: dict[str, Any] | None = None
    risk_sell_epoch: int = 0
    last_executed_ahr: dict[str, tuple[pd.Timestamp, int]] = field(default_factory=dict)
    requested_ahr_buys: int = 0
    executed_ahr_buys: int = 0
    delayed_ahr_buys: int = 0
    cancelled_ahr_buys: int = 0
    duplicate_ahr_suppressions: int = 0
    new_bull_redeploy_remaining: int = 0


def _signal_type(action: str) -> str:
    if action == AHR_ACTION:
        return "AHR_VALUE_BUY"
    if action == "TACTICAL_BUYBACK_RIGHT_TO_50":
        return "RIGHT_SIDE_TO_50"
    if action == "TACTICAL_BUYBACK_RIGHT_TO_60":
        return "RIGHT_SIDE_TO_60"
    if action == NEW_BULL_ACTION:
        return "NEW_BULL_REDEPLOY"
    if action == TEMP_UNWIND_ACTION:
        return "TEMPORARY_HEDGE_UNWIND"
    if action.startswith("TACTICAL_SELL"):
        return "RISK_SELL"
    return action


def _priority(event: dict[str, Any]) -> int:
    action = str(event["action"])
    if str(event["side"]) == "SELL":
        return 2
    if action == NEW_BULL_ACTION:
        return 3
    if action == TEMP_UNWIND_ACTION:
        return 3
    if action in RIGHT_ACTIONS:
        return 4
    if action == AHR_ACTION:
        return 5
    return 4


def _shadow_events(shadow: V31BacktestResult) -> dict[pd.Timestamp, list[dict[str, Any]]]:
    tactical = shadow.trades.loc[shadow.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if tactical.empty:
        return {}
    tactical["timestamp"] = pd.to_datetime(tactical["timestamp"], utc=True)
    grouped = tactical.groupby(
        ["tactical_event_id", "timestamp", "action", "side", "ledger", "reason", "cycle_id"],
        as_index=False, dropna=False,
    ).agg(
        target=("target_crypto_exposure", "first"),
        temporary_lot_id=("temporary_lot_id", "first"),
        shadow_gross_notional=("gross_notional_usd", "sum"),
        shadow_cash_change=("cash_change_usd", "sum"),
    )
    result: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for timestamp, frame in grouped.groupby("timestamp", sort=True):
        events = frame.sort_values("tactical_event_id").to_dict("records")
        result[pd.Timestamp(timestamp)] = sorted(events, key=lambda item: (_priority(item), item["tactical_event_id"]))
    return result


def _cooldown_remaining(state: V37OverlayState, timestamp: pd.Timestamp) -> float:
    if state.ahr_cooldown_until is None:
        return 0.0
    return max(0.0, (pd.Timestamp(state.ahr_cooldown_until) - timestamp).total_seconds() / 86400.0)


def _cooldown_active(state: V37OverlayState, timestamp: pd.Timestamp) -> bool:
    return _cooldown_remaining(state, timestamp) > 1e-12


def _audit_row(
    state: V37OverlayState,
    *,
    timestamp: pd.Timestamp,
    shadow_action: str,
    shadow_signal_type: str,
    shadow_target: float,
    actual_action: str,
    overlay_decision: str,
    decision_reason: str,
    before: float,
    after: float,
    shadow_event_id: Any = "",
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "shadow_event_id": shadow_event_id,
        "shadow_action": shadow_action,
        "shadow_signal_type": shadow_signal_type,
        "shadow_target": shadow_target,
        "actual_action": actual_action,
        "overlay_decision": overlay_decision,
        "decision_reason": decision_reason,
        "cooldown_remaining": _cooldown_remaining(state, timestamp),
        "pending_ahr_buy": state.pending_ahr_buy is not None,
        "actual_exposure_before": before,
        "actual_exposure_after": after,
        "risk_sell_epoch": state.risk_sell_epoch,
        "restricted_by_overlay": overlay_decision in {"DELAY", "SUPPRESS", "CANCEL"},
    }


def _cancel_pending(
    state: V37OverlayState,
    timestamp: pd.Timestamp,
    prices: dict[str, float],
    audit: list[dict[str, Any]],
    reason: str,
) -> None:
    if state.pending_ahr_buy is None:
        return
    pending = state.pending_ahr_buy
    before = _exposure(state, prices)
    state.pending_ahr_buy = None
    state.cancelled_ahr_buys += 1
    audit.append(_audit_row(
        state, timestamp=timestamp, shadow_action="PENDING_AHR_BUY",
        shadow_signal_type=str(pending["signal_type"]), shadow_target=float(pending["target"]),
        actual_action="NONE", overlay_decision="CANCEL", decision_reason=reason,
        before=before, after=before, shadow_event_id=pending.get("shadow_event_id", ""),
    ))


def _actual_temp_lot(state: V37OverlayState, shadow_lot_id: Any) -> dict[str, Any] | None:
    try:
        requested = int(float(shadow_lot_id))
    except (TypeError, ValueError):
        requested = -1
    for lot in state.temporary_lots:
        if lot["status"] == "OPEN" and int(lot["lot_id"]) == requested:
            return lot
    return next((lot for lot in state.temporary_lots if lot["status"] == "OPEN" and not lot["bear_confirmed"]), None)


def _execute_non_ahr(
    state: V37OverlayState,
    event: dict[str, Any],
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
) -> tuple[float, str]:
    action = str(event["action"])
    target = float(event["target"])
    before = _exposure(state, prices)
    if str(event["side"]) == "SELL":
        if action == "TACTICAL_SELL_STAGE2":
            _reclassify_temp_to_bear(state, row, cash_events, "EARLY_BEAR_CONFIRMED")
        sold, outcome, _ = _sell_to_target(
            state, row, prices, target, base_rules, scenario, trades,
            action=action, reason=str(event["reason"]), ledger=str(event["ledger"]),
        )
        if str(event["ledger"]) == "temporary_hedge" and state.macro_state in BEAR_STATES:
            _reclassify_temp_to_bear(state, row, cash_events, "CRASH_DURING_CONFIRMED_BEAR")
        return _exposure(state, prices), outcome if sold > 0 else "EXECUTE_NO_FILL_AT_TARGET"
    if action == TEMP_UNWIND_ACTION:
        lot = _actual_temp_lot(state, event.get("temporary_lot_id"))
        if lot is None:
            return before, "EXECUTE_NO_FILL_NO_OPEN_TEMP_LOT"
        remaining = int(lot.get("overlay_unwind_remaining", 5))
        cap = float(lot["cash_remaining"]) / max(1, remaining)
        spent, outcome = _buy_to_target(
            state, row, prices, target, base_rules, scenario, trades,
            action=action, reason=str(event["reason"]), ledger="temporary_hedge",
            temp_lot=lot, budget_cap=cap,
        )
        remaining -= 1
        lot["overlay_unwind_remaining"] = remaining
        if float(lot["cash_remaining"]) <= 1e-8:
            lot["cash_remaining"] = 0.0
            lot["status"] = "UNWOUND"
            lot["closed_date"] = row.get("signal_date")
            lot["closure_reason"] = "FIVE_DAY_UNWIND"
        elif remaining <= 0:
            lot["overlay_unwind_remaining"] = 5
        return _exposure(state, prices), outcome if spent > 0 else "EXECUTE_NO_FILL_AT_TARGET"
    budget_cap = None
    if action == NEW_BULL_ACTION:
        current_remaining = max(1, state.new_bull_redeploy_remaining)
        budget_cap = state.tactical_bear_cash / float(current_remaining)
    spent, outcome = _buy_to_target(
        state, row, prices, target, base_rules, scenario, trades,
        action=action, reason=str(event["reason"]), ledger="tactical_bear",
        budget_cap=budget_cap,
    )
    if action == NEW_BULL_ACTION and state.new_bull_redeploy_remaining > 0:
        state.new_bull_redeploy_remaining -= 1
    return _exposure(state, prices), outcome if spent > 0 else "EXECUTE_NO_FILL_AT_TARGET"


def _execute_ahr(
    state: V37OverlayState,
    *,
    timestamp: pd.Timestamp,
    row: pd.Series,
    prices: dict[str, float],
    target: float,
    signal_type: str,
    reason: str,
    base_rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
) -> tuple[float, str]:
    spent, outcome = _buy_to_target(
        state, row, prices, target, base_rules, scenario, trades,
        action=AHR_ACTION, reason=reason, ledger="tactical_bear",
    )
    if spent > 0:
        state.executed_ahr_buys += 1
        state.last_executed_ahr[signal_type] = (timestamp, state.risk_sell_epoch)
    return _exposure(state, prices), outcome if spent > 0 else "EXECUTE_NO_FILL_AT_TARGET"


def _ahr_condition(row: pd.Series, shadow_state: str, base_rules: dict[str, Any]) -> bool:
    value = row.get("ahr999_fixed_arithmetic")
    return bool(
        shadow_state in {"BEAR", "DEEP_BEAR", "ACCUMULATION"}
        and pd.notna(value)
        and float(value) <= float(base_rules["buyback"]["ahr999_threshold"])
    )


def _history_row(
    state: V37OverlayState,
    row: pd.Series,
    prices_close: dict[str, float],
    *,
    end_value: float,
    unit_nav: float,
    drawdown: float,
    twr_return: float,
    external_flow: float,
    elapsed: int,
    committed: float,
    executed: float,
    dca_alloc: dict[str, float],
    previous_closes: dict[str, float] | None,
    base_rules: dict[str, Any],
    desired_actions: str,
    desired_signal_types: str,
    desired_targets: str,
) -> dict[str, Any]:
    values = _values(state, prices_close)
    crypto_value = sum(values.values())
    allocations = _allocations(state, prices_close)
    pending_cash = _pending_cash(state)
    temporary_cash = _temp_cash(state)
    tactical_cash = state.tactical_bear_cash + temporary_cash
    total_cash = state.normal_cash + pending_cash + tactical_cash
    basket_return = 0.0 if previous_closes is None else sum(
        float(base_rules["target_weights"][asset])
        * (prices_close[asset] / previous_closes[asset] - 1.0)
        for asset in ASSETS_V31
    )
    return {
        "timestamp": pd.Timestamp(row["open_time"]), "portfolio_value": end_value,
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
        "actual_crypto_exposure": crypto_value / end_value,
        "BTC_allocation": allocations["BTC"], "ETH_allocation": allocations["ETH"],
        "BTC_close": prices_close["BTC"], "ETH_close": prices_close["ETH"],
        "BTC_signal_close": row.get("BTC_daily_close"),
        "sma10": row.get("sma10"), "sma20": row.get("sma20"),
        "sma50": row.get("sma50"), "sma200": row.get("sma200"),
        "ahr999": row.get("ahr999_fixed_arithmetic"), "bear_risk": np.nan,
        "ai_enabled": False, "ai_intervention": "NONE",
        "macro_state_previous": row.get("shadow_macro_state_previous", "BULL"),
        "macro_state": row.get("shadow_macro_state", "BULL"),
        "macro_state_shadow": row.get("shadow_macro_state", "BULL"),
        "sell_stage": int(row.get("shadow_sell_stage", 0)),
        "sell_stage_shadow": int(row.get("shadow_sell_stage", 0)),
        "active_target": float(row.get("shadow_active_target", 0.95)),
        "active_target_shadow": float(row.get("shadow_active_target", 0.95)),
        "shadow_target_exposure": float(row.get("shadow_active_target", 0.95)),
        "cycle_id": int(row.get("shadow_cycle_id", 0)),
        "cycle_id_shadow": int(row.get("shadow_cycle_id", 0)),
        "macro_cooldown_days": int(row.get("shadow_macro_cooldown_days", 0)),
        "accumulation_lock": bool(row.get("shadow_accumulation_lock", False)),
        "crash_level1_active": bool(row.get("shadow_crash_state", False)),
        "crash_state_shadow": bool(row.get("shadow_crash_state", False)),
        "new_bull_state_shadow": bool(row.get("shadow_new_bull_state", False)),
        "desired_action_shadow": desired_actions,
        "desired_signal_type_shadow": desired_signal_types,
        "desired_exposure_target_shadow": desired_targets,
        "ahr_rebuy_cooldown_remaining": _cooldown_remaining(state, pd.Timestamp(row["open_time"])),
        "pending_ahr_buy": state.pending_ahr_buy is not None,
        "theoretical_dca": float(base_rules["external_contribution_per_4h"]),
        "protected_dca": float(base_rules["external_contribution_per_4h"]),
        "committed_dca": committed, "executed_dca": executed,
        "dca_alloc_BTC": dca_alloc["BTC"], "dca_alloc_ETH": dca_alloc["ETH"],
        "target_basket_return": basket_return,
        "cash_drag_increment": (total_cash / end_value) * basket_return,
        "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
        "daily_floor_breach_reason": (
            "market_move_after_tactical_sell"
            if crypto_value / end_value < 0.20 - 1e-10 else "none"
        ),
    }


def run_v37_overlay(
    frame: pd.DataFrame,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
    shadow: V31BacktestResult,
) -> tuple[V31BacktestResult, pd.DataFrame]:
    if frame.empty:
        raise ValueError("No formal V3.7 bars")
    state = V37OverlayState(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    daily_signals: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    overlay_audit: list[dict[str, Any]] = []
    counters = {"dca_cash_shortfall_count": 0}
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(base_rules["initial_allocation_usd"][asset]),
            first_prices[asset], first_prices, timestamp=pd.Timestamp(first["open_time"]),
            scenario=scenario, action="INITIAL_ALLOCATION", ledger="normal", trades=trades,
            signal_date=first.get("signal_date"), reason="FRESH_2020_START",
        )

    a_history = model_a.history.set_index("timestamp")
    dca = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")].copy()
    a_dca = {
        (pd.Timestamp(ts), str(asset)): float(-group["cash_change_usd"].sum())
        for (ts, asset), group in dca.groupby(["timestamp", "asset"])
    }
    shadow_history = shadow.history.set_index("timestamp")
    shadow_signals = shadow.signals.set_index("execution_4h_open")
    events_by_time = _shadow_events(shadow)
    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    previous_timestamp: pd.Timestamp | None = None
    unit_nav, peak_nav = 1.0, 1.0

    for _, source_row in frame.iterrows():
        row = source_row.copy()
        row["strategy_name"] = scenario.name
        timestamp = pd.Timestamp(row["open_time"])
        elapsed = 1 if previous_timestamp is None else max(
            1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4)))
        )
        external_flow = float(base_rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}

        # Priority 1: exact Model-A DCA replay.
        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.7 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(arow[f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
        for asset in ASSETS_V31:
            state.pending[asset] += dca_alloc[asset]
        executed_dca = 0.0
        for asset in ASSETS_V31:
            budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
                executed_dca += _buy(
                    state, asset, budget, prices_open[asset], prices_open,
                    timestamp=timestamp, scenario=scenario, action="NORMAL_DCA", ledger="pending",
                    trades=trades, signal_date=row.get("signal_date"), reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed_dca - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("V3.7 executed DCA differs from Model A")

        sh = shadow_history.loc[timestamp]
        row["shadow_macro_state"] = sh["macro_state"]
        row["shadow_macro_state_previous"] = sh["macro_state_previous"]
        row["shadow_sell_stage"] = sh["sell_stage"]
        row["shadow_active_target"] = sh["active_target"]
        row["shadow_cycle_id"] = sh["cycle_id"]
        row["shadow_crash_state"] = sh["crash_level1_active"]
        row["shadow_new_bull_state"] = sh["macro_state"] == "NEW_BULL"
        row["shadow_macro_cooldown_days"] = sh["macro_cooldown_days"]
        row["shadow_accumulation_lock"] = sh["accumulation_lock"]
        signal_actions = (
            str(shadow_signals.loc[timestamp].get("actions", ""))
            if timestamp in shadow_signals.index else ""
        )
        if "NEW_BULL_CONFIRMED" in signal_actions:
            state.new_bull_redeploy_remaining = int(base_rules["new_bull"]["redeploy_trading_days"])
        row["shadow_redeploy_days_remaining"] = state.new_bull_redeploy_remaining
        state.macro_state = str(sh["macro_state"])
        state.stage = int(sh["sell_stage"])
        state.active_target = float(sh["active_target"])
        state.active_cycle_id = int(sh["cycle_id"])

        events = events_by_time.get(timestamp, [])
        desired_actions = "|".join(str(event["action"]) for event in events)
        desired_types = "|".join(_signal_type(str(event["action"])) for event in events)
        desired_targets = "|".join(f"{float(event['target']):.8f}" for event in events)
        had_risk_sell = any(str(event["side"]) == "SELL" for event in events)
        has_new_bull = any(str(event["action"]) == NEW_BULL_ACTION for event in events)
        has_right = any(str(event["action"]) in RIGHT_ACTIONS for event in events)
        current_ahr_request = False

        for event in events:
            action = str(event["action"])
            signal_type = _signal_type(action)
            target = float(event["target"])
            before = _exposure(state, prices_open)
            if str(event["side"]) == "SELL":
                after, outcome = _execute_non_ahr(
                    state, event, row, prices_open, base_rules, scenario, trades, cash_events
                )
                state.risk_sell_epoch += 1
                state.ahr_cooldown_until = timestamp + pd.Timedelta(
                    days=int(rules["execution_overlay"]["ahr_rebuy_cooldown_calendar_days_after_any_tactical_sell"])
                )
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action=action, overlay_decision="EXECUTE",
                    decision_reason=outcome, before=before, after=after,
                    shadow_event_id=event["tactical_event_id"],
                ))
                continue
            if action == NEW_BULL_ACTION:
                _cancel_pending(state, timestamp, prices_open, overlay_audit, "NEW_BULL_CANCELS_PENDING_AHR")
                state.ahr_cooldown_until = None
                after, outcome = _execute_non_ahr(
                    state, event, row, prices_open, base_rules, scenario, trades, cash_events
                )
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action=action, overlay_decision="EXECUTE",
                    decision_reason=outcome, before=before, after=after,
                    shadow_event_id=event["tactical_event_id"],
                ))
                continue
            if action in RIGHT_ACTIONS:
                _cancel_pending(state, timestamp, prices_open, overlay_audit, "RIGHT_SIDE_CANCELS_PENDING_AHR")
                after, outcome = _execute_non_ahr(
                    state, event, row, prices_open, base_rules, scenario, trades, cash_events
                )
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action=action, overlay_decision="EXECUTE",
                    decision_reason=outcome, before=before, after=after,
                    shadow_event_id=event["tactical_event_id"],
                ))
                continue
            if action != AHR_ACTION:
                after, outcome = _execute_non_ahr(
                    state, event, row, prices_open, base_rules, scenario, trades, cash_events
                )
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action=action, overlay_decision="EXECUTE",
                    decision_reason=outcome, before=before, after=after,
                    shadow_event_id=event["tactical_event_id"],
                ))
                continue

            current_ahr_request = True
            state.requested_ahr_buys += 1
            prior = state.last_executed_ahr.get(signal_type)
            duplicate = bool(
                prior is not None and prior[1] == state.risk_sell_epoch
                and (timestamp - prior[0]).total_seconds() / 86400.0
                < float(rules["execution_overlay"]["same_ahr_signal_duplicate_window_calendar_days"])
            )
            if had_risk_sell or _cooldown_active(state, timestamp):
                state.pending_ahr_buy = {
                    "signal_type": signal_type, "target": target,
                    "requested_at": timestamp, "shadow_event_id": event["tactical_event_id"],
                }
                state.delayed_ahr_buys += 1
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action="NONE", overlay_decision="DELAY",
                    decision_reason="RISK_SELL_PRIORITY" if had_risk_sell else "AHR_REBUY_COOLDOWN",
                    before=before, after=before, shadow_event_id=event["tactical_event_id"],
                ))
            elif duplicate:
                state.pending_ahr_buy = None
                state.duplicate_ahr_suppressions += 1
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action="NONE", overlay_decision="SUPPRESS",
                    decision_reason="DUPLICATE_AHR_WITHIN_3_CALENDAR_DAYS",
                    before=before, after=before, shadow_event_id=event["tactical_event_id"],
                ))
            else:
                state.pending_ahr_buy = None
                after, outcome = _execute_ahr(
                    state, timestamp=timestamp, row=row, prices=prices_open, target=target,
                    signal_type=signal_type, reason=str(event["reason"]), base_rules=base_rules,
                    scenario=scenario, trades=trades,
                )
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action=action, shadow_signal_type=signal_type,
                    shadow_target=target, actual_action=action, overlay_decision="EXECUTE",
                    decision_reason=outcome, before=before, after=after,
                    shadow_event_id=event["tactical_event_id"],
                ))

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        if is_new_signal and state.pending_ahr_buy is not None and not current_ahr_request:
            if has_new_bull:
                _cancel_pending(state, timestamp, prices_open, overlay_audit, "NEW_BULL_CANCELS_PENDING_AHR")
            elif has_right:
                _cancel_pending(state, timestamp, prices_open, overlay_audit, "RIGHT_SIDE_CANCELS_PENDING_AHR")
            elif had_risk_sell:
                pending = state.pending_ahr_buy
                exposure = _exposure(state, prices_open)
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action="PENDING_AHR_BUY",
                    shadow_signal_type=str(pending["signal_type"]), shadow_target=float(pending["target"]),
                    actual_action="NONE", overlay_decision="DELAY", decision_reason="NEW_RISK_SELL_RESETS_COOLDOWN",
                    before=exposure, after=exposure, shadow_event_id=pending.get("shadow_event_id", ""),
                ))
            elif not _ahr_condition(row, str(sh["macro_state"]), base_rules):
                _cancel_pending(state, timestamp, prices_open, overlay_audit, "AHR_VALUE_CONDITION_DISAPPEARED")
            elif _cooldown_active(state, timestamp):
                pending = state.pending_ahr_buy
                exposure = _exposure(state, prices_open)
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action="PENDING_AHR_BUY",
                    shadow_signal_type=str(pending["signal_type"]), shadow_target=float(pending["target"]),
                    actual_action="NONE", overlay_decision="DELAY", decision_reason="PENDING_COOLDOWN_ACTIVE",
                    before=exposure, after=exposure, shadow_event_id=pending.get("shadow_event_id", ""),
                ))
            else:
                pending = state.pending_ahr_buy
                before = _exposure(state, prices_open)
                after, outcome = _execute_ahr(
                    state, timestamp=timestamp, row=row, prices=prices_open,
                    target=float(pending["target"]), signal_type=str(pending["signal_type"]),
                    reason="V3_7_PENDING_AHR_EXECUTION", base_rules=base_rules,
                    scenario=scenario, trades=trades,
                )
                state.pending_ahr_buy = None
                overlay_audit.append(_audit_row(
                    state, timestamp=timestamp, shadow_action="PENDING_AHR_BUY",
                    shadow_signal_type=str(pending["signal_type"]), shadow_target=float(pending["target"]),
                    actual_action=AHR_ACTION, overlay_decision="EXECUTE", decision_reason=outcome,
                    before=before, after=after, shadow_event_id=pending.get("shadow_event_id", ""),
                ))
        if is_new_signal:
            state.last_signal_date = row.get("signal_date")
            daily_signals.append({
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"), "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "macro_state_shadow": sh["macro_state"], "sell_stage_shadow": sh["sell_stage"],
                "cycle_id_shadow": sh["cycle_id"], "active_target_shadow": sh["active_target"],
                "crash_state_shadow": bool(sh["crash_level1_active"]),
                "new_bull_state_shadow": sh["macro_state"] == "NEW_BULL",
                "desired_action_shadow": desired_actions,
                "desired_signal_type_shadow": desired_types,
                "desired_exposure_target_shadow": desired_targets,
                "actual_crypto_exposure": _exposure(state, prices_open),
                "ahr_rebuy_cooldown_remaining": _cooldown_remaining(state, timestamp),
                "pending_ahr_buy": state.pending_ahr_buy is not None,
            })

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        drawdown = unit_nav / peak_nav - 1.0
        histories.append(_history_row(
            state, row, prices_close, end_value=end_value, unit_nav=unit_nav,
            drawdown=drawdown, twr_return=twr_return, external_flow=external_flow,
            elapsed=elapsed, committed=committed, executed=executed_dca,
            dca_alloc=dca_alloc, previous_closes=previous_closes, base_rules=base_rules,
            desired_actions=desired_actions, desired_signal_types=desired_types,
            desired_targets=desired_targets,
        ))
        previous_value = end_value
        previous_closes = prices_close
        previous_timestamp = timestamp

    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    counters.update({
        "requested_ahr_buys": state.requested_ahr_buys,
        "executed_ahr_buys": state.executed_ahr_buys,
        "delayed_ahr_buys": state.delayed_ahr_buys,
        "cancelled_ahr_buys": state.cancelled_ahr_buys,
        "duplicate_ahr_suppressions": state.duplicate_ahr_suppressions,
    })
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=base_rules)
    result = V31BacktestResult(
        scenario=scenario, summary=summary, history=history, trades=trade_frame,
        signals=pd.DataFrame(daily_signals), transitions=shadow.transitions.copy(),
        cycles=shadow.cycles.copy(), temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events), counters=counters,
    )
    return result, pd.DataFrame(overlay_audit)


__all__ = [
    "AHR_ACTION", "NEW_BULL_ACTION", "RIGHT_ACTIONS", "V37OverlayState",
    "run_v37_overlay",
]
