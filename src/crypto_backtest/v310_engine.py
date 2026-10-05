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
    _cycle,
    _days_since,
    _exposure,
    _is_lock_active,
    _pending_cash,
    _portfolio_value,
    _process_crash,
    _process_drift,
    _process_temp_unwind,
    _run_macro_fsm,
    _stage_sell,
    _temp_cash,
    _update_temp_lots,
    _values,
)
from .v39_engine import _new_candidate, _resolve_candidate


@dataclass
class V310BacktestResult:
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
    stage3_candidates: pd.DataFrame


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _shadow_signal_map(shadow: V31BacktestResult) -> dict[pd.Timestamp, dict[str, Any]]:
    return {
        pd.Timestamp(row["execution_4h_open"]): row.to_dict()
        for _, row in shadow.signals.iterrows()
    }


def _force_v31_stage4(
    state: V31State,
    row: pd.Series,
    prices: dict[str, float],
    rules: dict[str, Any],
    scenario: V31Scenario,
    trades: list[dict[str, Any]],
    transitions: list[dict[str, Any]],
    cycles: list[dict[str, Any]],
    counters: dict[str, Any],
    actions: list[str],
) -> None:
    """Execute the frozen V3.1 Stage4 action when Q is still held in EARLY_BEAR."""
    transitions.append({
        "strategy": row.get("strategy_name", ""),
        "signal_date": row.get("signal_date"),
        "execution_4h_open": row.get("open_time"),
        "from_state": state.macro_state,
        "to_state": "DEEP_BEAR",
        "reason": "V31_SHADOW_STAGE4_PRIORITY",
        "cycle_id": state.active_cycle_id,
        "ai_intervention": "NONE",
    })
    state.macro_state = "DEEP_BEAR"
    state.regime_days = 0
    _stage_sell(
        state, 4, row, prices, rules, scenario, trades, cycles, actions,
        reason="V31_SHADOW_STAGE4_PRIORITY", temporary=False,
    )
    counters["stage4_count"] += 1
    counters["stage4_override_count"] += 1


def _candidate_condition(row: pd.Series) -> bool:
    return bool(
        float(row["BTC_daily_close"]) < float(row["sma50"])
        and float(row["sma20"]) < float(row["sma50"])
    )


def _reject_candidate(
    candidate: dict[str, Any],
    row: pd.Series,
    reason: str,
    audit: list[dict[str, Any]],
    counters: dict[str, Any],
) -> None:
    _resolve_candidate(candidate, outcome="REJECTED", row=row, reason=reason)
    candidate["resolution_date"] = row.get("signal_date")
    audit.append(candidate)
    counters["stage3_candidate_rejected_count"] += 1
    if reason == "SMA200_HARD_FAILURE":
        counters["stage3_candidate_hard_failure_count"] += 1
    elif reason == "STAGE4_PRIORITY":
        counters["stage3_candidate_stage4_override_count"] += 1
    elif reason == "CRASH_PRIORITY":
        counters["stage3_candidate_crash_override_count"] += 1


def run_v310_backtest(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
    shadow_v31: V31BacktestResult,
) -> V310BacktestResult:
    """Run V3.10 with exactly one direct change: eligible Stage3 confirmation."""
    if frame.empty:
        raise ValueError("No formal V3.10 bars")
    if scenario.model != "Q":
        raise ValueError("V3.10 engine only accepts model Q")

    state = V31State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    candidate_rows: list[dict[str, Any]] = []
    counters = {key: 0 for key in [
        "stage1_count", "stage2_count", "stage3_count", "stage4_count",
        "aborted_distribution_count", "value_buyback_count", "right_buyback_count",
        "new_bull_count", "new_bull_redeploy_count", "crash_level1_count",
        "crash_level2_count", "drift_sell_count", "ai_stage4_acceleration_count",
        "ai_buyback_cap_count", "dca_cash_shortfall_count",
        "stage3_candidate_count", "stage3_candidate_rejected_count",
        "stage3_candidate_confirmed_count", "stage3_candidate_hard_failure_count",
        "stage3_candidate_stage4_override_count", "stage3_candidate_crash_override_count",
        "stage4_override_count",
    ]}

    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(rules["initial_allocation_usd"][asset]),
            first_prices[asset], first_prices, timestamp=pd.Timestamp(first["open_time"]),
            scenario=scenario, action="INITIAL_ALLOCATION", ledger="normal",
            trades=trades, signal_date=first.get("signal_date"), reason="FRESH_ROLLING_START",
        )

    a_history = model_a.history.set_index("timestamp")
    dca = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA")].copy()
    a_dca = {
        (pd.Timestamp(timestamp), str(asset)): float(-group["cash_change_usd"].sum())
        for (timestamp, asset), group in dca.groupby(["timestamp", "asset"])
    }
    shadow_map = _shadow_signal_map(shadow_v31)

    stage3_eligible = False
    eligibility_started_at: Any = pd.NaT
    sma200_failure_streak = 0
    candidate: dict[str, Any] | None = None
    next_candidate_id = 1
    last_causal_candidate_id: Any = ""
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
        external_flow = float(rules["external_contribution_per_4h"]) * elapsed
        state.normal_cash += external_flow
        prices_open = {asset: float(row[f"{asset}_open"]) for asset in ASSETS_V31}
        prices_close = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}

        is_new_signal = pd.notna(row.get("signal_date")) and row.get("signal_date") != state.last_signal_date
        before_state, before_stage, before_target = state.macro_state, state.stage, state.active_target
        before_exposure = _exposure(state, prices_open)
        actions: list[str] = []
        ai_intervention, ai_reason = "NONE", ""
        shadow_row: dict[str, Any] = {}
        direct_difference_candidate_id: Any = ""

        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, rules)
            shadow_row = shadow_map.get(timestamp, {})
            shadow_actions = str(shadow_row.get("actions", ""))

            if stage3_eligible and float(row["BTC_daily_close"]) < float(row["sma200"]):
                sma200_failure_streak += 1
            else:
                sma200_failure_streak = 0

            if stage3_eligible and sma200_failure_streak >= 3:
                stage3_eligible = False
                actions.append("STAGE3_ELIGIBILITY_EXIT:SMA200_HARD_FAILURE_3_CLOSES")
                if candidate is not None:
                    last_causal_candidate_id = candidate["candidate_id"]
                    _reject_candidate(
                        candidate, row, "SMA200_HARD_FAILURE", candidate_rows, counters,
                    )
                    candidate = None

            force_stage4 = bool(stage3_eligible and "STAGE4_SELL:" in shadow_actions)
            if force_stage4:
                stage3_eligible = False
                if candidate is not None:
                    last_causal_candidate_id = candidate["candidate_id"]
                    _reject_candidate(candidate, row, "STAGE4_PRIORITY", candidate_rows, counters)
                    candidate = None
                _force_v31_stage4(
                    state, row, prices_open, rules, scenario, trades,
                    transitions, cycles, counters, actions,
                )
                actions.append("STAGE3_ELIGIBILITY_EXIT:V31_STAGE4_PRIORITY")
            else:
                row_for_fsm = row.copy()
                stage3_raw = _truth(row.get("stage3_confirmed"))
                if stage3_eligible and state.macro_state == "EARLY_BEAR" and stage3_raw:
                    condition = _candidate_condition(row)
                    if candidate is None:
                        candidate = _new_candidate(row, shadow_row, condition)
                        candidate.update({
                            "candidate_id": next_candidate_id,
                            "eligibility_started_at": eligibility_started_at,
                            "B_stage3_execution_date": (
                                row.get("signal_date")
                                if "STAGE3_SELL:" in shadow_actions else pd.NaT
                            ),
                            "shadow_v31_stage3_executed": "STAGE3_SELL:" in shadow_actions,
                            "resolution_date": pd.NaT,
                        })
                        next_candidate_id += 1
                        counters["stage3_candidate_count"] += 1
                        direct_difference_candidate_id = candidate["candidate_id"]
                        last_causal_candidate_id = candidate["candidate_id"]
                        actions.append(f"STAGE3_REENTRY_CANDIDATE:{candidate['candidate_id']}")
                    elif condition:
                        slot = int(candidate["confirmation_count"]) + 1
                        if slot <= 3:
                            candidate["confirmation_count"] = slot
                            candidate[f"confirmation_close_{slot}"] = float(row["BTC_daily_close"])
                            candidate[f"confirmation_date_{slot}"] = row.get("signal_date")
                    if not condition:
                        _reject_candidate(
                            candidate, row, "THREE_CLOSE_SEQUENCE_BROKEN", candidate_rows, counters,
                        )
                        candidate = None
                        row_for_fsm["stage3_confirmed"] = False
                    elif int(candidate["confirmation_count"]) >= 3:
                        _resolve_candidate(
                            candidate, outcome="CONFIRMED", row=row,
                            reason="THREE_COMPLETED_CLOSES",
                        )
                        candidate["resolution_date"] = row.get("signal_date")
                        candidate_rows.append(candidate)
                        counters["stage3_candidate_confirmed_count"] += 1
                        last_causal_candidate_id = candidate["candidate_id"]
                        candidate = None
                        stage3_eligible = False
                        row_for_fsm["stage3_confirmed"] = True
                        actions.append("STAGE3_REENTRY_CONFIRMED")
                    else:
                        row_for_fsm["stage3_confirmed"] = False
                        actions.append("STAGE3_HELD_FOR_3_CLOSE_CONFIRMATION")
                elif stage3_eligible and candidate is not None:
                    condition = _candidate_condition(row)
                    if condition:
                        slot = int(candidate["confirmation_count"]) + 1
                        if slot <= 3:
                            candidate["confirmation_count"] = slot
                            candidate[f"confirmation_close_{slot}"] = float(row["BTC_daily_close"])
                            candidate[f"confirmation_date_{slot}"] = row.get("signal_date")
                    else:
                        _reject_candidate(
                            candidate, row, "THREE_CLOSE_SEQUENCE_BROKEN", candidate_rows, counters,
                        )
                        candidate = None
                    if candidate is not None and int(candidate["confirmation_count"]) >= 3:
                        _resolve_candidate(
                            candidate, outcome="CONFIRMED", row=row,
                            reason="THREE_COMPLETED_CLOSES",
                        )
                        candidate["resolution_date"] = row.get("signal_date")
                        candidate_rows.append(candidate)
                        counters["stage3_candidate_confirmed_count"] += 1
                        last_causal_candidate_id = candidate["candidate_id"]
                        candidate = None
                        stage3_eligible = False
                        row_for_fsm["stage3_confirmed"] = True
                        actions.append("STAGE3_REENTRY_CONFIRMED")
                    else:
                        row_for_fsm["stage3_confirmed"] = False

                ai_intervention, ai_reason = _run_macro_fsm(
                    state, row_for_fsm, prices_open, rules, scenario, trades,
                    transitions, cycles, cash_events, counters, actions,
                )

            _process_crash(
                state, row, prices_open, rules, scenario, trades,
                cash_events, counters, actions,
            )
            crash_action = any(
                item.startswith("CRASH_L1:") or item.startswith("CRASH_L2:")
                for item in actions
            )
            if crash_action and stage3_eligible:
                stage3_eligible = False
                actions.append("STAGE3_ELIGIBILITY_EXIT:CRASH_PRIORITY")
                if candidate is not None:
                    last_causal_candidate_id = candidate["candidate_id"]
                    _reject_candidate(candidate, row, "CRASH_PRIORITY", candidate_rows, counters)
                    candidate = None

            if "NEW_BULL_CONFIRMED" in actions:
                stage3_eligible = True
                eligibility_started_at = row.get("signal_date")
                sma200_failure_streak = 0
                actions.append("STAGE3_ELIGIBILITY_ACTIVATED")

            _process_temp_unwind(state, row, prices_open, rules, scenario, trades, actions)
            _process_drift(state, row, prices_open, rules, scenario, trades, counters, actions)
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        committed = float(a_history.loc[timestamp, "committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.10 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {
            asset: float(a_history.loc[timestamp, f"dca_alloc_{asset}"])
            for asset in ASSETS_V31
        }
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
        if abs(executed - float(a_history.loc[timestamp, "executed_dca"])) > 1e-8:
            raise AssertionError("V3.10 executed DCA differs from Model A")

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
            "timestamp": timestamp,
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
            "BTC_signal_close": row.get("BTC_daily_close"),
            "sma10": row.get("sma10"),
            "sma20": row.get("sma20"),
            "sma50": row.get("sma50"),
            "sma200": row.get("sma200"),
            "ahr999": row.get("ahr999_fixed_arithmetic"),
            "bear_risk": np.nan,
            "ai_enabled": False,
            "ai_intervention": "NONE",
            "macro_state_previous": before_state,
            "macro_state": state.macro_state,
            "sell_stage": state.stage,
            "active_target": state.active_target,
            "cycle_id": state.active_cycle_id,
            "macro_cooldown_days": state.macro_cooldown_days,
            "accumulation_lock": _is_lock_active(state, timestamp),
            "crash_level1_active": state.crash_level1_days_remaining > 0,
            "stage3_confirmation_eligible": stage3_eligible,
            "stage3_eligibility_started_at": eligibility_started_at,
            "stage3_candidate_active": candidate is not None,
            "stage3_candidate_id": candidate["candidate_id"] if candidate else "",
            "stage3_confirmation_count": int(candidate["confirmation_count"]) if candidate else 0,
            "sma200_failure_streak": sma200_failure_streak,
            "causal_parent_stage3_candidate_id": last_causal_candidate_id,
            "theoretical_dca": float(rules["external_contribution_per_4h"]),
            "protected_dca": float(rules["external_contribution_per_4h"]),
            "committed_dca": committed,
            "executed_dca": executed,
            "dca_alloc_BTC": dca_alloc["BTC"],
            "dca_alloc_ETH": dca_alloc["ETH"],
            "target_basket_return": basket_return,
            "cash_drag_increment": (total_cash / end_value) * basket_return,
            "tactical_cash_drag_increment": (tactical_cash / end_value) * basket_return,
            "daily_floor_breach_reason": (
                "market_move_after_tactical_sell"
                if crypto_value / end_value < scenario.hard_floor - 1e-10 else "none"
            ),
        })

        if is_new_signal:
            days_since_low = _days_since(pd.Timestamp(row["signal_date"]), state.bear_low_date)
            signals.append({
                "strategy": scenario.name,
                "model": scenario.model,
                "signal_date": row.get("signal_date"),
                "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp,
                "btc_close": row.get("BTC_daily_close"),
                "eth_execution_price": prices_open["ETH"],
                "sma10": row.get("sma10"),
                "sma20": row.get("sma20"),
                "sma50": row.get("sma50"),
                "sma200": row.get("sma200"),
                "sma200_slope_20d": row.get("feature_sma200_slope", np.nan),
                "ahr999": row.get("ahr999_fixed_arithmetic"),
                "bear_risk": np.nan,
                "ai_enabled": False,
                "ai_intervention": ai_intervention,
                "ai_intervention_reason": ai_reason,
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
                "actions": "|".join(actions),
                "stage3_confirmation_eligible": stage3_eligible,
                "stage3_candidate_active": candidate is not None,
                "stage3_candidate_id": candidate["candidate_id"] if candidate else "",
                "stage3_confirmation_count": int(candidate["confirmation_count"]) if candidate else 0,
                "sma200_failure_streak": sma200_failure_streak,
                "direct_difference_candidate_id": direct_difference_candidate_id,
                "causal_parent_stage3_candidate_id": last_causal_candidate_id,
                "shadow_v31_state_before": shadow_row.get("state_before", ""),
                "shadow_v31_state_after": shadow_row.get("state_after", ""),
                "shadow_v31_actions": shadow_row.get("actions", ""),
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

    if candidate is not None:
        candidate["confirmed_or_rejected"] = "OPEN_AT_END"
        candidate["resolution_reason"] = "DATA_END"
        candidate["resolution_date"] = frame.iloc[-1].get("signal_date")
        candidate_rows.append(candidate)
    final_signal_date = frame.iloc[-1].get("signal_date")
    for item in cycles:
        if pd.isna(item["end"]):
            item["end"] = final_signal_date
            item["status"] = "OPEN_AT_END"

    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(
        history, trade_frame, scenario=scenario, counters=counters, rules=rules,
    )
    return V310BacktestResult(
        scenario=scenario,
        summary=summary,
        history=history,
        trades=trade_frame,
        signals=pd.DataFrame(signals),
        transitions=pd.DataFrame(transitions),
        cycles=pd.DataFrame(cycles),
        temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events),
        counters=counters,
        stage3_candidates=pd.DataFrame(candidate_rows),
    )


__all__ = ["V310BacktestResult", "run_v310_backtest"]
