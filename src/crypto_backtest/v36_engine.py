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
    _cycle,
    _days_since,
    _exposure,
    _is_lock_active,
    _new_cycle,
    _pending_cash,
    _portfolio_value,
    _process_crash,
    _process_drift,
    _process_temp_unwind,
    _reclassify_temp_to_bear,
    _stage_sell,
    _start_lock,
    _temp_cash,
    _transition,
    _truth,
    _update_temp_lots,
    _values,
)


@dataclass
class V36State(V31State):
    accumulation_episode_id: int = 0
    next_accumulation_episode_id: int = 1
    accumulation_episode_active: bool = False
    value_base_buy_used: bool = False
    value_buy_rearmed: bool = False
    last_accumulation_sell_at: Any = None
    last_accumulation_buy_at: Any = None
    executed_episode_signals: set[str] = field(default_factory=set)


def _ahr_value_condition(row: pd.Series, base_rules: dict[str, Any]) -> bool:
    value = row.get("ahr999_fixed_arithmetic")
    return bool(
        pd.notna(value)
        and float(value) <= float(base_rules["buyback"]["ahr999_threshold"])
    )


def _start_episode(state: V36State) -> None:
    if state.accumulation_episode_active:
        return
    state.accumulation_episode_id = state.next_accumulation_episode_id
    state.next_accumulation_episode_id += 1
    state.accumulation_episode_active = True
    state.value_base_buy_used = False
    state.value_buy_rearmed = False
    state.last_accumulation_sell_at = None
    state.last_accumulation_buy_at = None
    state.executed_episode_signals.clear()


def _end_episode(state: V36State) -> None:
    state.accumulation_episode_active = False
    state.value_base_buy_used = False
    state.value_buy_rearmed = False
    state.last_accumulation_sell_at = None
    state.last_accumulation_buy_at = None
    state.executed_episode_signals.clear()


def _days_gate(timestamp: pd.Timestamp, prior: Any, minimum: float) -> bool:
    days = _days_since(timestamp, prior)
    return bool(pd.notna(days) and days >= minimum - 1e-12)


def _crash_sell_pending(state: V36State, row: pd.Series) -> bool:
    l1 = bool(_truth(row.get("crash_level1_raw")) and state.crash_armed)
    l2 = bool(
        state.crash_level1_days_remaining > 0
        and not state.crash_level2_fired
        and _truth(row.get("crash_level2_market_raw"))
    )
    return l1 or l2


def _update_rearm(
    state: V36State, row: pd.Series, base_rules: dict[str, Any], rules: dict[str, Any], actions: list[str]
) -> None:
    if not (
        state.accumulation_episode_active
        and state.value_base_buy_used
        and state.active_target <= 0.25 + 1e-10
        and _ahr_value_condition(row, base_rules)
    ):
        return
    minimum = float(rules["anti_whipsaw"]["rebuy_cooldown_calendar_days_after_accumulation_sell"])
    if not _days_gate(pd.Timestamp(row["open_time"]), state.last_accumulation_sell_at, minimum):
        return
    if not _truth(row.get("no_new_20d_closing_low_recent3")):
        return
    if not state.value_buy_rearmed:
        state.value_buy_rearmed = True
        state.executed_episode_signals.discard("AHR_BASE_BUY")
        state.executed_episode_signals.discard("AHR_DEEP_VALUE_BUY")
        actions.append("VALUE_BUY_REARMED")


def _attempt_base_buy(
    state: V36State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    signal_type = "AHR_BASE_BUY"
    timestamp = pd.Timestamp(row["open_time"])
    if _crash_sell_pending(state, row):
        counters["anti_whipsaw_buy_suppressed_count"] += 1
        actions.append("AHR_BASE_BUY_BLOCKED_RISK_SELL_PRIORITY")
        return
    if signal_type in state.executed_episode_signals and not state.value_buy_rearmed:
        counters["anti_whipsaw_buy_suppressed_count"] += 1
        actions.append("AHR_BASE_BUY_BLOCKED_DUPLICATE_EPISODE")
        return
    if state.last_accumulation_sell_at is not None:
        minimum = float(rules["anti_whipsaw"]["rebuy_cooldown_calendar_days_after_accumulation_sell"])
        if not _days_gate(timestamp, state.last_accumulation_sell_at, minimum):
            counters["anti_whipsaw_buy_suppressed_count"] += 1
            actions.append("AHR_BASE_BUY_BLOCKED_7D_REBUY_COOLDOWN")
            return
    target = float(base_rules["buyback"]["value_target"])
    state.active_target = target
    spent, outcome = _buy_to_target(
        state, row, prices, target, base_rules, scenario, trades,
        action="TACTICAL_BUYBACK_V36_AHR999_TO_35", reason="AHR_BASE_BUY",
        ledger="tactical_bear",
    )
    if spent > 0:
        state.value_base_buy_used = True
        state.value_buy_rearmed = False
        state.last_accumulation_buy_at = timestamp
        state.executed_episode_signals.add(signal_type)
        _start_lock(state, row, base_rules)
        counters["value_buyback_count"] += 1
    actions.append(f"AHR_BASE_BUY:{outcome}")


def _attempt_right_buy(
    state: V36State,
    row: pd.Series,
    prices: dict[str, float],
    target: float,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    signal_type = "RIGHT_SIDE_TO50" if target == 0.50 else "RIGHT_SIDE_TO60"
    timestamp = pd.Timestamp(row["open_time"])
    minimum = float(
        rules["anti_whipsaw"][
            "base_to_right_50_cooldown_calendar_days"
            if target == 0.50 else "right_50_to_60_cooldown_calendar_days"
        ]
    )
    reason = ""
    if _crash_sell_pending(state, row):
        reason = "RISK_SELL_PRIORITY"
    elif signal_type in state.executed_episode_signals:
        reason = "DUPLICATE_EPISODE"
    elif not _days_gate(timestamp, state.last_accumulation_buy_at, minimum):
        reason = f"{int(minimum)}D_BUY_COOLDOWN"
    elif target == 0.50 and not _truth(row.get("no_new_20d_closing_low_recent3")):
        reason = "RECENT_NEW_20D_CLOSING_LOW"
    if reason:
        counters["anti_whipsaw_buy_suppressed_count"] += 1
        actions.append(f"{signal_type}_BLOCKED_{reason}")
        return
    state.active_target = target
    spent, outcome = _buy_to_target(
        state, row, prices, target, base_rules, scenario, trades,
        action=f"TACTICAL_BUYBACK_V36_RIGHT_TO_{int(target * 100)}",
        reason=signal_type, ledger="tactical_bear",
    )
    if spent > 0:
        state.last_accumulation_buy_at = timestamp
        state.executed_episode_signals.add(signal_type)
        if target == 0.50:
            state.right_50_done = True
        else:
            state.right_60_done = True
        _start_lock(state, row, base_rules)
        counters["right_buyback_count"] += 1
    actions.append(f"{signal_type}:{outcome}")


def _run_v36_macro_fsm(
    state: V36State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> tuple[str, str]:
    start_state = state.macro_state
    timestamp = pd.Timestamp(row["open_time"])
    active_cycle = _cycle(state, cycles)
    if active_cycle is not None:
        active_cycle["cycle_peak_price"] = max(
            float(active_cycle["cycle_peak_price"]), float(row["BTC_daily_close"])
        )
    if start_state in {"BEAR", "DEEP_BEAR", "ACCUMULATION"}:
        close = float(row["BTC_daily_close"])
        if close < state.bear_low_price:
            state.bear_low_price = close
            state.bear_low_date = row.get("signal_date")
    _update_rearm(state, row, base_rules, rules, actions)

    if start_state == "BULL":
        if state.macro_cooldown_days <= 0 and _truth(row.get("distribution_confirmed")):
            cycles.append(_new_cycle(state, row, prices))
            _transition(state, "DISTRIBUTION", "DISTRIBUTION_CONFIRMED", row, base_rules, transitions)
            _stage_sell(
                state, 1, row, prices, base_rules, scenario, trades, cycles, actions,
                reason="DISTRIBUTION_STAGE1", temporary=True,
            )
            counters["stage1_count"] += 1

    elif start_state == "DISTRIBUTION":
        active_cycle = _cycle(state, cycles)
        abort_allowed = active_cycle is not None and not bool(active_cycle["confirmed"])
        if _truth(row.get("distribution_abort_confirmed")) and abort_allowed:
            _transition(state, "BULL", "ABORTED_DISTRIBUTION", row, base_rules, transitions)
            if active_cycle is not None:
                active_cycle["end"] = row.get("signal_date")
                active_cycle["status"] = "ABORTED_DISTRIBUTION"
            state.active_cycle_id = 0
            state.stage = 0
            state.active_target = 0.95
            counters["aborted_distribution_count"] += 1
            actions.append("ABORTED_DISTRIBUTION")
        elif _truth(row.get("early_bear_confirmed")):
            _transition(state, "EARLY_BEAR", "EARLY_BEAR_CONFIRMED", row, base_rules, transitions)
            if active_cycle is not None and not bool(active_cycle["confirmed"]):
                active_cycle["confirmed"] = True
                active_cycle["confirmed_date"] = row.get("signal_date")
            _reclassify_temp_to_bear(state, row, cash_events, "EARLY_BEAR_CONFIRMED")
            _stage_sell(
                state, 2, row, prices, base_rules, scenario, trades, cycles, actions,
                reason="EARLY_BEAR_STAGE2", temporary=False,
            )
            counters["stage2_count"] += 1

    elif start_state == "EARLY_BEAR":
        if _truth(row.get("stage3_confirmed")):
            _transition(state, "BEAR", "BEAR_STAGE3_CONFIRMED", row, base_rules, transitions)
            _stage_sell(
                state, 3, row, prices, base_rules, scenario, trades, cycles, actions,
                reason="BEAR_STAGE3", temporary=False,
            )
            counters["stage3_count"] += 1
        elif _truth(row.get("early_bear_repair_confirmed")):
            _transition(state, "DISTRIBUTION", "EARLY_BEAR_REPAIR", row, base_rules, transitions)
            state.stage = 1
            state.active_target = 0.85
            actions.append("EARLY_BEAR_TO_DISTRIBUTION")

    elif start_state == "BEAR":
        active_cycle = _cycle(state, cycles)
        cycle_dd = (
            float(row["BTC_daily_close"]) / float(active_cycle["cycle_peak_price"]) - 1.0
            if active_cycle is not None else np.nan
        )
        market_acceleration = bool(
            _truth(row.get("bear_acceleration_market_raw"))
            and cycle_dd <= float(base_rules["macro"]["drawdown_cycle_acceleration"])
        )
        structural = _truth(row.get("deep_bear_structural_confirmed"))
        if structural or market_acceleration:
            reason = "FSM_BEAR_ACCELERATION" if market_acceleration else "FSM_STRUCTURAL_STAGE4"
            _transition(state, "DEEP_BEAR", reason, row, base_rules, transitions)
            _stage_sell(
                state, 4, row, prices, base_rules, scenario, trades, cycles, actions,
                reason=reason, temporary=False,
            )
            counters["stage4_count"] += 1
        elif _ahr_value_condition(row, base_rules):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, base_rules, transitions)
            _start_episode(state)
            _attempt_base_buy(state, row, prices, base_rules, rules, scenario, trades, counters, actions)

    elif start_state == "DEEP_BEAR":
        if _ahr_value_condition(row, base_rules):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, base_rules, transitions)
            _start_episode(state)
            _attempt_base_buy(state, row, prices, base_rules, rules, scenario, trades, counters, actions)
        elif _truth(row.get("deep_bear_exit_confirmed")):
            _transition(state, "BEAR", "DEEP_BEAR_STRUCTURAL_EXIT", row, base_rules, transitions)
            state.stage = 3
            state.active_target = 0.55
            actions.append("DEEP_BEAR_TO_BEAR_NO_AUTO_BUY")

    elif start_state == "ACCUMULATION":
        lock_active = _is_lock_active(state, timestamp)
        lower_low = _truth(row.get("confirmed_lower_low"))
        if lock_active and lower_low:
            state.accumulation_lock_until = timestamp
            lock_active = False
            actions.append("ACCUMULATION_LOCK_RELEASE_LOWER_LOW")
        if not lock_active and (lower_low or _truth(row.get("deep_bear_structural_confirmed"))):
            to_state = "DEEP_BEAR" if _truth(row.get("deep_bear_structural_confirmed")) else "BEAR"
            _transition(state, to_state, "ACCUMULATION_BEARISH_REBREAK", row, base_rules, transitions)
            stage = 4 if to_state == "DEEP_BEAR" else 3
            _stage_sell(
                state, stage, row, prices, base_rules, scenario, trades, cycles, actions,
                reason="ACCUMULATION_BEARISH_REBREAK", temporary=False,
            )
        else:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            gate7 = bool(
                pd.notna(days_since_low)
                and days_since_low >= float(base_rules["new_bull"]["minimum_calendar_days_since_bear_low"])
            )
            if _truth(row.get("new_bull_first_six")) and gate7:
                _transition(state, "NEW_BULL", "NEW_BULL_ALL_SEVEN_GATES", row, base_rules, transitions)
                state.stage = 0
                state.active_target = 0.95
                state.redeploy_days_remaining = int(base_rules["new_bull"]["redeploy_trading_days"])
                active_cycle = _cycle(state, cycles)
                if active_cycle is not None:
                    active_cycle["new_bull_date"] = row.get("signal_date")
                counters["new_bull_count"] += 1
                actions.append("NEW_BULL_CONFIRMED")
                _end_episode(state)
            elif state.active_target <= 0.25 + 1e-10 and _ahr_value_condition(row, base_rules):
                _attempt_base_buy(state, row, prices, base_rules, rules, scenario, trades, counters, actions)
            elif (
                abs(state.active_target - 0.35) <= 1e-10
                and _truth(row.get("right_50_confirmed"))
                and not state.right_50_done
            ):
                _attempt_right_buy(
                    state, row, prices, 0.50, base_rules, rules, scenario, trades, counters, actions
                )
            elif (
                abs(state.active_target - 0.50) <= 1e-10
                and _truth(row.get("right_60_confirmed"))
                and not state.right_60_done
            ):
                _attempt_right_buy(
                    state, row, prices, 0.60, base_rules, rules, scenario, trades, counters, actions
                )

    if state.macro_state == "NEW_BULL":
        if state.redeploy_days_remaining > 0:
            cap = state.tactical_bear_cash / float(state.redeploy_days_remaining)
            spent, outcome = _buy_to_target(
                state, row, prices, 0.95, base_rules, scenario, trades,
                action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
                reason="TEN_DAY_NEW_BULL_REDEPLOY", ledger="tactical_bear", budget_cap=cap,
            )
            state.redeploy_days_remaining -= 1
            if spent > 0:
                counters["new_bull_redeploy_count"] += 1
            actions.append(f"NEW_BULL_REDEPLOY:{outcome}")
        if state.redeploy_days_remaining == 0:
            active_cycle = _cycle(state, cycles)
            _transition(state, "BULL", "NEW_BULL_REDEPLOY_COMPLETE", row, base_rules, transitions)
            if active_cycle is not None:
                active_cycle["end"] = row.get("signal_date")
                active_cycle["status"] = "COMPLETED_NEW_BULL"
            state.active_cycle_id = 0
            state.stage = 0
            state.active_target = 0.95
            state.macro_cooldown_days = int(base_rules["new_bull"]["macro_cooldown_trading_days"])
            _end_episode(state)
            actions.append("NEW_BULL_COMPLETE_COOLDOWN_30")
    return "NONE", ""


def run_v36_backtest(
    frame: pd.DataFrame,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.6 bars")
    state = V36State(normal_cash=float(scenario.initial_capital))
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
        "anti_whipsaw_buy_suppressed_count",
    ]}

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

        # Frozen Model A DCA is committed and executed before any Model H tactical action.
        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.6 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(arow[f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
        for asset in ASSETS_V31:
            state.pending[asset] += dca_alloc[asset]
        executed = 0.0
        for asset in ASSETS_V31:
            budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
                executed += _buy(
                    state, asset, budget, prices_open[asset], prices_open,
                    timestamp=timestamp, scenario=scenario, action="NORMAL_DCA", ledger="pending",
                    trades=trades, signal_date=row.get("signal_date"), reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("V3.6 executed DCA differs from Model A")

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_state, before_stage, before_target = state.macro_state, state.stage, state.active_target
        before_exposure = _exposure(state, prices_open)
        before_trade_count = len(trades)
        prior_sell_at = state.last_accumulation_sell_at
        actions: list[str] = []
        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, base_rules)
            _run_v36_macro_fsm(
                state, row, prices_open, base_rules, rules, scenario, trades,
                transitions, cycles, cash_events, counters, actions,
            )
            _process_crash(
                state, row, prices_open, base_rules, scenario, trades,
                cash_events, counters, actions,
            )
            _process_temp_unwind(state, row, prices_open, base_rules, scenario, trades, actions)
            _process_drift(state, row, prices_open, base_rules, scenario, trades, counters, actions)
            new_tactical = trades[before_trade_count:]
            if state.accumulation_episode_active and any(
                trade.get("action", "").startswith("TACTICAL") and trade.get("side") == "SELL"
                for trade in new_tactical
            ):
                state.last_accumulation_sell_at = timestamp
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

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
            float(base_rules["target_weights"][asset])
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
            "ahr999": row.get("ahr999_fixed_arithmetic"), "bear_risk": np.nan,
            "ai_enabled": False, "ai_intervention": "NONE",
            "macro_state_previous": before_state, "macro_state": state.macro_state,
            "sell_stage": state.stage, "active_target": state.active_target,
            "cycle_id": state.active_cycle_id, "macro_cooldown_days": state.macro_cooldown_days,
            "accumulation_lock": _is_lock_active(state, timestamp),
            "crash_level1_active": state.crash_level1_days_remaining > 0,
            "theoretical_dca": float(base_rules["external_contribution_per_4h"]),
            "protected_dca": float(base_rules["external_contribution_per_4h"]),
            "committed_dca": committed, "executed_dca": executed,
            "dca_alloc_BTC": dca_alloc["BTC"], "dca_alloc_ETH": dca_alloc["ETH"],
            "target_basket_return": basket_return,
            "cash_drag_increment": (total_cash / end_value) * basket_return,
            "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
            "daily_floor_breach_reason": (
                "market_move_after_tactical_sell"
                if crypto_value / end_value < scenario.hard_floor - 1e-10 else "none"
            ),
            "accumulation_episode_id": state.accumulation_episode_id,
            "accumulation_episode_active": state.accumulation_episode_active,
            "value_base_buy_used": state.value_base_buy_used,
            "value_buy_rearmed": state.value_buy_rearmed,
            "last_accumulation_sell_at": state.last_accumulation_sell_at,
            "last_accumulation_buy_at": state.last_accumulation_buy_at,
            "new_20d_closing_low": bool(row.get("new_20d_closing_low", False)),
            "no_new_20d_closing_low_recent3": bool(row.get("no_new_20d_closing_low_recent3", False)),
        })

        if is_new_signal:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            signals.append({
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"), "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "sma10": row.get("sma10"), "sma20": row.get("sma20"),
                "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "ahr999": row.get("ahr999_fixed_arithmetic"), "bear_risk": np.nan,
                "ai_enabled": False, "ai_intervention": "NONE", "ai_intervention_reason": "",
                "state_before": before_state, "state_after": state.macro_state,
                "stage_before": before_stage, "stage_after": state.stage,
                "active_target_before": before_target, "active_target_after": state.active_target,
                "crypto_exposure_before": before_exposure,
                "crypto_exposure_after": _exposure(state, prices_open),
                "tactical_bear_cash_after": state.tactical_bear_cash,
                "temporary_hedge_cash_after": _temp_cash(state), "actions": "|".join(actions),
                "distribution_confirmed": row.get("distribution_confirmed"),
                "early_bear_confirmed": row.get("early_bear_confirmed"),
                "stage3_confirmed": row.get("stage3_confirmed"),
                "deep_bear_structural_confirmed": row.get("deep_bear_structural_confirmed"),
                "crash_level1_raw": row.get("crash_level1_raw"),
                "crash_level2_market_raw": row.get("crash_level2_market_raw"),
                "right_50_confirmed": row.get("right_50_confirmed"),
                "right_60_confirmed": row.get("right_60_confirmed"),
                "new_20d_closing_low": bool(row.get("new_20d_closing_low", False)),
                "no_new_20d_closing_low_recent3": bool(row.get("no_new_20d_closing_low_recent3", False)),
                "accumulation_episode_id": state.accumulation_episode_id,
                "accumulation_episode_active": state.accumulation_episode_active,
                "value_base_buy_used": state.value_base_buy_used,
                "value_buy_rearmed": state.value_buy_rearmed,
                "rearm_status": "REARMED" if state.value_buy_rearmed else "NOT_REARMED",
                "rebuy_cooldown": (
                    False if state.last_accumulation_sell_at is None else
                    not _days_gate(timestamp, state.last_accumulation_sell_at,
                                   float(rules["anti_whipsaw"]["rebuy_cooldown_calendar_days_after_accumulation_sell"]))
                ),
                "last_accumulation_sell_at_before_signal": prior_sell_at,
                **{f"new_bull_gate_{i}": row.get(f"new_bull_gate_{i}") for i in range(1, 7)},
                "new_bull_gate_7": bool(
                    pd.notna(days_since_low)
                    and days_since_low >= float(base_rules["new_bull"]["minimum_calendar_days_since_bear_low"])
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
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=base_rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history, trades=trade_frame,
        signals=pd.DataFrame(signals), transitions=pd.DataFrame(transitions), cycles=pd.DataFrame(cycles),
        temporary_lots=pd.DataFrame(state.temporary_lots), cash_events=pd.DataFrame(cash_events), counters=counters,
    )


__all__ = ["V36State", "run_v36_backtest"]
