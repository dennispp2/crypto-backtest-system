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
    _budget_to_target,
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


BEARISH_STATES = {"EARLY_BEAR", "BEAR", "DEEP_BEAR"}
REQUAL_STATES = {"BEAR", "DEEP_BEAR", "ACCUMULATION"}


@dataclass
class V34State(V31State):
    deep_bear_entry_signal_index: int = 0
    crash_episode_active: bool = False
    crash_episode_id: int = 0
    crash_level3_used: bool = False
    actual_l2_signal_indices: list[int] = field(default_factory=list)
    actual_l3_signal_indices: list[int] = field(default_factory=list)
    requal_candidate_active: bool = False
    requal_candidate_date: Any = None
    requal_candidate_following_days: int = 0
    macro_bear_invalidated: bool = False
    macro_bear_invalidated_date: Any = None
    requal_new_bull_following_days: int = 0


def _crash_level3_cash(state: V34State) -> float:
    return float(sum(
        float(lot.get("cash_remaining", 0.0))
        for lot in state.temporary_lots
        if lot.get("status") == "OPEN" and lot.get("source") == "CRASH_LEVEL3"
    ))


def _new_cycle_v34(state: V34State, row: pd.Series, prices: dict[str, float]) -> dict[str, Any]:
    item = _new_cycle(state, row, prices)
    item.update({
        "cycle_closed": False,
        "accumulation_date": pd.NaT,
        "accumulation_btc_price": np.nan,
        "accumulation_exposure": np.nan,
        "requal_candidate_date": pd.NaT,
        "macro_bear_invalidated_date": pd.NaT,
        "new_bull_path": "",
        "new_bull_btc_price": np.nan,
        "new_bull_exposure": np.nan,
        "bull_date": pd.NaT,
        "bull_btc_price": np.nan,
        "bull_exposure": np.nan,
        "final_cash_sweep_date": pd.NaT,
        "final_cash_sweep_spent": 0.0,
        "cash_reset_audit": "NOT_APPLICABLE",
        "cash_reset_reason": "",
        "tactical_bear_cash_ratio_at_close": np.nan,
    })
    return item


def _record_cycle_event(
    state: V34State,
    cycles: list[dict[str, Any]],
    event: str,
    row: pd.Series,
    prices: dict[str, float],
) -> None:
    item = _cycle(state, cycles)
    if item is None or pd.notna(item.get(f"{event}_date")):
        return
    item[f"{event}_date"] = row.get("signal_date")
    item[f"{event}_btc_price"] = float(row["BTC_daily_close"])
    item[f"{event}_exposure"] = _exposure(state, prices)


def _mark_deep_bear_entry(state: V34State) -> None:
    state.deep_bear_entry_signal_index = state.signal_index


def _reset_requalification(state: V34State) -> None:
    state.requal_candidate_active = False
    state.requal_candidate_date = None
    state.requal_candidate_following_days = 0
    state.macro_bear_invalidated = False
    state.macro_bear_invalidated_date = None
    state.requal_new_bull_following_days = 0


def _recent_actual_crash(state: V34State, *, level: int, days: int) -> bool:
    indices = state.actual_l2_signal_indices if level == 2 else state.actual_l3_signal_indices
    return any(state.signal_index - index < days for index in indices)


def _current_crash_free(row: pd.Series) -> bool:
    return not _truth(row.get("crash_level2_market_raw")) and not _truth(row.get("crash_level3_price_raw"))


def _patch_transition_to_new_bull(
    state: V34State,
    row: pd.Series,
    transitions: list[dict[str, Any]],
) -> None:
    before = state.macro_state
    if before not in REQUAL_STATES:
        raise AssertionError(f"Illegal V3.4 requalification transition {before} -> NEW_BULL")
    transitions.append({
        "strategy": row.get("strategy_name", ""),
        "signal_date": row.get("signal_date"),
        "execution_4h_open": row.get("open_time"),
        "from_state": before,
        "to_state": "NEW_BULL",
        "reason": "MACRO_BULL_REQUALIFICATION_NEW_BULL",
        "cycle_id": state.active_cycle_id,
        "ai_intervention": "NONE",
    })
    state.macro_state = "NEW_BULL"
    state.regime_days = 0


def _reclassify_cycle_temporary_cash(
    state: V34State,
    row: pd.Series,
    cycles: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
) -> float:
    active = _cycle(state, cycles)
    if active is None:
        return 0.0
    moved = 0.0
    for lot in state.temporary_lots:
        if lot.get("status") != "OPEN" or int(lot.get("cycle_id", 0)) != state.active_cycle_id:
            continue
        residual = float(lot.get("cash_remaining", 0.0))
        moved += residual
        lot["cash_remaining"] = 0.0
        lot["status"] = "RECLASSIFIED_FINAL_SWEEP" if residual > 1e-10 else "CLOSED_FINAL_SWEEP"
        lot["closed_date"] = row.get("signal_date")
        lot["closure_reason"] = "PRE_NEW_BULL_FINAL_CASH_SWEEP"
    if moved > 0:
        state.tactical_bear_cash += moved
        cash_events.append({
            "strategy": row.get("strategy_name", ""),
            "date": row.get("signal_date"),
            "event": "TEMPORARY_TO_TACTICAL_BEAR_BEFORE_FINAL_SWEEP",
            "amount_usd": moved,
            "reason": "CLOSE_ACTIVE_CYCLE_TEMPORARY_REFERENCES",
            "cycle_id": state.active_cycle_id,
        })
    return moved


def _final_cash_sweep(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
) -> tuple[float, str]:
    sweep = rules["final_cash_sweep"]
    total = _portfolio_value(state, prices)
    ratio = state.tactical_bear_cash / total if total > 0 else 0.0
    if ratio <= float(sweep["trigger_tactical_bear_cash_ratio_above"]) + 1e-12:
        return 0.0, "NOT_REQUIRED"
    needed = min(
        _budget_to_target(state, prices, float(sweep["target_exposure"]), scenario),
        state.tactical_bear_cash,
    )
    ordinary_minimum = max(
        float(base_rules["turnover_guard"]["minimum_notional_usd"]),
        float(base_rules["turnover_guard"]["minimum_portfolio_fraction"]) * total,
    )
    if needed + 1e-10 < ordinary_minimum:
        return 0.0, "NOTIONAL_BELOW_UNCHANGED_TURNOVER_GUARD"
    before = _exposure(state, prices)
    state.tactical_event_id += 1
    budgets = {
        asset: needed * float(base_rules["target_weights"][asset]) for asset in ASSETS_V31
    }
    spent = 0.0
    for asset in ASSETS_V31:
        if budgets[asset] + 1e-10 < float(base_rules["modeled_min_notional_usdt"][asset]):
            continue
        spent += _buy(
            state,
            asset,
            budgets[asset],
            prices[asset],
            prices,
            timestamp=pd.Timestamp(row["open_time"]),
            scenario=scenario,
            action="TACTICAL_BUYBACK_FINAL_CASH_SWEEP",
            ledger="tactical_bear",
            trades=trades,
            signal_date=row.get("signal_date"),
            reason="NEW_BULL_FINAL_CASH_SWEEP",
            event_before=before,
            target=float(sweep["target_exposure"]),
        )
    return spent, "EXECUTED" if spent > 0 else "MINIMUM_NOTIONAL"


def _cash_reset_status(
    state: V34State,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[bool, str, float]:
    portfolio = _portfolio_value(state, prices)
    ratio = state.tactical_bear_cash / portfolio if portfolio > 0 else 0.0
    if ratio <= float(rules["cycle_reset"]["cash_reset_max_tactical_bear_cash_ratio"]) + 1e-12:
        return True, "TACTICAL_BEAR_CASH_AT_OR_BELOW_1_PERCENT", ratio
    exemption = sum(float(value) for value in base_rules["modeled_min_notional_usdt"].values()) + 0.01
    if state.tactical_bear_cash <= exemption + 1e-12:
        return True, "MODELED_MIN_NOTIONAL_OR_ROUNDING", ratio
    return False, "TACTICAL_BEAR_CASH_ABOVE_1_PERCENT_AFTER_FINAL_SWEEP", ratio


def _enter_new_bull(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
    *,
    path: str,
) -> None:
    if path == "MACRO_BULL_REQUALIFICATION":
        _patch_transition_to_new_bull(state, row, transitions)
    else:
        _transition(state, "NEW_BULL", "NEW_BULL_ALL_SEVEN_GATES", row, base_rules, transitions)
    state.stage = 0
    state.active_target = float(base_rules["new_bull"]["completion_target"])
    state.redeploy_days_remaining = int(base_rules["new_bull"]["redeploy_trading_days"])
    active = _cycle(state, cycles)
    if active is not None:
        active["new_bull_date"] = row.get("signal_date")
        active["new_bull_path"] = path
        active["status"] = str(rules["cycle_reset"]["on_new_bull_confirmed_status"])
    _record_cycle_event(state, cycles, "new_bull", row, prices)
    counters["new_bull_count"] += 1
    if path == "MACRO_BULL_REQUALIFICATION":
        counters["macro_bull_requalification_count"] += 1
    actions.append(f"NEW_BULL_CONFIRMED:{path}")


def _process_macro_bull_requalification(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> bool:
    """Return True when ordinary bear-state FSM processing must be suspended."""
    req = rules["macro_bull_requalification"]
    eligible = state.macro_state in set(req["eligible_states"])
    crash_free_30 = (
        not _recent_actual_crash(
            state, level=2, days=int(req["crash_free_completed_closes"])
        )
        and not _recent_actual_crash(
            state, level=3, days=int(req["crash_free_completed_closes"])
        )
        and _current_crash_free(row)
    )
    if not eligible:
        _reset_requalification(state)
        return False

    just_invalidated = False
    if not state.macro_bear_invalidated:
        if state.requal_candidate_active:
            confirmation_ok = (
                _truth(row.get("macro_bull_candidate_confirmation_market")) and crash_free_30
            )
            if confirmation_ok:
                state.requal_candidate_following_days += 1
                actions.append(
                    "MACRO_BULL_REQUALIFICATION_CONFIRM_"
                    f"{state.requal_candidate_following_days}_OF_"
                    f"{int(req['candidate_following_confirmation_closes'])}"
                )
                if state.requal_candidate_following_days >= int(
                    req["candidate_following_confirmation_closes"]
                ):
                    state.macro_bear_invalidated = True
                    state.macro_bear_invalidated_date = row.get("signal_date")
                    state.requal_new_bull_following_days = 0
                    state.active_target = float(req["invalidated_target"])
                    active = _cycle(state, cycles)
                    if active is not None:
                        active["macro_bear_invalidated_date"] = row.get("signal_date")
                    counters["macro_bear_invalidated_count"] += 1
                    actions.append("MACRO_BEAR_INVALIDATED_TARGET_70")
                    just_invalidated = True
            else:
                actions.append("MACRO_BULL_REQUALIFICATION_CANDIDATE_RESET")
                state.requal_candidate_active = False
                state.requal_candidate_date = None
                state.requal_candidate_following_days = 0
        elif (
            _truth(row.get("macro_bull_requalification_market_candidate")) and crash_free_30
        ):
            state.requal_candidate_active = True
            state.requal_candidate_date = row.get("signal_date")
            state.requal_candidate_following_days = 0
            active = _cycle(state, cycles)
            if active is not None and pd.isna(active.get("requal_candidate_date")):
                active["requal_candidate_date"] = row.get("signal_date")
            counters["macro_bull_candidate_count"] += 1
            actions.append("MACRO_BULL_REQUALIFICATION_CANDIDATE")

    if not state.macro_bear_invalidated:
        return False

    state.active_target = float(req["invalidated_target"])
    if just_invalidated:
        return True
    new_bull_ok = (
        _truth(row.get("macro_bull_new_bull_confirmation_market")) and crash_free_30
    )
    if new_bull_ok:
        state.requal_new_bull_following_days += 1
        actions.append(
            "MACRO_BULL_NEW_BULL_CONFIRM_"
            f"{state.requal_new_bull_following_days}_OF_"
            f"{int(req['new_bull_following_confirmation_closes'])}"
        )
        if state.requal_new_bull_following_days >= int(
            req["new_bull_following_confirmation_closes"]
        ):
            _enter_new_bull(
                state,
                row,
                prices,
                base_rules,
                rules,
                transitions,
                cycles,
                counters,
                actions,
                path="MACRO_BULL_REQUALIFICATION",
            )
            return True
    else:
        state.requal_new_bull_following_days = 0
        actions.append("MACRO_BULL_NEW_BULL_CONFIRM_RESET")
    return True


def _complete_new_bull_if_ready(
    state: V34State,
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
) -> None:
    if state.macro_state != "NEW_BULL":
        return
    if state.redeploy_days_remaining > 0:
        cap = state.tactical_bear_cash / float(state.redeploy_days_remaining)
        spent, outcome = _buy_to_target(
            state,
            row,
            prices,
            float(base_rules["new_bull"]["completion_target"]),
            base_rules,
            scenario,
            trades,
            action="TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
            reason="TEN_DAY_NEW_BULL_REDEPLOY",
            ledger="tactical_bear",
            budget_cap=cap,
        )
        state.redeploy_days_remaining -= 1
        if spent > 0:
            counters["new_bull_redeploy_count"] += 1
        actions.append(f"NEW_BULL_REDEPLOY:{outcome}")
    if state.redeploy_days_remaining > 0:
        return

    _reclassify_cycle_temporary_cash(state, row, cycles, cash_events)
    spent, outcome = _final_cash_sweep(
        state, row, prices, base_rules, rules, scenario, trades
    )
    if outcome != "NOT_REQUIRED":
        counters["final_cash_sweep_count"] += int(spent > 0)
        actions.append(f"FINAL_CASH_SWEEP:{outcome}")
    active = _cycle(state, cycles)
    if active is not None and spent > 0:
        active["final_cash_sweep_date"] = row.get("signal_date")
        active["final_cash_sweep_spent"] = float(active["final_cash_sweep_spent"]) + spent
    cash_pass, cash_reason, cash_ratio = _cash_reset_status(
        state, prices, base_rules, rules
    )
    if active is not None:
        active["cash_reset_audit"] = "PASS" if cash_pass else "FAIL"
        active["cash_reset_reason"] = cash_reason
        active["tactical_bear_cash_ratio_at_close"] = cash_ratio
    if not cash_pass:
        counters["cash_reset_block_count"] += 1
        actions.append("NEW_BULL_CLOSE_BLOCKED_CASH_RESET")
        return

    _transition(state, "BULL", "NEW_BULL_REDEPLOY_AND_FINAL_SWEEP_COMPLETE", row, base_rules, transitions)
    _record_cycle_event(state, cycles, "bull", row, prices)
    if active is not None:
        active["end"] = row.get("signal_date")
        active["status"] = str(rules["cycle_reset"]["on_bull_status"])
        active["cycle_closed"] = True
    state.active_cycle_id = 0
    state.stage = 0
    state.active_target = float(base_rules["new_bull"]["completion_target"])
    state.macro_cooldown_days = int(base_rules["new_bull"]["macro_cooldown_trading_days"])
    _reset_requalification(state)
    actions.append("NEW_BULL_COMPLETE_FINAL_CASH_SWEEP_CYCLE_RESET")


def _run_v34_macro_fsm(
    state: V34State,
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
) -> None:
    """V3.1 FSM plus only frozen V3.4 patches and V3.3 hysteresis."""
    start_state = state.macro_state
    timestamp = pd.Timestamp(row["open_time"])
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

    suspend_ordinary = _process_macro_bull_requalification(
        state, row, prices, base_rules, rules, transitions, cycles, counters, actions
    )
    if suspend_ordinary:
        _complete_new_bull_if_ready(
            state, row, prices, base_rules, rules, scenario, trades,
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
            and float(row["ahr999_fixed_arithmetic"]) <= float(base_rules["buyback"]["ahr999_threshold"])
        ):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, base_rules, transitions)
            state.active_target = float(base_rules["buyback"]["value_target"])
            spent, outcome = _buy_to_target(
                state, row, prices, state.active_target, base_rules, scenario, trades,
                action="TACTICAL_BUYBACK_AHR999_TO_35", reason="AHR999<=0.35", ledger="tactical_bear",
            )
            if spent > 0:
                _start_lock(state, row, base_rules)
                counters["value_buyback_count"] += 1
            _record_cycle_event(state, cycles, "accumulation", row, prices)
            actions.append(f"AHR999_TO35:{outcome}")

    elif start_state == "DEEP_BEAR":
        if (
            pd.notna(row.get("ahr999_fixed_arithmetic"))
            and float(row["ahr999_fixed_arithmetic"]) <= float(base_rules["buyback"]["ahr999_threshold"])
        ):
            _transition(state, "ACCUMULATION", "AHR999_VALUE_ACCUMULATION", row, base_rules, transitions)
            state.active_target = float(base_rules["buyback"]["value_target"])
            spent, outcome = _buy_to_target(
                state, row, prices, state.active_target, base_rules, scenario, trades,
                action="TACTICAL_BUYBACK_AHR999_TO_35", reason="AHR999<=0.35", ledger="tactical_bear",
            )
            if spent > 0:
                _start_lock(state, row, base_rules)
                counters["value_buyback_count"] += 1
            _record_cycle_event(state, cycles, "accumulation", row, prices)
            actions.append(f"AHR999_TO35:{outcome}")
        else:
            dwell = state.signal_index - state.deep_bear_entry_signal_index
            minimum = int(rules["deep_bear_hysteresis"]["minimum_completed_daily_closes"])
            if dwell >= minimum and _truth(row.get("deep_bear_exit_v34_confirmed")):
                _transition(state, "BEAR", "DEEP_BEAR_HYSTERESIS_EXIT", row, base_rules, transitions)
                state.stage = 3
                state.active_target = 0.55
                actions.append("DEEP_BEAR_TO_BEAR_NO_AUTO_BUY")
            elif _truth(row.get("deep_bear_exit_v34_confirmed")):
                actions.append(f"DEEP_BEAR_EXIT_BLOCKED_MIN_DWELL_{dwell}_OF_{minimum}")

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
            if to_state == "DEEP_BEAR":
                _mark_deep_bear_entry(state)
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
                _enter_new_bull(
                    state, row, prices, base_rules, rules, transitions, cycles,
                    counters, actions, path="V3.1_ORIGINAL",
                )
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
                if desired is not None:
                    state.active_target = desired
                    spent, outcome = _buy_to_target(
                        state, row, prices, desired, base_rules, scenario, trades,
                        action=f"TACTICAL_BUYBACK_RIGHT_TO_{int(desired * 100)}",
                        reason=f"RIGHT_SIDE_TO_{int(desired * 100)}", ledger="tactical_bear",
                    )
                    if spent > 0:
                        if desired == 0.50:
                            state.right_50_done = True
                        else:
                            state.right_60_done = True
                        _start_lock(state, row, base_rules)
                        counters["right_buyback_count"] += 1
                    actions.append(f"RIGHT_TO_{int(desired * 100)}:{outcome}")

    _complete_new_bull_if_ready(
        state, row, prices, base_rules, rules, scenario, trades,
        transitions, cycles, cash_events, counters, actions,
    )


def _process_crash_v34(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    cash_events: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    l1_before = int(counters["crash_level1_count"])
    l2_before = int(counters["crash_level2_count"])
    _process_crash(
        state, row, prices, base_rules, scenario, trades, cash_events, counters, actions
    )
    if int(counters["crash_level1_count"]) > l1_before:
        state.crash_episode_id += 1
        state.crash_episode_active = True
        state.crash_level3_used = False
        actions.append(f"CRASH_EPISODE_{state.crash_episode_id}_START")
    if int(counters["crash_level2_count"]) > l2_before:
        state.actual_l2_signal_indices.append(state.signal_index)
        actions.append("CRASH_L2_ACTUAL_RECORDED")

    crash = rules["crash_level_3"]
    eligible = (
        state.crash_episode_active
        and state.crash_level2_fired
        and not state.crash_level3_used
        and _truth(row.get("crash_level3_price_raw"))
    )
    if eligible:
        before = _exposure(state, prices)
        sold = 0.0
        outcome = "EXPOSURE_ALREADY_AT_OR_BELOW_35"
        lot = None
        if before > float(crash["target_exposure"]) + 1e-12:
            sold, outcome, lot = _sell_to_target(
                state,
                row,
                prices,
                float(crash["target_exposure"]),
                base_rules,
                scenario,
                trades,
                action="TEMPORARY_CRASH_SELL_LEVEL3",
                reason="CRASH_LEVEL3",
                ledger="temporary_hedge",
            )
        state.crash_level3_used = True
        state.actual_l3_signal_indices.append(state.signal_index)
        counters["crash_level3_count"] += 1
        if lot is not None:
            lot.update({
                "source": "CRASH_LEVEL3",
                "crash_episode_id": state.crash_episode_id,
                "pre_crash_macro_target": float(state.active_target),
                "pre_crash_exposure": before,
                "level3_trigger_date": row.get("signal_date"),
                "level3_trigger_btc_close": float(row["BTC_daily_close"]),
                "recovery_confirmed_date": pd.NaT,
                "unwind_completed_date": pd.NaT,
            })
        actions.append(f"CRASH_L3:{outcome}")
        if sold > 0 and state.macro_state in BEARISH_STATES | {"ACCUMULATION"}:
            _reclassify_temp_to_bear(state, row, cash_events, "CRASH_LEVEL3_DURING_MACRO_BEAR")

    if state.macro_state in BEARISH_STATES:
        state.crash_episode_active = False
        state.crash_level3_used = False
    elif (
        state.crash_episode_active
        and state.crash_level1_days_remaining <= 0
        and state.crash_armed
        and state.crash_clear_days >= int(base_rules["crash_brake"]["rearm_clear_days"])
    ):
        state.crash_episode_active = False
        state.crash_level3_used = False
        actions.append(f"CRASH_EPISODE_{state.crash_episode_id}_END")


def _process_legacy_temp_unwind(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    actions: list[str],
) -> None:
    """Unchanged V3.1 unwind for non-L3 lots; L3 has its own recovery gate."""
    if state.macro_state != "BULL" or not _truth(row.get("bull_5_confirmed")):
        return
    observation = int(base_rules["temporary_hedge"]["observation_trading_days"])
    unwind_days = int(base_rules["temporary_hedge"]["unwind_trading_days"])
    for lot in state.temporary_lots:
        if (
            lot.get("status") != "OPEN"
            or lot.get("bear_confirmed")
            or lot.get("source") == "CRASH_LEVEL3"
        ):
            continue
        if state.signal_index - int(lot["created_signal_index"]) < observation:
            continue
        if int(lot["unwind_days_remaining"]) == 0 and pd.isna(lot["unwind_started_date"]):
            lot["unwind_started_date"] = row.get("signal_date")
            lot["unwind_days_remaining"] = unwind_days
        if int(lot["unwind_days_remaining"]) <= 0:
            continue
        cap = float(lot["cash_remaining"]) / float(lot["unwind_days_remaining"])
        spent, outcome = _buy_to_target(
            state,
            row,
            prices,
            0.95,
            base_rules,
            scenario,
            trades,
            action="TACTICAL_BUY_TEMPORARY_HEDGE_UNWIND",
            reason=f"temporary_lot_{lot['lot_id']}_five_day_unwind",
            ledger="temporary_hedge",
            temp_lot=lot,
            budget_cap=cap,
        )
        lot["unwind_days_remaining"] -= 1
        actions.append(f"TEMP_UNWIND_LOT_{lot['lot_id']}:{outcome}")
        if float(lot["cash_remaining"]) <= 1e-8:
            lot["cash_remaining"] = 0.0
            lot["status"] = "UNWOUND"
            lot["closed_date"] = row.get("signal_date")
            lot["closure_reason"] = "FIVE_DAY_UNWIND"
        elif int(lot["unwind_days_remaining"]) == 0:
            lot["unwind_started_date"] = pd.NaT


def _process_crash_level3_recovery(
    state: V34State,
    row: pd.Series,
    prices: dict[str, float],
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    if state.macro_state in BEARISH_STATES:
        return
    crash = rules["crash_level_3"]
    open_lots = [
        lot for lot in state.temporary_lots
        if lot.get("status") == "OPEN" and lot.get("source") == "CRASH_LEVEL3"
    ]
    if not open_lots:
        return
    recovery = (
        _truth(row.get("crash_recovery_market_raw"))
        and not _recent_actual_crash(
            state,
            level=2,
            days=int(crash["recovery_crash_level2_free_completed_closes"]),
        )
    )
    for lot in open_lots:
        if recovery and pd.isna(lot.get("recovery_confirmed_date")):
            lot["recovery_confirmed_date"] = row.get("signal_date")
            lot["unwind_started_date"] = row.get("signal_date")
            lot["unwind_days_remaining"] = int(crash["unwind_trading_days"])
            counters["crash_level3_recovery_count"] += 1
            actions.append(f"CRASH_L3_RECOVERY_CONFIRMED_LOT_{lot['lot_id']}")
        if pd.isna(lot.get("recovery_confirmed_date")):
            continue
        if int(lot.get("unwind_days_remaining", 0)) <= 0:
            lot["unwind_started_date"] = row.get("signal_date")
            lot["unwind_days_remaining"] = int(crash["unwind_trading_days"])
        cap = float(lot["cash_remaining"]) / float(lot["unwind_days_remaining"])
        target = min(float(lot.get("pre_crash_macro_target", 0.95)), float(state.active_target))
        spent, outcome = _buy_to_target(
            state,
            row,
            prices,
            target,
            base_rules,
            scenario,
            trades,
            action="TACTICAL_BUY_CRASH_LEVEL3_RECOVERY",
            reason=f"crash_level3_lot_{lot['lot_id']}_five_day_unwind",
            ledger="temporary_hedge",
            temp_lot=lot,
            budget_cap=cap,
        )
        lot["unwind_days_remaining"] -= 1
        actions.append(f"CRASH_L3_UNWIND_LOT_{lot['lot_id']}:{outcome}")
        if float(lot["cash_remaining"]) <= 1e-8:
            lot["cash_remaining"] = 0.0
            lot["status"] = "UNWOUND"
            lot["closed_date"] = row.get("signal_date")
            lot["unwind_completed_date"] = row.get("signal_date")
            lot["closure_reason"] = "CRASH_LEVEL3_FIVE_DAY_UNWIND"


def _history_row(
    state: V34State,
    row: pd.Series,
    scenario: V31Scenario,
    prices_close: dict[str, float],
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
    rules: dict[str, Any],
    before_state: str,
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
        "crash_level3_cash": _crash_level3_cash(state),
        "tactical_cash": tactical_cash,
        "normal_cash_ratio": state.normal_cash / end_value,
        "tactical_bear_cash_ratio": state.tactical_bear_cash / end_value,
        "temporary_hedge_cash_ratio": temporary_cash / end_value,
        "crash_level3_cash_ratio": _crash_level3_cash(state) / end_value,
        "tactical_cash_ratio": tactical_cash / end_value,
        "total_cash_ratio": total_cash / end_value,
        "crypto_exposure": crypto_value / end_value,
        "BTC_allocation": allocations["BTC"],
        "ETH_allocation": allocations["ETH"],
        "BTC_close": prices_close["BTC"],
        "ETH_close": prices_close["ETH"],
        "BTC_signal_close": row.get("BTC_daily_close"),
        "sma10": row.get("sma10"),
        "sma20": row.get("sma20"),
        "sma50": row.get("sma50"),
        "sma200": row.get("sma200"),
        "bb_lower": row.get("bb_lower"),
        "ahr999": row.get("ahr999_fixed_arithmetic"),
        "bear_risk": np.nan,
        "ai_enabled": False,
        "ai_intervention": "NONE",
        "macro_state_previous": before_state if scenario.use_fsm else "N/A",
        "macro_state": state.macro_state if scenario.use_fsm else "N/A",
        "sell_stage": state.stage if scenario.use_fsm else 0,
        "active_target": state.active_target if scenario.use_fsm else np.nan,
        "cycle_id": state.active_cycle_id if scenario.use_fsm else 0,
        "macro_cooldown_days": state.macro_cooldown_days,
        "accumulation_lock": _is_lock_active(state, pd.Timestamp(row["open_time"])),
        "crash_level1_active": state.crash_level1_days_remaining > 0,
        "crash_level2_active": state.crash_level2_fired and state.crash_episode_active,
        "crash_level3_used": state.crash_level3_used,
        "crash_episode_id": state.crash_episode_id,
        "requal_candidate_active": state.requal_candidate_active,
        "macro_bear_invalidated": state.macro_bear_invalidated,
        "theoretical_dca": 0.0 if scenario.model == "H0" else float(rules["external_contribution_per_4h"]),
        "protected_dca": 0.0 if scenario.model == "H0" else float(rules["external_contribution_per_4h"]),
        "committed_dca": committed,
        "executed_dca": executed,
        "dca_alloc_BTC": dca_alloc["BTC"],
        "dca_alloc_ETH": dca_alloc["ETH"],
        "target_basket_return": basket_return,
        "cash_drag_increment": (total_cash / end_value) * basket_return,
        "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
        "daily_floor_breach_reason": (
            "market_move_after_tactical_sell"
            if scenario.use_fsm and crypto_value / end_value < scenario.hard_floor - 1e-10
            else "none"
        ),
    }


def run_initial_only(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: V31Scenario,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.4 bars")
    state = V34State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    history: list[dict[str, Any]] = []
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
            reason="FRESH_2020_START_H0",
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
            state,
            row,
            scenario,
            prices_close,
            end_value,
            unit_nav,
            unit_nav / peak_nav - 1.0,
            twr_return,
            0.0,
            1,
            0.0,
            0.0,
            {asset: 0.0 for asset in ASSETS_V31},
            previous_closes,
            rules,
            "N/A",
        ))
        previous_value = end_value
        previous_closes = prices_close
    history_frame = pd.DataFrame(history)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history_frame, trade_frame, scenario=scenario, counters={}, rules=rules)
    return V31BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history_frame,
        trades=trade_frame,
        signals=pd.DataFrame(),
        transitions=pd.DataFrame(),
        cycles=pd.DataFrame(),
        temporary_lots=pd.DataFrame(),
        cash_events=pd.DataFrame(),
        counters={},
    )


def run_v34_backtest(
    frame: pd.DataFrame,
    base_rules: dict[str, Any],
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
) -> V31BacktestResult:
    if frame.empty:
        raise ValueError("No formal V3.4 bars")
    state = V34State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    counters = {key: 0 for key in [
        "stage1_count",
        "stage2_count",
        "stage3_count",
        "stage4_count",
        "aborted_distribution_count",
        "value_buyback_count",
        "right_buyback_count",
        "new_bull_count",
        "new_bull_redeploy_count",
        "crash_level1_count",
        "crash_level2_count",
        "crash_level3_count",
        "crash_level3_recovery_count",
        "macro_bull_candidate_count",
        "macro_bear_invalidated_count",
        "macro_bull_requalification_count",
        "final_cash_sweep_count",
        "cash_reset_block_count",
        "drift_sell_count",
        "dca_cash_shortfall_count",
    ]}
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state,
            asset,
            float(base_rules["initial_allocation_usd"][asset]),
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
        before_state = state.macro_state
        before_stage = state.stage
        before_target = state.active_target
        before_exposure = _exposure(state, prices_open)
        before_l3_cash = _crash_level3_cash(state)
        actions: list[str] = []
        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, base_rules)
            _run_v34_macro_fsm(
                state,
                row,
                prices_open,
                base_rules,
                rules,
                scenario,
                trades,
                transitions,
                cycles,
                cash_events,
                counters,
                actions,
            )
            _process_crash_v34(
                state,
                row,
                prices_open,
                base_rules,
                rules,
                scenario,
                trades,
                cash_events,
                counters,
                actions,
            )
            _process_crash_level3_recovery(
                state,
                row,
                prices_open,
                base_rules,
                rules,
                scenario,
                trades,
                counters,
                actions,
            )
            _process_legacy_temp_unwind(
                state, row, prices_open, base_rules, scenario, trades, actions
            )
            _process_drift(
                state, row, prices_open, base_rules, scenario, trades, counters, actions
            )
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        arow = a_history.loc[timestamp]
        committed = float(arow["committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.4 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(arow[f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
        for asset in ASSETS_V31:
            state.pending[asset] += dca_alloc[asset]
        executed = 0.0
        for asset in ASSETS_V31:
            budget = a_dca.get((timestamp, asset), 0.0)
            if budget > 0:
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
                    trades=trades,
                    signal_date=row.get("signal_date"),
                    reason="FIXED_USD_2_PER_4H",
                )
        if abs(executed - float(arow["executed_dca"])) > 1e-8:
            raise AssertionError("Executed V3.4 DCA differs from Model A")

        end_value = _portfolio_value(state, prices_close)
        denominator = previous_value + external_flow
        twr_return = end_value / denominator - 1.0 if denominator > 0 else 0.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        histories.append(_history_row(
            state,
            row,
            scenario,
            prices_close,
            end_value,
            unit_nav,
            unit_nav / peak_nav - 1.0,
            twr_return,
            external_flow,
            elapsed,
            committed,
            executed,
            dca_alloc,
            previous_closes,
            base_rules,
            before_state,
        ))
        if is_new_signal:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            signals.append({
                "strategy": scenario.name,
                "model": scenario.model,
                "signal_date": row.get("signal_date"),
                "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp,
                "btc_close": row.get("BTC_daily_close"),
                "sma10": row.get("sma10"),
                "sma20": row.get("sma20"),
                "sma50": row.get("sma50"),
                "sma200": row.get("sma200"),
                "bb_lower": row.get("bb_lower"),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "state_before": before_state,
                "state_after": state.macro_state,
                "stage_before": before_stage,
                "stage_after": state.stage,
                "active_target_before": before_target,
                "active_target_after": state.active_target,
                "crypto_exposure_before": before_exposure,
                "crypto_exposure_after": _exposure(state, prices_open),
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
                "close_above_sma50_5d": row.get("close_above_sma50_5d"),
                "sma20_up_5d": row.get("sma20_up_5d"),
                "no_new_20d_low": row.get("no_new_20d_low"),
                "deep_bear_dwell_days": (
                    state.signal_index - state.deep_bear_entry_signal_index
                    if before_state == "DEEP_BEAR" or state.macro_state == "DEEP_BEAR"
                    else 0
                ),
                "crash_level1_raw": row.get("crash_level1_raw"),
                "crash_level2_market_raw": row.get("crash_level2_market_raw"),
                "crash_level3_price_raw": row.get("crash_level3_price_raw"),
                "crash_recovery_market_raw": row.get("crash_recovery_market_raw"),
                "btc_peak_to_close_dd_7d": row.get("btc_peak_to_close_dd_7d"),
                "btc_peak_to_close_dd_10d": row.get("btc_peak_to_close_dd_10d"),
                "crash_episode_id": state.crash_episode_id,
                "crash_level2_active": state.crash_level2_fired and state.crash_episode_active,
                "crash_level3_used": state.crash_level3_used,
                "macro_bull_requalification_market_candidate": row.get(
                    "macro_bull_requalification_market_candidate"
                ),
                "macro_bull_candidate_confirmation_market": row.get(
                    "macro_bull_candidate_confirmation_market"
                ),
                "macro_bull_new_bull_confirmation_market": row.get(
                    "macro_bull_new_bull_confirmation_market"
                ),
                "requal_candidate_active": state.requal_candidate_active,
                "requal_candidate_following_days": state.requal_candidate_following_days,
                "macro_bear_invalidated": state.macro_bear_invalidated,
                "requal_new_bull_following_days": state.requal_new_bull_following_days,
                "right_50_confirmed": row.get("right_50_confirmed"),
                "right_60_confirmed": row.get("right_60_confirmed"),
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
            item["status"] = (
                "CLOSING_NEW_BULL_AT_END"
                if item.get("status") == "CLOSING_NEW_BULL"
                else "OPEN_AT_END"
            )
    history_frame = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(
        history_frame, trade_frame, scenario=scenario, counters=counters, rules=base_rules
    )
    return V31BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history_frame,
        trades=trade_frame,
        signals=pd.DataFrame(signals),
        transitions=pd.DataFrame(transitions),
        cycles=pd.DataFrame(cycles),
        temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events),
        counters=counters,
    )


__all__ = [
    "V34State",
    "run_initial_only",
    "run_v34_backtest",
    "_cash_reset_status",
    "_crash_level3_cash",
    "_final_cash_sweep",
]
