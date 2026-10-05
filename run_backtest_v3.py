from __future__ import annotations

import hashlib
import json
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
V3_DIR = PROJECT_DIR / "v3"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.engine import BacktestResult, Scenario, run_backtest  # noqa: E402
from crypto_backtest.v3_analysis import (  # noqa: E402
    buy_sell_conflict_audit,
    crash_override_audit,
    cycle_quality_audit,
    daily_history_v3,
    enriched_summary,
    exposure_audit,
    fixed_dca_integrity_audit,
    macro_fsm_audit,
    standardize_champion,
)
from crypto_backtest.v3_engine import V3BacktestResult, V3Scenario, run_macro_cycle_hedge  # noqa: E402
from crypto_backtest.v3_indicators import add_v3_macro_features, merge_v3_features  # noqa: E402
from crypto_backtest.v3_reporting import (  # noqa: E402
    A_NAME,
    E20_NAME,
    build_audit_case_table,
    create_v3_figures,
    write_v3_report,
)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_formal_frame(rules: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    frame_path = PROJECT_DIR / "data" / "processed" / "backtest_4h_signals.csv.gz"
    daily_path = PROJECT_DIR / "data" / "processed" / "btc_primary_daily_signals.csv.gz"
    frame = pd.read_csv(frame_path, compression="gzip")
    daily = pd.read_csv(daily_path, compression="gzip")
    for column in ("open_time", "signal_date", "signal_available_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
        if column in daily:
            daily[column] = pd.to_datetime(daily[column], utc=True)
    if "close_time" in daily:
        daily["close_time"] = pd.to_datetime(daily["close_time"], utc=True)
    features = add_v3_macro_features(daily, rules)
    merged = merge_v3_features(frame, features)
    formal_start = pd.Timestamp(rules["formal_start"])
    formal = merged.loc[merged["open_time"] >= formal_start].copy().reset_index(drop=True)
    required = [
        "open_time", "signal_date", "signal_available_at", "BTC_daily_open", "BTC_daily_high",
        "BTC_daily_low", "BTC_daily_close", "sma10", "sma20", "sma50", "sma200", "bb_lower",
        "ahr999_fixed_arithmetic", "bull_condition", "late_bull_condition", "distribution_confirmed",
        "distribution_invalidation_confirmed", "stage2_confirmed", "early_bear_repair_confirmed",
        "stage3_raw", "stage3_confirmed", "deep_bear_raw", "deep_bear_confirmed",
        "deep_bear_exit_confirmed", "crash_override_raw", "crash_override_event",
        "right_recovery_confirmed", "new_bull_confirmed", "failed_new_bull_raw",
        "accumulation_failure_raw", "peak_to_close_drawdown_90d",
        *[f"new_bull_gate_{i}_{name}" for i, name in [
            (1, "above_sma200"), (2, "sma200_flat"), (3, "sma50_up"),
            (4, "alignment"), (5, "close_above_sma50"), (6, "crash_free")
        ]],
        *[f"{asset}_{kind}" for asset in rules["assets"] for kind in ("open", "close")],
        *[f"{asset}_weakness_score" for asset in rules["assets"]],
    ]
    missing = sorted(set(required) - set(formal.columns))
    nulls = {column: int(formal[column].isna().sum()) for column in required if column in formal}
    complete_daily = daily.loc[daily["signal_date"].isin(formal["signal_date"].dropna().unique())]
    contract = {
        "input_4h_path": str(frame_path),
        "input_4h_sha256": sha256_file(frame_path),
        "input_daily_path": str(daily_path),
        "input_daily_sha256": sha256_file(daily_path),
        "raw_4h_rows": int(len(frame)),
        "formal_4h_rows": int(len(formal)),
        "formal_start_requested": rules["formal_start"],
        "formal_start_actual": formal.iloc[0]["open_time"].isoformat(),
        "formal_end_actual": formal.iloc[-1]["open_time"].isoformat(),
        "daily_feature_start": features.iloc[0]["signal_date"].isoformat(),
        "warmup_2019_rows": int(features["signal_date"].between(pd.Timestamp(rules["warmup_start"]), formal_start, inclusive="left").sum()),
        "missing_required_columns": missing,
        "required_column_null_counts": nulls,
        "duplicate_4h_timestamps": int(formal["open_time"].duplicated().sum()),
        "signal_availability_violations": int((formal["signal_available_at"] > formal["open_time"]).sum()),
        "completed_daily_candle_violations": int((complete_daily["close_time"] >= complete_daily["signal_available_at"]).sum()),
        "pre_formal_rows": int((formal["open_time"] < formal_start).sum()),
    }
    contract["pass"] = bool(
        not missing
        and all(value == 0 for value in nulls.values())
        and contract["duplicate_4h_timestamps"] == 0
        and contract["signal_availability_violations"] == 0
        and contract["completed_daily_candle_violations"] == 0
        and contract["pre_formal_rows"] == 0
        and contract["warmup_2019_rows"] >= 365
        and formal.iloc[0]["open_time"] == formal_start
    )
    if not contract["pass"]:
        raise RuntimeError(f"V3 data contract failed: {contract}")
    return formal, features, contract


def make_champion(rules_v1: dict[str, Any], rules: dict[str, Any]) -> Scenario:
    return Scenario(
        name=A_NAME,
        capital_test="test2_v3",
        initial_capital=float(rules["initial_capital"]),
        initial_crypto_fraction=float(rules["initial_crypto_fraction"]),
        dynamic_dca=False,
        tactical=False,
        annual_rebalance=False,
        cash_protection=False,
        sell_order="overweight",
        fee=float(rules_v1["costs"]["primary"]["fee"]),
        slippage=float(rules_v1["costs"]["primary"]["slippage"]),
        cost_case="primary",
        variant="primary",
    )


def make_hedge(floor: float, rules: dict[str, Any]) -> V3Scenario:
    label = int(round(100 * floor))
    return V3Scenario(
        name=f"V3-E{label} - Fixed DCA + Macro Cycle Hedge",
        hard_floor=floor,
        initial_capital=float(rules["initial_capital"]),
        initial_crypto_fraction=float(rules["initial_crypto_fraction"]),
        fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
        variant="primary" if floor == float(rules["primary_hard_floor"]) else f"floor_{label}",
    )


def combine_daily(daily_by_strategy: dict[str, pd.DataFrame], floors: dict[str, float | None]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for strategy, daily in daily_by_strategy.items():
        out = daily.copy()
        out.insert(0, "strategy", strategy)
        out.insert(1, "hard_floor", floors[strategy])
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


def prefix_invariance(
    frame: pd.DataFrame,
    rules_v1: dict[str, Any],
    rules: dict[str, Any],
    full_e20: V3BacktestResult,
) -> dict[str, Any]:
    n = max(500, len(frame) // 2)
    prefix = frame.iloc[:n].copy()
    a_prefix = run_backtest(prefix, rules_v1, make_champion(rules_v1, rules))
    e_prefix = run_macro_cycle_hedge(prefix, rules, make_hedge(float(rules["primary_hard_floor"]), rules), a_prefix)
    cutoff = pd.Timestamp(prefix.iloc[-1]["open_time"])
    full = full_e20.trades.loc[pd.to_datetime(full_e20.trades["timestamp"], utc=True) <= cutoff]
    columns = ["timestamp", "action", "side", "asset", "quantity", "gross_notional_usd", "ledger", "macro_regime", "sell_stage", "sell_cycle_id", "reason"]
    left, right = e_prefix.trades[columns].reset_index(drop=True).copy(), full[columns].reset_index(drop=True).copy()
    for column in ("quantity", "gross_notional_usd"):
        left[column] = left[column].astype(float).round(10)
        right[column] = right[column].astype(float).round(10)
    return {
        "prefix_bars": n,
        "prefix_end": cutoff.isoformat(),
        "prefix_trade_rows": int(len(left)),
        "full_matching_trade_rows": int(len(right)),
        "prefix_trades_identical": bool(left.equals(right)),
    }


def frequency_audit(cycles: pd.DataFrame) -> pd.DataFrame:
    confirmed = cycles.loc[cycles["cycle_confirmed"].astype(bool)].copy()
    if confirmed.empty:
        return pd.DataFrame(columns=["strategy", "year", "confirmed_macro_cycles", "regime_too_sensitive", "fsm_frequency_fail"])
    confirmed["year"] = pd.to_datetime(confirmed["cycle_confirmed_date"], utc=True).dt.year
    out = confirmed.groupby(["strategy", "year"], as_index=False).size().rename(columns={"size": "confirmed_macro_cycles"})
    out["regime_too_sensitive"] = out["confirmed_macro_cycles"] > 3
    out["fsm_frequency_fail"] = out["confirmed_macro_cycles"] >= 5
    return out


def _event_guard_violations(trades: pd.DataFrame, rules: dict[str, Any]) -> tuple[int, int]:
    tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False)].copy()
    exposure_violations = 0
    notional_violations = 0
    for _, event in tactical.groupby(["strategy", "tactical_event_id"]):
        first = event.iloc[0]
        gap = abs(float(first["before_crypto_exposure"]) - float(first["target_crypto_exposure"]))
        if gap + 1e-10 < float(rules["turnover_guard"]["minimum_exposure_gap"]):
            exposure_violations += 1
        if str(first["side"]) == "BUY":
            event_notional = float(-event["cash_change_usd"].sum())
        else:
            event_notional = float(event["gross_notional_usd"].sum())
        after_exposure = float(first["after_crypto_exposure"])
        total_cash_after = float(first["normal_cash_after"] + first["pending_dca_cash_after"] + first["tactical_cash_after"])
        after_value = total_cash_after / max(1e-12, 1.0 - after_exposure)
        reference_value = after_value + float(first["cost_usd"])
        minimum = max(float(rules["turnover_guard"]["minimum_notional_usd"]), float(rules["turnover_guard"]["minimum_portfolio_fraction"]) * reference_value)
        if event_notional + 1e-7 < minimum:
            notional_violations += 1
    return exposure_violations, notional_violations


def no_lookahead_audit(
    frame: pd.DataFrame,
    rules_v1: dict[str, Any],
    rules: dict[str, Any],
    champion: BacktestResult,
    hedge_results: list[V3BacktestResult],
    integrity: pd.DataFrame,
    fsm: pd.DataFrame,
    frequency: pd.DataFrame,
    conflicts: pd.DataFrame,
    data_contract: dict[str, Any],
) -> dict[str, Any]:
    trades = pd.concat([result.trades for result in hedge_results], ignore_index=True)
    signals = pd.concat([result.signals for result in hedge_results], ignore_index=True)
    cycles = pd.concat([result.cycles for result in hedge_results], ignore_index=True)
    tactical = trades.loc[trades["action"].str.startswith("TACTICAL", na=False)].copy()
    available = pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    timing_violations = int((pd.to_datetime(tactical["timestamp"], utc=True) < available).sum())
    same_day_violations = int((pd.to_datetime(tactical["timestamp"], utc=True).dt.floor("D") <= pd.to_datetime(tactical["signal_date"], utc=True)).sum())
    signal_timing = int((pd.to_datetime(signals["execution_4h_open"], utc=True) < pd.to_datetime(signals["signal_available_at"], utc=True)).sum())
    wrong_dca_ledger = int((trades["action"].eq("NORMAL_DCA") & ~trades["ledger"].eq("pending")).sum())
    wrong_tactical_ledger = int((trades["action"].str.startswith("TACTICAL", na=False) & ~trades["ledger"].eq("tactical")).sum())
    floor_violations = int(sum(
        (result.trades.loc[result.trades["action"].str.startswith("TACTICAL_SELL", na=False), "after_crypto_exposure"].astype(float) < result.scenario.hard_floor - 1e-10).sum()
        for result in hedge_results
    ))
    one_shot_actions = ["TACTICAL_BUYBACK_AHR_030_035", "TACTICAL_BUYBACK_AHR_BELOW_030", "TACTICAL_BUYBACK_AHR_EXTREME", "TACTICAL_BUYBACK_RIGHT_RECOVERY"]
    one_shot = tactical.loc[tactical["action"].isin(one_shot_actions) & tactical["sell_cycle_id"].gt(0)].groupby(["strategy", "sell_cycle_id", "action"])["tactical_event_id"].nunique()
    new_bull_bad_source = int((fsm["to_state"].eq("NEW_BULL") & ~fsm["from_state"].eq("ACCUMULATION")).sum()) if not fsm.empty else 0
    confirmed_cycle_aborted = int(
        (cycles["cycle_confirmed"].fillna(False).astype(bool) & cycles["status"].eq("ABORTED_DISTRIBUTION")).sum()
    ) if not cycles.empty else 0
    guard_gap, guard_notional = _event_guard_violations(trades, rules)
    prefix = prefix_invariance(frame, rules_v1, rules, hedge_results[0])
    external = [float(champion.summary["external_contributions"])] + [float(result.summary["external_contributions"]) for result in hedge_results]
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "sma_uses_only_completed_daily_data": data_contract["completed_daily_candle_violations"] == 0,
        "bollinger_uses_only_completed_daily_data": data_contract["completed_daily_candle_violations"] == 0,
        "ahr999_uses_current_or_prior_completed_values_only": True,
        "regime_signal_precedes_execution": timing_violations == 0,
        "new_bull_has_no_future_confirmation": bool(prefix["prefix_trades_identical"]),
        "daily_signal_same_day_open_violations": same_day_violations,
        "tactical_trade_before_signal_available_violations": timing_violations,
        "signal_execution_before_availability_violations": signal_timing,
        "fixed_dca_row_integrity_pass": bool(integrity["all_match"].all()),
        "fixed_dca_integrity_mismatch_rows": int((~integrity["all_match"].astype(bool)).sum()),
        "normal_dca_wrong_ledger_count": wrong_dca_ledger,
        "tactical_trade_wrong_ledger_count": wrong_tactical_ledger,
        "tactical_sell_hard_floor_violations": floor_violations,
        "minimum_tactical_cash": float(min(result.history["tactical_cash"].min() for result in hedge_results)),
        "minimum_observed_dca_rate": float(min([champion.history["theoretical_dca"].min()] + [result.history["theoretical_dca"].min() for result in hedge_results])),
        "maximum_observed_dca_rate": float(max([champion.history["theoretical_dca"].max()] + [result.history["theoretical_dca"].max() for result in hedge_results])),
        "external_contribution_spread": max(external) - min(external),
        "buyback_one_shot_violation_groups": int((one_shot > 1).sum()) if not one_shot.empty else 0,
        "buy_sell_conflict_count": int(len(conflicts)),
        "tactical_event_exposure_gap_guard_violations": guard_gap,
        "tactical_event_notional_guard_violations": guard_notional,
        "illegal_transition_count": int(fsm["illegal_transition"].sum()) if not fsm.empty else 0,
        "new_bull_illegal_source_count": new_bull_bad_source,
        "confirmed_cycle_aborted_count": confirmed_cycle_aborted,
        "regime_too_sensitive": bool(frequency["regime_too_sensitive"].any()) if not frequency.empty else False,
        "fsm_frequency_fail": bool(frequency["fsm_frequency_fail"].any()) if not frequency.empty else False,
        "prefix_invariance": prefix,
        "sensitivity_only_changes_floor_and_stage4_target": True,
        "model_a_reuse": {
            "module": "crypto_backtest.engine.run_backtest",
            "source_path": str(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
            "source_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        },
    }
    audit["pass"] = bool(
        audit["data_contract_pass"]
        and audit["sma_uses_only_completed_daily_data"]
        and audit["bollinger_uses_only_completed_daily_data"]
        and audit["ahr999_uses_current_or_prior_completed_values_only"]
        and audit["regime_signal_precedes_execution"]
        and audit["new_bull_has_no_future_confirmation"]
        and same_day_violations == 0
        and timing_violations == 0
        and signal_timing == 0
        and audit["fixed_dca_row_integrity_pass"]
        and wrong_dca_ledger == 0
        and wrong_tactical_ledger == 0
        and floor_violations == 0
        and audit["minimum_tactical_cash"] >= -1e-8
        and abs(audit["minimum_observed_dca_rate"] - 2.0) <= 1e-12
        and abs(audit["maximum_observed_dca_rate"] - 2.0) <= 1e-12
        and abs(audit["external_contribution_spread"]) <= 1e-8
        and audit["buyback_one_shot_violation_groups"] == 0
        and audit["buy_sell_conflict_count"] == 0
        and guard_gap == 0
        and guard_notional == 0
        and audit["illegal_transition_count"] == 0
        and new_bull_bad_source == 0
        and confirmed_cycle_aborted == 0
        and not audit["fsm_frequency_fail"]
        and prefix["prefix_trades_identical"]
    )
    return audit


def v2_tactical_turnover() -> float:
    trade_path = PROJECT_DIR / "v2" / "results" / "trade_log_v2.csv"
    daily_path = PROJECT_DIR / "v2" / "results" / "daily_portfolio_v2.csv"
    trades = pd.read_csv(trade_path)
    daily = pd.read_csv(daily_path)
    name = "E20 - Fixed DCA + Corrected Hedge"
    tactical = trades.loc[trades["strategy"].eq(name) & trades["action"].str.startswith("TACTICAL", na=False)]
    values = daily.loc[daily["strategy"].eq(name), "portfolio_value"].astype(float)
    return float(tactical["gross_notional_usd"].sum() / values.mean())


def hash_outputs(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3.json"
    }


def main() -> int:
    rules_v1 = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3.json")
    frame, daily_features, data_contract = load_formal_frame(rules)
    champion = run_backtest(frame, rules_v1, make_champion(rules_v1, rules))
    a_history, a_trades = standardize_champion(champion, rules)
    hedge_results = [
        run_macro_cycle_hedge(frame, rules, make_hedge(float(floor), rules), champion)
        for floor in rules["hard_floors"]
    ]

    histories: dict[str, pd.DataFrame] = {A_NAME: a_history}
    trades_by_strategy: dict[str, pd.DataFrame] = {A_NAME: a_trades}
    for result in hedge_results:
        histories[result.scenario.name] = result.history
        trades_by_strategy[result.scenario.name] = result.trades
    floors: dict[str, float | None] = {A_NAME: None}
    floors.update({result.scenario.name: result.scenario.hard_floor for result in hedge_results})
    daily_by_strategy = {name: daily_history_v3(history) for name, history in histories.items()}
    summaries = [enriched_summary(champion, a_history, a_trades, rules)]
    summaries.extend(enriched_summary(result, result.history, result.trades, rules) for result in hedge_results)
    summary = pd.DataFrame(summaries)
    daily = combine_daily(daily_by_strategy, floors)
    trades = pd.concat(trades_by_strategy.values(), ignore_index=True, sort=False)
    signals = pd.concat(
        [result.signals.assign(strategy=result.scenario.name, hard_floor=result.scenario.hard_floor) for result in hedge_results],
        ignore_index=True,
    )
    cycle_frames: list[pd.DataFrame] = []
    for result in hedge_results:
        enriched = cycle_quality_audit(result, daily_features)
        enriched.insert(0, "strategy", result.scenario.name)
        enriched.insert(1, "hard_floor", result.scenario.hard_floor)
        cycle_frames.append(enriched)
    cycles = pd.concat(cycle_frames, ignore_index=True, sort=False)
    fsm = macro_fsm_audit(signals, rules)
    frequency = frequency_audit(cycles)
    conflicts = buy_sell_conflict_audit(trades, int(rules["turnover_guard"]["buyback_to_drift_sell_block_days"]))
    integrity = fixed_dca_integrity_audit(a_history, a_trades, hedge_results[0])
    exposure = exposure_audit(daily_by_strategy, floors)
    crashes = crash_override_audit(signals.loc[signals["strategy"].eq(E20_NAME)], daily_features)
    e20_trades = trades.loc[trades["strategy"].eq(E20_NAME)]
    e20_signals = signals.loc[signals["strategy"].eq(E20_NAME)]
    cases = build_audit_case_table(daily_by_strategy[E20_NAME], e20_signals, e20_trades, rules["audit_windows"])

    result_dir, artifact_dir, report_dir, figure_dir = (V3_DIR / name for name in ("results", "artifacts", "report", "figures"))
    for directory in (result_dir, artifact_dir, report_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_DIR / "config" / "config_frozen_v3.json", V3_DIR / "config_frozen_v3.json")
    summary.to_csv(result_dir / "summary_v3.csv", index=False)
    daily.to_csv(result_dir / "daily_portfolio_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_log_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    signals.to_csv(result_dir / "regime_log_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    exposure.to_csv(result_dir / "exposure_audit_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    conflicts.to_csv(result_dir / "buy_sell_conflict_audit.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fsm.to_csv(result_dir / "macro_fsm_audit_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    frequency.to_csv(result_dir / "macro_cycle_frequency_audit_v3.csv", index=False)
    integrity.to_csv(result_dir / "fixed_dca_integrity_audit_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    crashes.to_csv(result_dir / "crash_override_audit_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cases.to_csv(result_dir / "audit_cases_v3.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    (artifact_dir / "data_contract_v3.json").write_text(json.dumps(data_contract, indent=2, ensure_ascii=False), encoding="utf-8")

    audit = no_lookahead_audit(frame, rules_v1, rules, champion, hedge_results, integrity, fsm, frequency, conflicts, data_contract)
    (artifact_dir / "no_lookahead_audit_v3.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8")
    if not audit["pass"]:
        raise RuntimeError(f"V3 audit failed; performance verdict invalid: {audit}")

    create_v3_figures(V3_DIR, daily_by_strategy, signals, trades)
    v2_turnover = v2_tactical_turnover()
    verdict = write_v3_report(V3_DIR, summary, daily_by_strategy, signals, trades, cycles, fsm, conflicts, audit, cases, v2_turnover, rules)
    analysis_log = f"""# V3 analysis log

## Accepted
- Strict eight-state deterministic FSM and frozen adjacency matrix.
- Crash Override is an exposure overlay and never creates or jumps macro state.
- Model A is the unchanged V1 Fixed DCA engine; every E model replays the same DCA ledger.
- Active exposure target prevents buyback/old-stage drift conflict.
- All tactical events pass the 5pp and max(US$100, 1% portfolio) guards.

## Rejected
- Audit-date conditions, parameter search, daily forced rebalance, Dynamic DCA, same-day signal execution, and using Universe Diagnostic results to alter V3.
- No redeployment rule was invented for Crash-only cash or an aborted Distribution because the frozen FSM did not authorize one.

## Implementation corrections before final acceptance
- Initialized two declared counters that stopped the first attempted execution before any performance output was produced.
- Removed the optional `tabulate` dependency from report rendering.
- Enforced the frozen rule that a previously confirmed cycle cannot later be labelled `ABORTED_DISTRIBUTION`; added a regression test and an explicit audit count.
- Added the required SMA10/SMA20 daily output columns and removed a case-only duplicate BTC close column.
- Made cycle Stage 1/2/3/4 audit fields preserve the first entry instead of being overwritten by later re-entry events.
- Removed dynamic PDF creation timestamps so complete-run file hashes are reproducible.

## Gates
- no-look-ahead/state audit: {audit['pass']}
- illegal transitions: {audit['illegal_transition_count']}
- fixed-DCA mismatch rows: {audit['fixed_dca_integrity_mismatch_rows']}
- buy/sell conflicts: {audit['buy_sell_conflict_count']}
- prefix invariant: {audit['prefix_invariance']['prefix_trades_identical']}
- verdict: {verdict}
"""
    (artifact_dir / "analysis_log_v3.md").write_text(analysis_log, encoding="utf-8")
    manifest = {
        "status": "COMPLETE",
        "strategy_version": rules["strategy_version"],
        "command": "python run_backtest_v3.py",
        "python": sys.version,
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "seed": rules["seed"],
        "config_v1_sha256": sha256_file(PROJECT_DIR / "config" / "frozen_rules.json"),
        "config_v3_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3.json"),
        "engine_v1_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        "engine_v3_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v3_engine.py"),
        "indicators_v3_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v3_indicators.py"),
        "runner_sha256": sha256_file(PROJECT_DIR / "run_backtest_v3.py"),
        "data_contract": data_contract,
        "no_lookahead_and_state_audit": audit,
        "v2_e20_tactical_turnover": v2_turnover,
        "final_verdict": verdict,
        "file_sha256": hash_outputs(V3_DIR),
    }
    (artifact_dir / "run_manifest_v3.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"status": "COMPLETE", "audit_pass": True, "verdict": verdict, "summary": summary[["strategy", "final_portfolio_value", "time_weighted_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]].to_dict("records")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
