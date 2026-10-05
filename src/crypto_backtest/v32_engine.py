from __future__ import annotations

from dataclasses import dataclass
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
    _commit_model_a_dca,
    _cycle,
    _days_since,
    _exposure,
    _is_lock_active,
    _new_cycle,
    _pending_cash,
    _portfolio_value,
    _process_crash,
    _process_temp_unwind,
    _reclassify_temp_to_bear,
    _sell_to_target,
    _stage_sell,
    _start_lock,
    _temp_cash,
    _transition,
    _truth,
    _update_temp_lots,
    _values,
)


@dataclass
class V32State(V31State):
    recovery_mode: bool = False
    recovery_entry_signal_index: int = 0
    recovery_confirmation_days: int = 0
    deep_bear_entry_signal_index: int = 0
    new_bull_confirmation_signal_index: int = 0


def _new_cycle_v32(state: V32State, row: pd.Series, prices: dict[str, float]) -> dict[str, Any]:
    item = _new_cycle(state, row, prices)
    for event in ("accumulation", "new_bull", "bull"):
        item[f"{event}_date"] = pd.NaT
        item[f"{event}_btc_price"] = np.nan
        item[f"{event}_exposure"] = np.nan
    return item


def _record_cycle_event(
    state: V32State, cycles: list[dict[str, Any]], event: str,
    row: pd.Series, prices: dict[str, float],
) -> None:
    item = _cycle(state, cycles)
    if item is None or pd.notna(item.get(f"{event}_date")):
        return
    item[f"{event}_date"] = row.get("signal_date")
    item[f"{event}_btc_price"] = float(row["BTC_daily_close"])
    item[f"{event}_exposure"] = _exposure(state, prices)


def _enter_accumulation(
    state: V32State, row: pd.Series, prices: dict[str, float],
    base_rules: dict[str, Any], v32_rules: dict[str, Any], scenario: V31Scenario,
    trades: list[dict[str, Any]], transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]], actions: list[str], counters: dict[str, Any],
    *, recovery: bool,
) -> None:
    reason = "BULL_RECOVERY_GATE" if recovery else "AHR999_VALUE_ACCUMULATION"
    _transition(state, "ACCUMULATION", reason, row, base_rules, transitions)
    target = (
        float(v32_rules["bull_recovery"]["target_exposure"])
        if recovery else float(v32_rules["buyback"]["value_only_max_exposure"])
    )
    state.active_target = target
    state.recovery_mode = recovery
    state.recovery_entry_signal_index = state.signal_index if recovery else 0
    state.recovery_confirmation_days = 0
    _record_cycle_event(state, cycles, "accumulation", row, prices)
    spent, outcome = _buy_to_target(
        state, row, prices, target, base_rules, scenario, trades,
        action=("TACTICAL_BUYBACK_BULL_RECOVERY_TO_60" if recovery else "TACTICAL_BUYBACK_AHR999_TO_35"),
        reason=reason, ledger="tactical_bear",
    )
    if spent > 0 and not recovery:
        _start_lock(state, row, base_rules)
        counters["value_buyback_count"] += 1
    if recovery:
        counters["bull_recovery_count"] += 1
    actions.append(f"{reason}:{outcome}")


def _run_v32_macro_fsm(
    state: V32State, row: pd.Series, prices: dict[str, float],
    base_rules: dict[str, Any], v32_rules: dict[str, Any], scenario: V31Scenario,
    trades: list[dict[str, Any]], transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]], cash_events: list[dict[str, Any]],
    counters: dict[str, Any], actions: list[str],
) -> None:
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

    if start_state == "BULL" and state.macro_cooldown_days <= 0 and _truth(row.get("distribution_confirmed")):
        cycles.append(_new_cycle_v32(state, row, prices))
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
        if _truth(row.get("bull_recovery_gate")):
            _enter_accumulation(
                state, row, prices, base_rules, v32_rules, scenario, trades,
                transitions, cycles, actions, counters, recovery=True,
            )
        else:
            active_cycle = _cycle(state, cycles)
            cycle_dd = (
                float(row["BTC_daily_close"]) / float(active_cycle["cycle_peak_price"]) - 1.0
                if active_cycle is not None else np.nan
            )
            accel = v32_rules["stage4_acceleration"]
            market_acceleration = bool(
                float(row["BTC_daily_close"]) < float(row["sma200"])
                and float(row["below_sma200_count_7"]) >= int(accel["below_sma200_required"])
                and cycle_dd <= float(accel["cycle_peak_to_close_drawdown_max"])
            )
            crash_level2_active = bool(
                state.crash_level2_fired
                or (
                    state.crash_level1_days_remaining > 0
                    and _truth(row.get("crash_level2_market_raw"))
                )
            )
            crash_acceleration = bool(
                crash_level2_active and float(row["BTC_daily_close"]) < float(row["sma200"])
            )
            structural = _truth(row.get("deep_bear_structural_confirmed"))
            if structural or market_acceleration or crash_acceleration:
                reason = (
                    "V32_CRASH_L2_STAGE4" if crash_acceleration else
                    "V32_5OF7_SMA200_DD25_STAGE4" if market_acceleration else
                    "FSM_STRUCTURAL_STAGE4"
                )
                _transition(state, "DEEP_BEAR", reason, row, base_rules, transitions)
                state.deep_bear_entry_signal_index = state.signal_index
                _stage_sell(
                    state, 4, row, prices, base_rules, scenario, trades, cycles, actions,
                    reason=reason, temporary=False,
                )
                counters["stage4_count"] += 1
            elif (
                pd.notna(row.get("ahr999_fixed_arithmetic"))
                and float(row["ahr999_fixed_arithmetic"]) <= float(v32_rules["buyback"]["ahr999_value_threshold"])
            ):
                _enter_accumulation(
                    state, row, prices, base_rules, v32_rules, scenario, trades,
                    transitions, cycles, actions, counters, recovery=False,
                )

    elif start_state == "DEEP_BEAR":
        if _truth(row.get("bull_recovery_gate")):
            _enter_accumulation(
                state, row, prices, base_rules, v32_rules, scenario, trades,
                transitions, cycles, actions, counters, recovery=True,
            )
        elif (
            pd.notna(row.get("ahr999_fixed_arithmetic"))
            and float(row["ahr999_fixed_arithmetic"]) <= float(v32_rules["buyback"]["ahr999_value_threshold"])
        ):
            _enter_accumulation(
                state, row, prices, base_rules, v32_rules, scenario, trades,
                transitions, cycles, actions, counters, recovery=False,
            )
        else:
            min_days = int(v32_rules["deep_bear_hysteresis"]["minimum_completed_days"])
            stayed = state.signal_index - state.deep_bear_entry_signal_index
            if stayed >= min_days and _truth(row.get("deep_bear_exit_v32_confirmed")):
                _transition(state, "BEAR", "V32_DEEP_BEAR_HYSTERESIS_EXIT", row, base_rules, transitions)
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
            if stage == 4:
                state.deep_bear_entry_signal_index = state.signal_index
            state.recovery_mode = False
            state.recovery_confirmation_days = 0
            _stage_sell(
                state, stage, row, prices, base_rules, scenario, trades, cycles, actions,
                reason="ACCUMULATION_BEARISH_REBREAK", temporary=False,
            )
        elif state.recovery_mode:
            if state.signal_index > state.recovery_entry_signal_index:
                if _truth(row.get("recovery_new_bull_daily_condition")):
                    state.recovery_confirmation_days += 1
                else:
                    state.recovery_confirmation_days = 0
            if state.recovery_confirmation_days >= int(v32_rules["bull_recovery"]["new_bull_confirmation_completed_days"]):
                _transition(state, "NEW_BULL", "V32_RECOVERY_NEW_BULL_CONFIRMED", row, base_rules, transitions)
                state.stage = 0
                state.active_target = float(v32_rules["bull_recovery"]["new_bull_target_exposure"])
                state.redeploy_days_remaining = int(v32_rules["bull_recovery"]["new_bull_redeploy_completed_days"])
                state.macro_cooldown_days = int(v32_rules["bull_recovery"]["new_bull_cooldown_completed_days_from_confirmation"])
                state.new_bull_confirmation_signal_index = state.signal_index
                _record_cycle_event(state, cycles, "new_bull", row, prices)
                active_cycle = _cycle(state, cycles)
                if active_cycle is not None:
                    active_cycle["new_bull_date"] = row.get("signal_date")
                counters["new_bull_count"] += 1
                actions.append("V32_NEW_BULL_CONFIRMED")
        else:
            desired: float | None = None
            if state.active_target <= 0.35 + 1e-10 and _truth(row.get("right_50_confirmed")) and not state.right_50_done:
                desired = 0.50
            elif 0.50 - 1e-10 <= state.active_target < 0.60 - 1e-10 and _truth(row.get("right_60_v32_confirmed")) and not state.right_60_done:
                desired = 0.60
            if desired is not None:
                state.active_target = desired
                spent, outcome = _buy_to_target(
                    state, row, prices, desired, base_rules, scenario, trades,
                    action=f"TACTICAL_BUYBACK_RIGHT_TO_{int(desired * 100)}",
                    reason=f"V32_RIGHT_SIDE_TO_{int(desired * 100)}", ledger="tactical_bear",
                )
                if spent > 0:
                    state.right_50_done = state.right_50_done or desired == 0.50
                    state.right_60_done = state.right_60_done or desired == 0.60
                    _start_lock(state, row, base_rules)
                    counters["right_buyback_count"] += 1
                actions.append(f"RIGHT_TO_{int(desired * 100)}:{outcome}")

    if state.macro_state == "NEW_BULL":
        if state.redeploy_days_remaining > 0:
            cap = state.tactical_bear_cash / float(state.redeploy_days_remaining)
            spent, outcome = _buy_to_target(
                state, row, prices, float(v32_rules["bull_recovery"]["new_bull_target_exposure"]),
                base_rules, scenario, trades, action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
                reason="V32_FIVE_DAY_NEW_BULL_REDEPLOY", ledger="tactical_bear", budget_cap=cap,
            )
            state.redeploy_days_remaining -= 1
            if spent > 0:
                counters["new_bull_redeploy_count"] += 1
            actions.append(f"NEW_BULL_REDEPLOY:{outcome}")
        if state.redeploy_days_remaining == 0:
            active_cycle = _cycle(state, cycles)
            _transition(state, "BULL", "V32_NEW_BULL_REDEPLOY_COMPLETE", row, base_rules, transitions)
            _record_cycle_event(state, cycles, "bull", row, prices)
            if active_cycle is not None:
                active_cycle["end"] = row.get("signal_date")
                active_cycle["status"] = "COMPLETED_NEW_BULL"
            state.active_cycle_id = 0
            state.stage = 0
            state.active_target = 0.95
            state.recovery_mode = False
            actions.append("V32_NEW_BULL_COMPLETE")


def _process_v32_drift(
    state: V32State, row: pd.Series, prices: dict[str, float],
    base_rules: dict[str, Any], v32_rules: dict[str, Any], scenario: V31Scenario,
    trades: list[dict[str, Any]], counters: dict[str, Any], actions: list[str],
) -> None:
    guard = v32_rules["drift_sell"]
    if state.macro_state not in set(guard["eligible_states"]):
        return
    timestamp = pd.Timestamp(row["open_time"])
    if _is_lock_active(state, timestamp):
        return
    if _exposure(state, prices) <= state.active_target + float(guard["exposure_above_target_percentage_points"]):
        return
    wait = _days_since(timestamp, state.last_drift_sell_at)
    if pd.notna(wait) and wait < float(guard["cooldown_calendar_days"]):
        return
    sold, outcome, _ = _sell_to_target(
        state, row, prices, state.active_target, base_rules, scenario, trades,
        action="TACTICAL_SELL_DRIFT", reason="DRIFT_ABOVE_ACTIVE_TARGET_PLUS_10PP",
        ledger="tactical_bear",
    )
    if sold > 0:
        state.last_drift_sell_at = timestamp
        counters["drift_sell_count"] += 1
    actions.append(f"DRIFT_SELL:{outcome}")


def _history_row(
    state: V31State, row: pd.Series, scenario: V31Scenario,
    prices_close: dict[str, float], end_value: float, unit_nav: float, drawdown: float,
    twr_return: float, external_flow: float, elapsed: int, committed: float, executed: float,
    dca_alloc: dict[str, float], previous_closes: dict[str, float] | None,
    rules: dict[str, Any], before_state: str, ai_intervention: str = "NONE",
) -> dict[str, Any]:
    values = _values(state, prices_close)
    crypto_value = sum(values.values())
    allocations = _allocations(state, prices_close)
    pending_cash = _pending_cash(state)
    temporary_cash = _temp_cash(state)
    tactical_cash = state.tactical_bear_cash + temporary_cash
    total_cash = state.normal_cash + pending_cash + tactical_cash
    basket_return = 0.0 if previous_closes is None else sum(
        float(rules["target_weights"][asset]) * (prices_close[asset] / previous_closes[asset] - 1.0)
        for asset in ASSETS_V31
    )
    return {
        "timestamp": pd.Timestamp(row["open_time"]), "portfolio_value": end_value,
        "btc_value": values["BTC"], "eth_value": values["ETH"], "unit_nav": unit_nav,
        "drawdown": drawdown, "twr_return": twr_return, "external_flow": external_flow,
        "elapsed_4h_intervals": elapsed, "normal_cash": state.normal_cash,
        "pending_dca_cash": pending_cash, "tactical_bear_cash": state.tactical_bear_cash,
        "temporary_hedge_cash": temporary_cash, "tactical_cash": tactical_cash,
        "normal_cash_ratio": state.normal_cash / end_value,
        "tactical_bear_cash_ratio": state.tactical_bear_cash / end_value,
        "temporary_hedge_cash_ratio": temporary_cash / end_value,
        "tactical_cash_ratio": tactical_cash / end_value, "total_cash_ratio": total_cash / end_value,
        "crypto_exposure": crypto_value / end_value, "BTC_allocation": allocations["BTC"],
        "ETH_allocation": allocations["ETH"], "BTC_close": prices_close["BTC"],
        "ETH_close": prices_close["ETH"], "BTC_signal_close": row.get("BTC_daily_close"),
        "sma10": row.get("sma10"), "sma20": row.get("sma20"), "sma50": row.get("sma50"),
        "sma200": row.get("sma200"), "ahr999": row.get("ahr999_fixed_arithmetic"),
        "bear_risk": np.nan, "ai_enabled": False, "ai_intervention": ai_intervention,
        "macro_state_previous": before_state if scenario.use_fsm else "N/A",
        "macro_state": state.macro_state if scenario.use_fsm else "N/A",
        "sell_stage": state.stage if scenario.use_fsm else 0,
        "active_target": state.active_target if scenario.use_fsm else np.nan,
        "cycle_id": state.active_cycle_id if scenario.use_fsm else 0,
        "macro_cooldown_days": state.macro_cooldown_days,
        "accumulation_lock": _is_lock_active(state, pd.Timestamp(row["open_time"])),
        "crash_level1_active": state.crash_level1_days_remaining > 0,
        "recovery_mode": bool(getattr(state, "recovery_mode", False)),
        "bull_recovery_gate": bool(row.get("bull_recovery_gate", False)) if pd.notna(row.get("bull_recovery_gate")) else False,
        "theoretical_dca": 0.0 if scenario.model == "H0" else float(rules["external_contribution_per_4h"]),
        "protected_dca": 0.0 if scenario.model == "H0" else float(rules["external_contribution_per_4h"]),
        "committed_dca": committed, "executed_dca": executed,
        "dca_alloc_BTC": dca_alloc["BTC"], "dca_alloc_ETH": dca_alloc["ETH"],
        "target_basket_return": basket_return,
        "cash_drag_increment": (total_cash / end_value) * basket_return,
        "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
        "daily_floor_breach_reason": (
            "market_move_after_tactical_sell"
            if scenario.use_fsm and crypto_value / end_value < scenario.hard_floor - 1e-10 else "none"
        ),
    }


def run_initial_only(
    frame: pd.DataFrame, rules: dict[str, Any], scenario: V31Scenario,
) -> V31BacktestResult:
    state = V31State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(rules["initial_allocation_usd"][asset]), first_prices[asset], first_prices,
            timestamp=pd.Timestamp(first["open_time"]), scenario=scenario, action="INITIAL_ALLOCATION",
            ledger="normal", trades=trades, signal_date=first.get("signal_date"), reason="FRESH_2020_START_H0",
        )
    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    unit_nav = peak_nav = 1.0
    for _, row in frame.iterrows():
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}
        end_value = _portfolio_value(state, prices_close)
        twr_return = end_value / previous_value - 1.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        history.append(_history_row(
            state, row, scenario, prices_close, end_value, unit_nav, unit_nav / peak_nav - 1.0,
            twr_return, 0.0, 1, 0.0, 0.0, {asset: 0.0 for asset in ASSETS_V31},
            previous_closes, rules, "N/A",
        ))
        previous_value = end_value
        previous_closes = prices_close
    history_frame = pd.DataFrame(history)
    trade_frame = pd.DataFrame(trades)
    counters: dict[str, Any] = {}
    summary = calculate_summary(history_frame, trade_frame, scenario=scenario, counters=counters, rules=rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history_frame, trades=trade_frame,
        signals=pd.DataFrame(), transitions=pd.DataFrame(), cycles=pd.DataFrame(),
        temporary_lots=pd.DataFrame(), cash_events=pd.DataFrame(), counters=counters,
    )


def run_v32_backtest(
    frame: pd.DataFrame, base_rules: dict[str, Any], v32_rules: dict[str, Any],
    scenario: V31Scenario, *, model_a: V31BacktestResult,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.2 bars")
    state = V32State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    counters = {key: 0 for key in [
        "stage1_count", "stage2_count", "stage3_count", "stage4_count",
        "aborted_distribution_count", "value_buyback_count", "right_buyback_count",
        "bull_recovery_count", "new_bull_count", "new_bull_redeploy_count",
        "crash_level1_count", "crash_level2_count", "drift_sell_count", "dca_cash_shortfall_count",
    ]}
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(base_rules["initial_allocation_usd"][asset]), first_prices[asset], first_prices,
            timestamp=pd.Timestamp(first["open_time"]), scenario=scenario, action="INITIAL_ALLOCATION",
            ledger="normal", trades=trades, signal_date=first.get("signal_date"), reason="FRESH_2020_START",
        )
    a_history = model_a.history.set_index("timestamp")
    a_dca_frame = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")]
    a_dca = {
        (pd.Timestamp(ts), str(asset)): float(-group["cash_change_usd"].sum())
        for (ts, asset), group in a_dca_frame.groupby(["timestamp", "asset"])
    }
    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    previous_timestamp: pd.Timestamp | None = None
    unit_nav = peak_nav = 1.0

    for _, source_row in frame.iterrows():
        row = source_row.copy()
        row["strategy_name"] = scenario.name
        timestamp = pd.Timestamp(row["open_time"])
        elapsed = 1 if previous_timestamp is None else max(1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4))))
        external_flow = float(base_rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}
        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_state, before_stage, before_target = state.macro_state, state.stage, state.active_target
        before_exposure = _exposure(state, prices_open)
        actions: list[str] = []
        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, base_rules)
            _run_v32_macro_fsm(
                state, row, prices_open, base_rules, v32_rules, scenario, trades,
                transitions, cycles, cash_events, counters, actions,
            )
            _process_crash(
                state, row, prices_open, base_rules, scenario, trades,
                cash_events, counters, actions,
            )
            _process_temp_unwind(state, row, prices_open, base_rules, scenario, trades, actions)
            _process_v32_drift(
                state, row, prices_open, base_rules, v32_rules, scenario, trades, counters, actions,
            )
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.2 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(arow[f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
        for asset in ASSETS_V31:
            state.pending[asset] += dca_alloc[asset]
        executed = 0.0
        for asset in ASSETS_V31:
            budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
                executed += _buy(
                    state, asset, budget, prices_open[asset], prices_open, timestamp=timestamp,
                    scenario=scenario, action="NORMAL_DCA", ledger="pending", trades=trades,
                    signal_date=row.get("signal_date"), reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("Executed V3.2 DCA differs from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        histories.append(_history_row(
            state, row, scenario, prices_close, end_value, unit_nav, unit_nav / peak_nav - 1.0,
            twr_return, external_flow, elapsed, committed, executed, dca_alloc,
            previous_closes, base_rules, before_state,
        ))
        if is_new_signal:
            signals.append({
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"), "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "sma10": row.get("sma10"), "sma20": row.get("sma20"),
                "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "ahr999": row.get("ahr999_fixed_arithmetic"), "state_before": before_state,
                "state_after": state.macro_state, "stage_before": before_stage, "stage_after": state.stage,
                "active_target_before": before_target, "active_target_after": state.active_target,
                "crypto_exposure_before": before_exposure, "crypto_exposure_after": _exposure(state, prices_open),
                "tactical_bear_cash_after": state.tactical_bear_cash,
                "temporary_hedge_cash_after": _temp_cash(state), "actions": "|".join(actions),
                "distribution_confirmed": row.get("distribution_confirmed"),
                "early_bear_confirmed": row.get("early_bear_confirmed"),
                "stage3_confirmed": row.get("stage3_confirmed"),
                "below_sma200_count_7": row.get("below_sma200_count_7"),
                "deep_bear_structural_confirmed": row.get("deep_bear_structural_confirmed"),
                "deep_bear_exit_v32_confirmed": row.get("deep_bear_exit_v32_confirmed"),
                "crash_level1_raw": row.get("crash_level1_raw"),
                "crash_level2_market_raw": row.get("crash_level2_market_raw"),
                "right_50_confirmed": row.get("right_50_confirmed"),
                "right_60_v32_confirmed": row.get("right_60_v32_confirmed"),
                "bull_recovery_gate": row.get("bull_recovery_gate"),
                "recovery_new_bull_daily_condition": row.get("recovery_new_bull_daily_condition"),
                "recovery_mode": state.recovery_mode,
                "recovery_confirmation_days": state.recovery_confirmation_days,
                "deep_bear_days": state.signal_index - state.deep_bear_entry_signal_index if state.macro_state == "DEEP_BEAR" else 0,
                "macro_cooldown_days": state.macro_cooldown_days,
            })
        previous_value = end_value
        previous_closes = prices_close
        previous_timestamp = timestamp

    final_signal_date = frame.iloc[-1].get("signal_date")
    for item in cycles:
        if pd.isna(item["end"]):
            item["end"] = final_signal_date
            item["status"] = "OPEN_AT_END"
    history_frame = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history_frame, trade_frame, scenario=scenario, counters=counters, rules=base_rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history_frame, trades=trade_frame,
        signals=pd.DataFrame(signals), transitions=pd.DataFrame(transitions), cycles=pd.DataFrame(cycles),
        temporary_lots=pd.DataFrame(state.temporary_lots), cash_events=pd.DataFrame(cash_events), counters=counters,
    )
