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
    _buy,
    _buy_to_target,
    _cycle,
    _days_since,
    _exposure,
    _is_lock_active,
    _pending_cash,
    _portfolio_value,
    _process_drift,
    _reclassify_temp_to_bear,
    _sell_to_target,
    _stage_sell,
    _start_lock,
    _temp_cash,
    _transition,
    _truth,
    _update_temp_lots,
)
from .v34_engine import (
    REQUAL_STATES,
    V34State,
    _complete_new_bull_if_ready,
    _crash_level3_cash,
    _enter_new_bull,
    _history_row,
    _mark_deep_bear_entry,
    _new_cycle_v34,
    _process_crash_level3_recovery,
    _process_crash_v34,
    _process_legacy_temp_unwind,
    _process_macro_bull_requalification,
    _record_cycle_event,
    run_initial_only,
)


@dataclass
class V35State(V34State):
    accumulation_episode_id: int = 0
    next_accumulation_episode_id: int = 1
    accumulation_episode_active: bool = False
    value_base_buyback_used: bool = False
    deep_value_confidence: bool = False
    last_value_buyback_at: Any = None
    last_accumulation_action_at: Any = None
    value_rearm_new_low_seen: bool = False
    value_rearm_no_new_low_days: int = 0
    value_buyback_rearmed: bool = False
    sticky_accumulation_base: bool = False
    hard_failure_confirmed: bool = False
    hard_failure_exit_at: Any = None


def _cooldown_active(state: V35State, timestamp: pd.Timestamp, rules: dict[str, Any]) -> bool:
    wait = _days_since(timestamp, state.last_accumulation_action_at)
    return bool(
        pd.notna(wait)
        and wait < float(rules["accumulation_anti_whipsaw"]["action_cooldown_calendar_days"])
    )


def _start_episode(state: V35State) -> None:
    state.accumulation_episode_id = state.next_accumulation_episode_id
    state.next_accumulation_episode_id += 1
    state.accumulation_episode_active = True
    state.value_base_buyback_used = False
    state.deep_value_confidence = False
    state.value_rearm_new_low_seen = False
    state.value_rearm_no_new_low_days = 0
    state.value_buyback_rearmed = False
    state.sticky_accumulation_base = False
    state.hard_failure_confirmed = False
    state.hard_failure_exit_at = None


def _end_episode_on_new_bull(state: V35State) -> None:
    state.accumulation_episode_active = False
    state.value_base_buyback_used = False
    state.deep_value_confidence = False
    state.last_value_buyback_at = None
    state.last_accumulation_action_at = None
    state.value_rearm_new_low_seen = False
    state.value_rearm_no_new_low_days = 0
    state.value_buyback_rearmed = False
    state.sticky_accumulation_base = False
    state.hard_failure_confirmed = False
    state.hard_failure_exit_at = None


def _update_value_rearm(
    state: V35State,
    row: pd.Series,
    rules: dict[str, Any],
    actions: list[str],
) -> None:
    if not (
        state.accumulation_episode_active
        and state.value_base_buyback_used
        and state.active_target <= 0.25 + 1e-10
    ):
        return
    timestamp = pd.Timestamp(row["open_time"])
    wait = _days_since(timestamp, state.last_value_buyback_at)
    if pd.isna(wait) or wait < float(rules["accumulation_anti_whipsaw"]["value_rearm_min_calendar_days"]):
        return
    if _truth(row.get("new_20d_low")):
        state.value_rearm_new_low_seen = True
        state.value_rearm_no_new_low_days = 0
        actions.append("VALUE_REARM_NEW_20D_LOW_SEEN")
        return
    if state.value_rearm_new_low_seen:
        state.value_rearm_no_new_low_days += 1
        if state.value_rearm_no_new_low_days >= int(
            rules["accumulation_anti_whipsaw"]["value_rearm_no_new_low_completed_closes"]
        ):
            state.value_buyback_rearmed = True
            actions.append("VALUE_BASE_BUYBACK_REARMED")


def _value_base_buyback(
    state: V35State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> bool:
    patch = rules["accumulation_anti_whipsaw"]
    timestamp = pd.Timestamp(row["open_time"])
    if _cooldown_active(state, timestamp, rules):
        actions.append("VALUE_BASE_BUYBACK_BLOCKED_COOLDOWN")
        return False
    if state.value_base_buyback_used and not state.value_buyback_rearmed:
        actions.append("VALUE_BASE_BUYBACK_BLOCKED_SAME_EPISODE")
        return False
    if state.macro_state == "DEEP_BEAR":
        _transition(state, "ACCUMULATION", "PATCH_D_VALUE_BASE_ACCUMULATION", row, base_rules, transitions)
    if not state.accumulation_episode_active or state.value_buyback_rearmed:
        _start_episode(state)
    target = float(patch["value_base_target"])
    spent, outcome = _buy_to_target(
        state,
        row,
        prices,
        target,
        base_rules,
        scenario,
        trades,
        action="TACTICAL_BUYBACK_PATCH_D_VALUE_BASE_35",
        reason="AHR999_VALUE_BASE_TO_35",
        ledger="tactical_bear",
    )
    if spent > 0:
        state.active_target = target
        state.value_base_buyback_used = True
        state.sticky_accumulation_base = True
        state.last_value_buyback_at = timestamp
        state.last_accumulation_action_at = timestamp
        state.value_buyback_rearmed = False
        state.value_rearm_new_low_seen = False
        state.value_rearm_no_new_low_days = 0
        _start_lock(state, row, base_rules)
        counters["value_buyback_count"] += 1
        counters["patch_d_bottom_buy_count"] += 1
    _record_cycle_event(state, cycles, "accumulation", row, prices)
    actions.append(f"PATCH_D_VALUE_BASE_35:{outcome}")
    return spent > 0


def _right_side_buy(
    state: V35State,
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
    timestamp = pd.Timestamp(row["open_time"])
    if _cooldown_active(state, timestamp, rules):
        actions.append(f"PATCH_D_RIGHT_{int(target*100)}_BLOCKED_COOLDOWN")
        return
    spent, outcome = _buy_to_target(
        state,
        row,
        prices,
        target,
        base_rules,
        scenario,
        trades,
        action=f"TACTICAL_BUYBACK_PATCH_D_RIGHT_{int(target * 100)}",
        reason=f"PATCH_D_RIGHT_SIDE_TO_{int(target * 100)}",
        ledger="tactical_bear",
    )
    if spent > 0:
        state.active_target = target
        state.last_accumulation_action_at = timestamp
        _start_lock(state, row, base_rules)
        counters["right_buyback_count"] += 1
        counters["patch_d_bottom_buy_count"] += 1
    actions.append(f"PATCH_D_RIGHT_{int(target*100)}:{outcome}")


def _hard_failure_one_rung(
    state: V35State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    timestamp = pd.Timestamp(row["open_time"])
    if _cooldown_active(state, timestamp, rules):
        actions.append("PATCH_D_HARD_FAILURE_BLOCKED_COOLDOWN")
        return
    ladder = list(map(float, rules["accumulation_anti_whipsaw"]["exposure_ladder"]))
    current_index = min(range(len(ladder)), key=lambda i: abs(ladder[i] - state.active_target))
    if current_index <= 0:
        actions.append("PATCH_D_HARD_FAILURE_ALREADY_AT_25")
        return
    target = ladder[current_index - 1]
    sold, outcome, _ = _sell_to_target(
        state,
        row,
        prices,
        target,
        base_rules,
        scenario,
        trades,
        action=f"TACTICAL_SELL_PATCH_D_HARD_FAILURE_TO_{int(target * 100)}",
        reason="PATCH_D_CONFIRMED_HARD_FAILURE_ONE_RUNG",
        ledger="tactical_bear",
    )
    if sold > 0:
        state.active_target = target
        state.last_accumulation_action_at = timestamp
        state.hard_failure_confirmed = True
        counters["patch_d_bottom_sell_count"] += 1
        if target <= 0.25 + 1e-10:
            state.sticky_accumulation_base = False
            state.hard_failure_exit_at = timestamp
            _transition(state, "DEEP_BEAR", "PATCH_D_HARD_FAILURE_TO_25", row, base_rules, transitions)
            _mark_deep_bear_entry(state)
    actions.append(f"PATCH_D_HARD_FAILURE_TO_{int(target*100)}:{outcome}")


def _run_v35_macro_fsm(
    state: V35State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    v34_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    start_state = state.macro_state
    active_cycle = _cycle(state, cycles)
    if active_cycle is not None:
        active_cycle["cycle_peak_price"] = max(
            float(active_cycle["cycle_peak_price"]), float(row["BTC_daily_close"])
        )
    if start_state in REQUAL_STATES:
        close = float(row["BTC_daily_close"])
        if close < state.bear_low_price:
            state.bear_low_price = close
            state.bear_low_date = row.get("signal_date")
    _update_value_rearm(state, row, rules, actions)

    suspend_ordinary = _process_macro_bull_requalification(
        state, row, prices, base_rules, v34_rules, transitions, cycles, counters, actions
    )
    if suspend_ordinary:
        if state.macro_state == "NEW_BULL":
            _end_episode_on_new_bull(state)
        _complete_new_bull_if_ready(
            state, row, prices, base_rules, v34_rules, scenario, trades,
            transitions, cycles, cash_events, counters, actions,
        )
        return

    if start_state == "BULL":
        if state.macro_cooldown_days <= 0 and _truth(row.get("distribution_confirmed")):
            cycles.append(_new_cycle_v34(state, row, prices))
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
                active_cycle["cycle_closed"] = True
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
            _mark_deep_bear_entry(state)
            _stage_sell(
                state, 4, row, prices, base_rules, scenario, trades, cycles, actions,
                reason=reason, temporary=False,
            )
            counters["stage4_count"] += 1
        elif (
            pd.notna(row.get("ahr999_fixed_arithmetic"))
            and float(row["ahr999_fixed_arithmetic"]) <= float(rules["accumulation_anti_whipsaw"]["ahr999_value_threshold"])
        ):
            actions.append("PATCH_D_BEAR_AHR999_NO_DIRECT_ACCUMULATION")

    elif start_state == "DEEP_BEAR":
        ahr = row.get("ahr999_fixed_arithmetic")
        if pd.notna(ahr) and float(ahr) <= float(rules["accumulation_anti_whipsaw"]["deep_value_confidence_threshold"]):
            state.deep_value_confidence = True
            actions.append("DEEP_VALUE_CONFIDENCE_TRUE_NO_EXTRA_BUY")
        if (
            pd.notna(ahr)
            and float(ahr) <= float(rules["accumulation_anti_whipsaw"]["ahr999_value_threshold"])
            and state.active_target < 0.35 - 1e-10
        ):
            _value_base_buyback(
                state, row, prices, base_rules, rules, scenario, trades,
                transitions, cycles, counters, actions,
            )
        else:
            dwell = state.signal_index - state.deep_bear_entry_signal_index
            minimum = int(v34_rules["deep_bear_hysteresis"]["minimum_completed_daily_closes"])
            if dwell >= minimum and _truth(row.get("deep_bear_exit_v34_confirmed")):
                _transition(state, "BEAR", "DEEP_BEAR_HYSTERESIS_EXIT", row, base_rules, transitions)
                state.stage = 3
                state.active_target = 0.55
                actions.append("DEEP_BEAR_TO_BEAR_NO_AUTO_BUY")
            elif _truth(row.get("deep_bear_exit_v34_confirmed")):
                actions.append(f"DEEP_BEAR_EXIT_BLOCKED_MIN_DWELL_{dwell}_OF_{minimum}")

    elif start_state == "ACCUMULATION":
        days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
        gate7 = bool(
            pd.notna(days_since_low)
            and days_since_low >= float(base_rules["new_bull"]["minimum_calendar_days_since_bear_low"])
        )
        if _truth(row.get("new_bull_first_six")) and gate7:
            _enter_new_bull(
                state, row, prices, base_rules, v34_rules, transitions, cycles,
                counters, actions, path="V3.1_ORIGINAL",
            )
            _end_episode_on_new_bull(state)
        elif _truth(row.get("patch_d_hard_failure_confirmed")):
            _hard_failure_one_rung(
                state, row, prices, base_rules, rules, scenario, trades,
                transitions, cycles, counters, actions,
            )
        elif state.active_target <= 0.25 + 1e-10:
            ahr = row.get("ahr999_fixed_arithmetic")
            if pd.notna(ahr) and float(ahr) <= float(rules["accumulation_anti_whipsaw"]["ahr999_value_threshold"]):
                _value_base_buyback(
                    state, row, prices, base_rules, rules, scenario, trades,
                    transitions, cycles, counters, actions,
                )
        elif (
            abs(state.active_target - 0.35) <= 1e-10
            and _truth(row.get("patch_d_right_50_confirmed"))
        ):
            _right_side_buy(
                state, row, prices, 0.50, base_rules, rules, scenario,
                trades, counters, actions,
            )
        elif (
            abs(state.active_target - 0.50) <= 1e-10
            and _truth(row.get("patch_d_right_60_confirmed"))
        ):
            _right_side_buy(
                state, row, prices, 0.60, base_rules, rules, scenario,
                trades, counters, actions,
            )

    _complete_new_bull_if_ready(
        state, row, prices, base_rules, v34_rules, scenario, trades,
        transitions, cycles, cash_events, counters, actions,
    )


def _process_drift_v35(
    state: V35State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    if state.accumulation_episode_active and _cooldown_active(state, pd.Timestamp(row["open_time"]), rules):
        actions.append("PATCH_D_ORDINARY_DRIFT_BLOCKED_COOLDOWN")
        return
    before = int(counters["drift_sell_count"])
    _process_drift(state, row, prices, base_rules, scenario, trades, counters, actions)
    if int(counters["drift_sell_count"]) > before and state.accumulation_episode_active:
        state.last_accumulation_action_at = pd.Timestamp(row["open_time"])
        counters["patch_d_bottom_sell_count"] += 1


def run_v35_backtest(
    frame: pd.DataFrame,
    base_rules: dict[str, Any],
    v34_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.5 bars")
    state = V35State(normal_cash=float(scenario.initial_capital))
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
        "crash_level2_count", "crash_level3_count", "crash_level3_recovery_count",
        "macro_bull_candidate_count", "macro_bear_invalidated_count",
        "macro_bull_requalification_count", "final_cash_sweep_count",
        "cash_reset_block_count", "drift_sell_count", "dca_cash_shortfall_count",
        "patch_d_bottom_buy_count", "patch_d_bottom_sell_count",
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
        elapsed = 1 if previous_timestamp is None else max(
            1, int(round((timestamp - previous_timestamp) / pd.Timedelta(hours=4)))
        )
        external_flow = float(base_rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}
        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_state, before_stage, before_target = state.macro_state, state.stage, state.active_target
        before_exposure = _exposure(state, prices_open)
        before_l3_cash = _crash_level3_cash(state)
        previous_action_at = state.last_accumulation_action_at
        actions: list[str] = []
        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, base_rules)
            _run_v35_macro_fsm(
                state, row, prices_open, base_rules, v34_rules, rules, scenario,
                trades, transitions, cycles, cash_events, counters, actions,
            )
            _process_crash_v34(
                state, row, prices_open, base_rules, v34_rules, scenario,
                trades, cash_events, counters, actions,
            )
            _process_crash_level3_recovery(
                state, row, prices_open, base_rules, v34_rules, scenario,
                trades, counters, actions,
            )
            _process_legacy_temp_unwind(
                state, row, prices_open, base_rules, scenario, trades, actions
            )
            _process_drift_v35(
                state, row, prices_open, base_rules, rules, scenario,
                trades, counters, actions,
            )
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.5 cannot replay Model A DCA commitment")
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
                    timestamp=timestamp, scenario=scenario, action="NORMAL_DCA",
                    ledger="pending", trades=trades, signal_date=row.get("signal_date"),
                    reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("Executed V3.5 DCA differs from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        history_row = _history_row(
            state, row, scenario, prices_close, end_value, unit_nav,
            unit_nav / peak_nav - 1.0, twr_return, external_flow, elapsed,
            committed, executed, dca_alloc, previous_closes, base_rules, before_state,
        )
        history_row.update({
            "accumulation_episode_id": state.accumulation_episode_id,
            "accumulation_episode_active": state.accumulation_episode_active,
            "value_base_buyback_used": state.value_base_buyback_used,
            "deep_value_confidence": state.deep_value_confidence,
            "value_buyback_rearmed": state.value_buyback_rearmed,
            "sticky_accumulation_base": state.sticky_accumulation_base,
            "hard_failure_confirmed": state.hard_failure_confirmed,
            "accumulation_action_cooldown_active": _cooldown_active(state, timestamp, rules),
        })
        histories.append(history_row)
        if is_new_signal:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            days_since_action = _days_since(timestamp, previous_action_at)
            signals.append({
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"), "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "sma10": row.get("sma10"), "sma20": row.get("sma20"),
                "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "state_before": before_state, "state_after": state.macro_state,
                "stage_before": before_stage, "stage_after": state.stage,
                "active_target_before": before_target, "active_target_after": state.active_target,
                "crypto_exposure_before": before_exposure, "crypto_exposure_after": _exposure(state, prices_open),
                "tactical_bear_cash_after": state.tactical_bear_cash,
                "temporary_hedge_cash_after": _temp_cash(state),
                "crash_level3_cash_before": before_l3_cash,
                "crash_level3_cash_after": _crash_level3_cash(state),
                "actions": "|".join(actions),
                "distribution_confirmed": row.get("distribution_confirmed"),
                "early_bear_confirmed": row.get("early_bear_confirmed"),
                "stage3_confirmed": row.get("stage3_confirmed"),
                "deep_bear_structural_confirmed": row.get("deep_bear_structural_confirmed"),
                "deep_bear_exit_v34_confirmed": row.get("deep_bear_exit_v34_confirmed"),
                "deep_bear_dwell_days": state.signal_index - state.deep_bear_entry_signal_index if before_state == "DEEP_BEAR" or state.macro_state == "DEEP_BEAR" else 0,
                "crash_level1_raw": row.get("crash_level1_raw"),
                "crash_level2_market_raw": row.get("crash_level2_market_raw"),
                "crash_level3_price_raw": row.get("crash_level3_price_raw"),
                "crash_recovery_market_raw": row.get("crash_recovery_market_raw"),
                "crash_episode_id": state.crash_episode_id,
                "crash_level2_active": state.crash_level2_fired and state.crash_episode_active,
                "crash_level3_used": state.crash_level3_used,
                "macro_bull_requalification_market_candidate": row.get("macro_bull_requalification_market_candidate"),
                "macro_bull_candidate_confirmation_market": row.get("macro_bull_candidate_confirmation_market"),
                "macro_bull_new_bull_confirmation_market": row.get("macro_bull_new_bull_confirmation_market"),
                "requal_candidate_active": state.requal_candidate_active,
                "requal_candidate_following_days": state.requal_candidate_following_days,
                "macro_bear_invalidated": state.macro_bear_invalidated,
                "requal_new_bull_following_days": state.requal_new_bull_following_days,
                "new_20d_low": row.get("new_20d_low"),
                "patch_d_right_50_confirmed": row.get("patch_d_right_50_confirmed"),
                "patch_d_right_60_confirmed": row.get("patch_d_right_60_confirmed"),
                "patch_d_hard_failure_confirmed": row.get("patch_d_hard_failure_confirmed"),
                "accumulation_episode_id": state.accumulation_episode_id,
                "accumulation_episode_active": state.accumulation_episode_active,
                "value_base_buyback_used": state.value_base_buyback_used,
                "value_buyback_rearmed": state.value_buyback_rearmed,
                "sticky_accumulation_base": state.sticky_accumulation_base,
                "hard_failure_confirmed": state.hard_failure_confirmed,
                "cooldown_active": _cooldown_active(state, timestamp, rules),
                "days_since_previous_accumulation_action": days_since_action,
                "right_50_confirmed": row.get("right_50_confirmed"),
                "right_60_confirmed": row.get("right_60_confirmed"),
                **{f"new_bull_gate_{i}": row.get(f"new_bull_gate_{i}") for i in range(1, 7)},
                "new_bull_gate_7": bool(pd.notna(days_since_low) and days_since_low >= float(base_rules["new_bull"]["minimum_calendar_days_since_bear_low"])),
            })
        previous_value = end_value
        previous_closes = prices_close
        previous_timestamp = timestamp

    final_signal_date = frame.iloc[-1].get("signal_date")
    for item in cycles:
        if pd.isna(item["end"]):
            item["end"] = final_signal_date
            item["status"] = "CLOSING_NEW_BULL_AT_END" if item.get("status") == "CLOSING_NEW_BULL" else "OPEN_AT_END"
    history_frame = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history_frame, trade_frame, scenario=scenario, counters=counters, rules=base_rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history_frame, trades=trade_frame,
        signals=pd.DataFrame(signals), transitions=pd.DataFrame(transitions), cycles=pd.DataFrame(cycles),
        temporary_lots=pd.DataFrame(state.temporary_lots), cash_events=pd.DataFrame(cash_events), counters=counters,
    )


__all__ = ["V35State", "run_initial_only", "run_v35_backtest"]
