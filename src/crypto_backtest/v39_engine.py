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
    _commit_model_a_dca,
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


@dataclass
class V39BacktestResult:
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
    blocked_sells: pd.DataFrame
    bear_reentry_audit: pd.DataFrame


def _truth(value: Any) -> bool:
    return bool(value) if pd.notna(value) else False


def _shadow_signal_map(shadow: V31BacktestResult) -> dict[pd.Timestamp, dict[str, Any]]:
    return {
        pd.Timestamp(row["execution_4h_open"]): row.to_dict()
        for _, row in shadow.signals.iterrows()
    }


def _healthy_bull(row: pd.Series, shadow_row: dict[str, Any]) -> bool:
    shadow_actions = str(shadow_row.get("actions", ""))
    no_crash = "CRASH_L1:" not in shadow_actions and "CRASH_L2:" not in shadow_actions
    return bool(
        float(row["BTC_daily_close"]) > float(row["sma200"])
        and _truth(row.get("sma200_slope_up"))
        and float(row["sma50"]) > float(row["sma200"])
        and float(row["BTC_daily_close"]) > float(row["sma50"])
        and no_crash
    )


def _new_candidate(
    row: pd.Series, shadow_row: dict[str, Any], condition: bool,
) -> dict[str, Any]:
    candidate = {
        "candidate_date": row.get("signal_date"),
        "candidate_execution_date": row.get("open_time"),
        "original_v31_state": shadow_row.get("state_before", ""),
        "candidate_reason": "ORIGINAL_V31_STAGE3_CONFIRMED",
        "close_vs_sma50": float(row["BTC_daily_close"]) / float(row["sma50"]) - 1.0,
        "sma20_vs_sma50": float(row["sma20"]) / float(row["sma50"]) - 1.0,
        "close_vs_sma200": float(row["BTC_daily_close"]) / float(row["sma200"]) - 1.0,
        "confirmation_close_1": np.nan,
        "confirmation_close_2": np.nan,
        "confirmation_close_3": np.nan,
        "confirmation_date_1": pd.NaT,
        "confirmation_date_2": pd.NaT,
        "confirmation_date_3": pd.NaT,
        "confirmed_or_rejected": "PENDING",
        "final_reentry_date": pd.NaT,
        "days_delayed_vs_v31": np.nan,
        "resolution_reason": "",
        "confirmation_count": 0,
    }
    if condition:
        candidate["confirmation_count"] = 1
        candidate["confirmation_close_1"] = float(row["BTC_daily_close"])
        candidate["confirmation_date_1"] = row.get("signal_date")
    return candidate


def _resolve_candidate(
    candidate: dict[str, Any], *, outcome: str, row: pd.Series, reason: str,
) -> None:
    candidate["confirmed_or_rejected"] = outcome
    candidate["resolution_reason"] = reason
    if outcome == "CONFIRMED":
        candidate["final_reentry_date"] = row.get("signal_date")
        candidate["days_delayed_vs_v31"] = (
            pd.Timestamp(row.get("signal_date")) - pd.Timestamp(candidate["candidate_date"])
        ).total_seconds() / 86_400.0


def _force_shadow_stage4(
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
    before = state.macro_state
    transitions.append({
        "strategy": row.get("strategy_name", ""),
        "signal_date": row.get("signal_date"),
        "execution_4h_open": row.get("open_time"),
        "from_state": before,
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
    counters["shadow_stage4_priority_count"] += 1


def run_v39_backtest(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    scenario: V31Scenario,
    *,
    model_a: V31BacktestResult,
    shadow_v31: V31BacktestResult,
) -> V39BacktestResult:
    """Run the one-change V3.9 challenger on completed daily signals.

    The V3.1 order, cash-ledger, crash, AHR, redeploy and DCA helpers are used
    directly. Only the persistence latch, Stage-3 confirmation and guarded
    drift interception are added here.
    """
    if frame.empty:
        raise ValueError("No formal V3.9 bars")
    if scenario.model != "P":
        raise ValueError("V3.9 engine only accepts model P")

    state = V31State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    transitions: list[dict[str, Any]] = []
    cycles: list[dict[str, Any]] = []
    cash_events: list[dict[str, Any]] = []
    blocked_sells: list[dict[str, Any]] = []
    reentry_rows: list[dict[str, Any]] = []
    counters = {key: 0 for key in [
        "stage1_count", "stage2_count", "stage3_count", "stage4_count",
        "aborted_distribution_count", "value_buyback_count", "right_buyback_count",
        "new_bull_count", "new_bull_redeploy_count", "crash_level1_count",
        "crash_level2_count", "drift_sell_count", "ai_stage4_acceleration_count",
        "ai_buyback_cap_count", "dca_cash_shortfall_count",
        "blocked_drift_sell_count", "bear_reentry_candidate_count",
        "bear_reentry_confirmed_count", "bear_reentry_rejected_count",
        "shadow_stage4_priority_count", "sma200_hard_failure_count",
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
        (pd.Timestamp(ts), str(asset)): float(-group["cash_change_usd"].sum())
        for (ts, asset), group in dca.groupby(["timestamp", "asset"])
    }
    shadow_map = _shadow_signal_map(shadow_v31)

    persistence_active = False
    persistence_started_at: Any = pd.NaT
    sma200_failure_streak = 0
    candidate: dict[str, Any] | None = None
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
        healthy = False
        guard_on_before = False
        shadow_row: dict[str, Any] = {}

        if is_new_signal:
            state.signal_index += 1
            state.regime_days += 1
            _update_temp_lots(state, row, rules)
            shadow_row = shadow_map.get(timestamp, {})
            shadow_actions = str(shadow_row.get("actions", ""))
            healthy = _healthy_bull(row, shadow_row)
            guard_on_before = bool(persistence_active and healthy)

            if persistence_active and float(row["BTC_daily_close"]) < float(row["sma200"]):
                sma200_failure_streak += 1
            else:
                sma200_failure_streak = 0
            if persistence_active and sma200_failure_streak >= 3:
                persistence_active = False
                counters["sma200_hard_failure_count"] += 1
                actions.append("BULL_PERSISTENCE_EXIT:SMA200_HARD_FAILURE_3_CLOSES")
                if candidate is not None:
                    _resolve_candidate(candidate, outcome="REJECTED", row=row, reason="SMA200_HARD_FAILURE")
                    counters["bear_reentry_rejected_count"] += 1
                    reentry_rows.append(candidate)
                    candidate = None

            force_stage4 = bool(persistence_active and "STAGE4_SELL:" in shadow_actions)
            if force_stage4:
                persistence_active = False
                if candidate is not None:
                    _resolve_candidate(candidate, outcome="REJECTED", row=row, reason="STAGE4_PRIORITY")
                    counters["bear_reentry_rejected_count"] += 1
                    reentry_rows.append(candidate)
                    candidate = None
                _force_shadow_stage4(
                    state, row, prices_open, rules, scenario, trades,
                    transitions, cycles, counters, actions,
                )
                actions.append("BULL_PERSISTENCE_EXIT:V31_STAGE4_PRIORITY")
            else:
                row_for_fsm = row.copy()
                stage3_raw = _truth(row.get("stage3_confirmed"))
                if persistence_active and state.macro_state == "EARLY_BEAR" and stage3_raw:
                    condition = bool(
                        float(row["BTC_daily_close"]) < float(row["sma50"])
                        and float(row["sma20"]) < float(row["sma50"])
                    )
                    if candidate is None:
                        candidate = _new_candidate(row, shadow_row, condition)
                        counters["bear_reentry_candidate_count"] += 1
                        actions.append("BEAR_REENTRY_CANDIDATE")
                    elif condition:
                        slot = int(candidate["confirmation_count"]) + 1
                        if slot <= 3:
                            candidate["confirmation_count"] = slot
                            candidate[f"confirmation_close_{slot}"] = float(row["BTC_daily_close"])
                            candidate[f"confirmation_date_{slot}"] = row.get("signal_date")
                    if not condition:
                        _resolve_candidate(candidate, outcome="REJECTED", row=row, reason="THREE_CLOSE_SEQUENCE_BROKEN")
                        counters["bear_reentry_rejected_count"] += 1
                        reentry_rows.append(candidate)
                        candidate = None
                        row_for_fsm["stage3_confirmed"] = False
                    elif int(candidate["confirmation_count"]) >= 3:
                        _resolve_candidate(candidate, outcome="CONFIRMED", row=row, reason="THREE_COMPLETED_CLOSES")
                        counters["bear_reentry_confirmed_count"] += 1
                        reentry_rows.append(candidate)
                        candidate = None
                        persistence_active = False
                        row_for_fsm["stage3_confirmed"] = True
                        actions.append("BEAR_REENTRY_CONFIRMED")
                    else:
                        row_for_fsm["stage3_confirmed"] = False
                        actions.append("STAGE3_HELD_FOR_3_CLOSE_CONFIRMATION")
                elif persistence_active and candidate is not None:
                    condition = bool(
                        float(row["BTC_daily_close"]) < float(row["sma50"])
                        and float(row["sma20"]) < float(row["sma50"])
                    )
                    if condition:
                        slot = int(candidate["confirmation_count"]) + 1
                        if slot <= 3:
                            candidate["confirmation_count"] = slot
                            candidate[f"confirmation_close_{slot}"] = float(row["BTC_daily_close"])
                            candidate[f"confirmation_date_{slot}"] = row.get("signal_date")
                    else:
                        _resolve_candidate(candidate, outcome="REJECTED", row=row, reason="THREE_CLOSE_SEQUENCE_BROKEN")
                        counters["bear_reentry_rejected_count"] += 1
                        reentry_rows.append(candidate)
                        candidate = None
                    if candidate is not None and int(candidate["confirmation_count"]) >= 3:
                        _resolve_candidate(candidate, outcome="CONFIRMED", row=row, reason="THREE_COMPLETED_CLOSES")
                        counters["bear_reentry_confirmed_count"] += 1
                        reentry_rows.append(candidate)
                        candidate = None
                        persistence_active = False
                        row_for_fsm["stage3_confirmed"] = True
                        actions.append("BEAR_REENTRY_CONFIRMED")
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
            crash_action = any(item.startswith("CRASH_L1:") or item.startswith("CRASH_L2:") for item in actions)
            if crash_action and persistence_active:
                persistence_active = False
                actions.append("BULL_PERSISTENCE_EXIT:CRASH_PRIORITY")
                if candidate is not None:
                    _resolve_candidate(candidate, outcome="REJECTED", row=row, reason="CRASH_PRIORITY")
                    counters["bear_reentry_rejected_count"] += 1
                    reentry_rows.append(candidate)
                    candidate = None

            if "NEW_BULL_CONFIRMED" in actions:
                persistence_active = True
                persistence_started_at = row.get("signal_date")
                sma200_failure_streak = 0
                actions.append("BULL_PERSISTENCE_ACTIVATED")

            _process_temp_unwind(state, row, prices_open, rules, scenario, trades, actions)
            guard_on_after_macro = bool(persistence_active and healthy)
            shadow_drift = "DRIFT_SELL:" in shadow_actions
            if guard_on_after_macro:
                if shadow_drift:
                    blocked_sells.append({
                        "timestamp": timestamp,
                        "signal_date": row.get("signal_date"),
                        "original_v31_signal_type": "DRIFT_SELL",
                        "original_v31_action": shadow_actions,
                        "original_target": shadow_row.get("active_target_after", np.nan),
                        "btc_close": row.get("BTC_daily_close"),
                        "sma20": row.get("sma20"),
                        "sma50": row.get("sma50"),
                        "sma200": row.get("sma200"),
                        "sma200_slope_20d": row.get("feature_sma200_slope", np.nan),
                        "healthy_bull_structure": healthy,
                        "bull_persistence_active": persistence_active,
                        "blocked_or_executed": "BLOCKED",
                        "reason": "BULL_PERSISTENCE_BLOCKED_DRIFT_SELL",
                        "actual_exposure_before": _exposure(state, prices_open),
                        "actual_exposure_after": _exposure(state, prices_open),
                    })
                    counters["blocked_drift_sell_count"] += 1
                    actions.append("BULL_PERSISTENCE_BLOCKED_DRIFT_SELL")
            else:
                _process_drift(state, row, prices_open, rules, scenario, trades, counters, actions)
            if state.macro_cooldown_days > 0:
                state.macro_cooldown_days -= 1
            state.last_signal_date = row.get("signal_date")

        committed = float(a_history.loc[timestamp, "committed_dca"])
        if state.normal_cash + 1e-9 < committed:
            counters["dca_cash_shortfall_count"] += 1
            raise AssertionError("V3.9 cannot replay Model A DCA commitment")
        state.normal_cash -= committed
        dca_alloc = {asset: float(a_history.loc[timestamp, f"dca_alloc_{asset}"]) for asset in ASSETS_V31}
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
            raise AssertionError("V3.9 executed DCA differs from Model A")

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
        current_guard = bool(persistence_active and healthy) if is_new_signal else (
            bool(histories[-1]["bull_persistence_guard"]) if histories else False
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
            "cycle_id": state.active_cycle_id,
            "macro_cooldown_days": state.macro_cooldown_days,
            "accumulation_lock": _is_lock_active(state, timestamp),
            "crash_level1_active": state.crash_level1_days_remaining > 0,
            "bull_persistence_active": persistence_active,
            "bull_persistence_started_at": persistence_started_at,
            "healthy_bull_structure": healthy if is_new_signal else (
                histories[-1]["healthy_bull_structure"] if histories else False
            ),
            "bull_persistence_guard": current_guard,
            "bear_reentry_candidate_active": candidate is not None,
            "bear_reentry_confirmation_count": int(candidate["confirmation_count"]) if candidate else 0,
            "sma200_failure_streak": sma200_failure_streak,
            "theoretical_dca": float(rules["external_contribution_per_4h"]),
            "protected_dca": float(rules["external_contribution_per_4h"]),
            "committed_dca": committed, "executed_dca": executed,
            "dca_alloc_BTC": dca_alloc["BTC"], "dca_alloc_ETH": dca_alloc["ETH"],
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
                "strategy": scenario.name, "model": scenario.model,
                "signal_date": row.get("signal_date"),
                "signal_available_at": row.get("signal_available_at"),
                "execution_4h_open": timestamp, "btc_close": row.get("BTC_daily_close"),
                "eth_execution_price": prices_open["ETH"],
                "sma10": row.get("sma10"), "sma20": row.get("sma20"),
                "sma50": row.get("sma50"), "sma200": row.get("sma200"),
                "sma200_slope_20d": row.get("feature_sma200_slope", np.nan),
                "ahr999": row.get("ahr999_fixed_arithmetic"), "bear_risk": np.nan,
                "ai_enabled": False, "ai_intervention": ai_intervention,
                "ai_intervention_reason": ai_reason,
                "state_before": before_state, "state_after": state.macro_state,
                "stage_before": before_stage, "stage_after": state.stage,
                "active_target_before": before_target, "active_target_after": state.active_target,
                "crypto_exposure_before": before_exposure,
                "crypto_exposure_after": _exposure(state, prices_open),
                "tactical_bear_cash_after": state.tactical_bear_cash,
                "temporary_hedge_cash_after": _temp_cash(state),
                "actions": "|".join(actions),
                "bull_persistence_active": persistence_active,
                "healthy_bull_structure": healthy,
                "bull_persistence_guard": bool(persistence_active and healthy),
                "bear_reentry_candidate_active": candidate is not None,
                "bear_reentry_confirmation_count": int(candidate["confirmation_count"]) if candidate else 0,
                "sma200_failure_streak": sma200_failure_streak,
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
        reentry_rows.append(candidate)
    final_signal_date = frame.iloc[-1].get("signal_date")
    for item in cycles:
        if pd.isna(item["end"]):
            item["end"] = final_signal_date
            item["status"] = "OPEN_AT_END"

    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=rules)
    return V39BacktestResult(
        scenario=scenario, summary=summary, history=history, trades=trade_frame,
        signals=pd.DataFrame(signals), transitions=pd.DataFrame(transitions),
        cycles=pd.DataFrame(cycles), temporary_lots=pd.DataFrame(state.temporary_lots),
        cash_events=pd.DataFrame(cash_events), counters=counters,
        blocked_sells=pd.DataFrame(blocked_sells),
        bear_reentry_audit=pd.DataFrame(reentry_rows),
    )
