from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
V2_DIR = PROJECT_DIR / "v2"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.engine import BacktestResult, Scenario, run_backtest  # noqa: E402
from crypto_backtest.v2_analysis import (  # noqa: E402
    daily_history_v2,
    enriched_summary,
    exposure_audit,
    fixed_dca_integrity_audit,
    segment_analysis,
    standardize_champion,
)
from crypto_backtest.v2_engine import (  # noqa: E402
    HedgeScenario,
    V2BacktestResult,
    run_cycle_hedge_backtest,
)
from crypto_backtest.v2_reporting import create_v2_figures, write_v2_report  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_formal_frame(rules_v2: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame_path = PROJECT_DIR / "data" / "processed" / "backtest_4h_signals.csv.gz"
    daily_path = PROJECT_DIR / "data" / "processed" / "btc_primary_daily_signals.csv.gz"
    if not frame_path.exists() or not daily_path.exists():
        raise FileNotFoundError("Frozen V1 processed inputs are missing; run V1 data preparation first")
    frame = pd.read_csv(frame_path, compression="gzip")
    primary_daily = pd.read_csv(daily_path, compression="gzip")
    for column in ("open_time", "signal_date", "signal_available_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
        if column in primary_daily:
            primary_daily[column] = pd.to_datetime(primary_daily[column], utc=True)
    formal_start = pd.Timestamp(rules_v2["formal_start"])
    formal = frame.loc[frame["open_time"] >= formal_start].copy().reset_index(drop=True)
    if formal.empty:
        raise RuntimeError("No bars remain after the V2 formal-period gate")
    required = [
        "open_time",
        "signal_date",
        "signal_available_at",
        "sma10",
        "sma20",
        "sma50",
        "sma200",
        "bb_upper",
        "bb_lower",
        "ahr999_fixed_arithmetic",
        "stage1_condition",
        "stage2_condition",
        "stage3_condition",
        "stage4_condition",
        "right_confirmation",
        "strong_confirmation",
        *[f"{asset}_{kind}" for asset in rules_v2["assets"] for kind in ("open", "close")],
    ]
    missing_columns = sorted(set(required) - set(formal.columns))
    nulls = {column: int(formal[column].isna().sum()) for column in required if column in formal}
    contract = {
        "input_4h_path": str(frame_path),
        "input_4h_sha256": sha256_file(frame_path),
        "input_daily_path": str(daily_path),
        "input_daily_sha256": sha256_file(daily_path),
        "raw_rows": int(len(frame)),
        "formal_rows": int(len(formal)),
        "formal_start_requested": rules_v2["formal_start"],
        "formal_start_actual": formal["open_time"].iloc[0].isoformat(),
        "formal_end_actual": formal["open_time"].iloc[-1].isoformat(),
        "warmup_start_requested": rules_v2["warmup_start"],
        "daily_source_start": primary_daily["open_time"].min().isoformat(),
        "warmup_rows_2019": int(
            primary_daily["open_time"].between(
                pd.Timestamp(rules_v2["warmup_start"]), formal_start, inclusive="left"
            ).sum()
        ),
        "missing_required_columns": missing_columns,
        "required_column_null_counts": nulls,
        "duplicate_4h_timestamps": int(formal["open_time"].duplicated().sum()),
        "signal_availability_violations": int(
            (formal["signal_available_at"] > formal["open_time"]).sum()
        ),
        "pre_formal_rows_in_performance_frame": int((formal["open_time"] < formal_start).sum()),
    }
    contract["pass"] = bool(
        not missing_columns
        and all(value == 0 for value in nulls.values())
        and contract["duplicate_4h_timestamps"] == 0
        and contract["signal_availability_violations"] == 0
        and contract["pre_formal_rows_in_performance_frame"] == 0
        and contract["warmup_rows_2019"] >= 365
        and formal["open_time"].iloc[0] == formal_start
    )
    if not contract["pass"]:
        raise RuntimeError(f"V2 data contract failed: {contract}")
    return formal, contract


def make_champion(rules_v1: dict[str, Any], rules_v2: dict[str, Any]) -> Scenario:
    return Scenario(
        name="A - Fixed DCA Champion",
        capital_test="test2_v2",
        initial_capital=float(rules_v2["initial_capital"]),
        initial_crypto_fraction=float(rules_v2["initial_crypto_fraction"]),
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


def make_hedge(floor: float, rules_v2: dict[str, Any]) -> HedgeScenario:
    label = int(round(100 * floor))
    return HedgeScenario(
        name=f"E{label} - Fixed DCA + Corrected Hedge",
        hard_floor=floor,
        initial_capital=float(rules_v2["initial_capital"]),
        initial_crypto_fraction=float(rules_v2["initial_crypto_fraction"]),
        fee=float(rules_v2["costs"]["fee"]),
        slippage=float(rules_v2["costs"]["slippage"]),
        variant="primary" if floor == float(rules_v2["primary_hard_floor"]) else f"floor_{label}",
    )


def combine_daily(
    daily_by_strategy: dict[str, pd.DataFrame], floors: dict[str, float | None]
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for strategy, daily in daily_by_strategy.items():
        out = daily.copy()
        out.insert(0, "strategy", strategy)
        out.insert(1, "hard_floor", floors[strategy])
        frames.append(out)
    return pd.concat(frames, ignore_index=True)


def combine_cycles(results: list[V2BacktestResult]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    columns = [
        "strategy",
        "hard_floor",
        "cycle_id",
        "cycle_start",
        "cycle_end",
        "BULL_date",
        "LATE_BULL_date",
        "DISTRIBUTION_date",
        "BEAR_date",
        "DEEP_BEAR_date",
        "ACCUMULATION_date",
        "NEW_BULL_date",
        "stage_1_date",
        "stage_2_date",
        "stage_3_date",
        "stage_4_date",
        "reset_date",
        "redeployment_complete_date",
        "status",
    ]
    for result in results:
        cycles = result.cycles.copy()
        if cycles.empty:
            continue
        cycles.insert(0, "strategy", result.scenario.name)
        cycles.insert(1, "hard_floor", result.scenario.hard_floor)
        frames.append(cycles)
    return pd.concat(frames, ignore_index=True)[columns] if frames else pd.DataFrame(columns=columns)


def one_shot_violation_count(trades: pd.DataFrame) -> int:
    watched = {
        "TACTICAL_BUYBACK_AHR_030_035",
        "TACTICAL_BUYBACK_AHR_BELOW_030",
        "TACTICAL_BUYBACK_AHR_EXTREME",
        "TACTICAL_BUYBACK_RIGHT_CONFIRMATION",
    }
    work = trades.loc[trades["action"].isin(watched) & (trades["sell_cycle_id"] > 0)].copy()
    if work.empty:
        return 0
    counts = work.groupby(["strategy", "sell_cycle_id", "action"])["timestamp"].nunique()
    return int((counts > 1).sum())


def cycle_transition_violations(cycles: pd.DataFrame) -> int:
    violations = 0
    stage_columns = ["stage_1_date", "stage_2_date", "stage_3_date", "stage_4_date"]
    for _, cycle in cycles.iterrows():
        new_bull = pd.to_datetime(cycle["NEW_BULL_date"], utc=True)
        reset = pd.to_datetime(cycle["reset_date"], utc=True)
        if pd.notna(new_bull) and (pd.isna(reset) or reset < new_bull):
            violations += 1
        if pd.notna(new_bull):
            for column in stage_columns:
                stage_date = pd.to_datetime(cycle[column], utc=True)
                if pd.notna(stage_date) and stage_date > new_bull:
                    violations += 1
    return violations


def prefix_invariance_audit(
    frame: pd.DataFrame,
    rules_v1: dict[str, Any],
    rules_v2: dict[str, Any],
    full_e20: V2BacktestResult,
) -> dict[str, Any]:
    n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:n].copy()
    a_prefix = run_backtest(prefix_frame, rules_v1, make_champion(rules_v1, rules_v2))
    e_prefix = run_cycle_hedge_backtest(
        prefix_frame,
        rules_v2,
        make_hedge(float(rules_v2["primary_hard_floor"]), rules_v2),
        a_prefix,
    )
    cutoff = prefix_frame.iloc[-1]["open_time"]
    full_trades = full_e20.trades.loc[full_e20.trades["timestamp"] <= cutoff].copy()
    columns = [
        "timestamp",
        "action",
        "side",
        "asset",
        "quantity",
        "gross_notional_usd",
        "ledger",
        "sell_stage",
        "cycle_regime",
        "sell_cycle_id",
    ]
    left = e_prefix.trades[columns].reset_index(drop=True).copy()
    right = full_trades[columns].reset_index(drop=True).copy()
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


def no_lookahead_and_state_audit(
    frame: pd.DataFrame,
    rules_v1: dict[str, Any],
    rules_v2: dict[str, Any],
    a_result: BacktestResult,
    hedge_results: list[V2BacktestResult],
    integrity: pd.DataFrame,
    cycles: pd.DataFrame,
    exposure: pd.DataFrame,
    data_contract: dict[str, Any],
) -> dict[str, Any]:
    all_trades = pd.concat([result.trades for result in hedge_results], ignore_index=True)
    tactical = all_trades.loc[all_trades["action"].str.startswith("TACTICAL", na=False)].copy()
    trade_signal_available = pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
    tactical_timing_violations = int(
        (pd.to_datetime(tactical["timestamp"], utc=True) < trade_signal_available).sum()
    )
    signal_timing_violations = int(
        sum(
            (
                pd.to_datetime(result.signals["execution_4h_open"], utc=True)
                < pd.to_datetime(result.signals["signal_available_at"], utc=True)
            ).sum()
            for result in hedge_results
        )
    )
    dca_wrong_ledger = int(
        sum(
            (
                result.trades["action"].eq("NORMAL_DCA")
                & ~result.trades["ledger"].eq("pending")
            ).sum()
            for result in hedge_results
        )
    )
    tactical_wrong_ledger = int(
        (
            all_trades["action"].str.startswith("TACTICAL", na=False)
            & ~all_trades["ledger"].eq("tactical")
        ).sum()
    )
    sell_floor_violations = int(
        sum(
            (
                result.trades.loc[
                    result.trades["action"].str.startswith("TACTICAL_SELL", na=False),
                    "post_trade_crypto_exposure",
                ].astype(float)
                < result.scenario.hard_floor - 1e-10
            ).sum()
            for result in hedge_results
        )
    )
    negative_tactical = float(min(result.history["tactical_cash"].min() for result in hedge_results))
    dca_rates = [
        float(a_result.history["theoretical_dca"].min()),
        float(a_result.history["theoretical_dca"].max()),
        *[float(result.history["theoretical_dca"].min()) for result in hedge_results],
        *[float(result.history["theoretical_dca"].max()) for result in hedge_results],
    ]
    external = [float(a_result.summary["external_contributions"])] + [
        float(result.summary["external_contributions"]) for result in hedge_results
    ]
    stage4_audit_failures = int((~exposure["stage4_upper_band_assertion_pass"].astype(bool)).sum())
    stage3_decoupling_failures = int((~exposure["stage3_93pct_decoupling_pass"].astype(bool)).sum())
    one_shot = one_shot_violation_count(all_trades)
    cycle_violations = cycle_transition_violations(cycles)
    prefix = prefix_invariance_audit(frame, rules_v1, rules_v2, hedge_results[0])
    formal_start = pd.Timestamp(rules_v2["formal_start"])
    pre_formal_trades = int(
        sum((pd.to_datetime(result.trades["timestamp"], utc=True) < formal_start).sum() for result in hedge_results)
        + (pd.to_datetime(a_result.trades["timestamp"], utc=True) < formal_start).sum()
    )
    audit = {
        "data_contract_pass": bool(data_contract["pass"]),
        "daily_signal_available_after_candle_close_violations": int(
            data_contract["signal_availability_violations"]
        ),
        "tactical_trade_before_signal_available_violations": tactical_timing_violations,
        "signal_execution_before_availability_violations": signal_timing_violations,
        "pre_formal_period_trade_count": pre_formal_trades,
        "fixed_dca_integrity_rows": int(len(integrity)),
        "fixed_dca_integrity_mismatch_rows": int((~integrity["all_match"].astype(bool)).sum()),
        "normal_dca_wrong_ledger_count": dca_wrong_ledger,
        "tactical_trade_wrong_ledger_count": tactical_wrong_ledger,
        "tactical_sell_hard_floor_violations": sell_floor_violations,
        "minimum_tactical_cash": negative_tactical,
        "minimum_observed_dca_rate": min(dca_rates),
        "maximum_observed_dca_rate": max(dca_rates),
        "required_fixed_dca_rate": float(rules_v2["external_contribution_per_4h"]),
        "external_contribution_spread": max(external) - min(external),
        "buyback_one_shot_violation_groups": one_shot,
        "cycle_transition_or_reset_violations": cycle_violations,
        "stage4_upper_band_unexplained_daily_rows": stage4_audit_failures,
        "stage3_with_93pct_exposure_daily_rows": stage3_decoupling_failures,
        "daily_mark_to_market_floor_breach_rows_nonblocking": int(
            (~exposure["daily_mark_to_market_floor_pass"].astype(bool)).sum()
        ),
        "daily_floor_semantics": "nonblocking: floor constrains tactical sells; later price drift is reported",
        "prefix_invariance": prefix,
        "model_a_reuse": {
            "module": "crypto_backtest.engine.run_backtest",
            "source_path": str(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
            "source_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        },
    }
    audit["pass"] = bool(
        audit["data_contract_pass"]
        and audit["daily_signal_available_after_candle_close_violations"] == 0
        and tactical_timing_violations == 0
        and signal_timing_violations == 0
        and pre_formal_trades == 0
        and audit["fixed_dca_integrity_mismatch_rows"] == 0
        and dca_wrong_ledger == 0
        and tactical_wrong_ledger == 0
        and sell_floor_violations == 0
        and negative_tactical >= -1e-8
        and abs(min(dca_rates) - 2.0) <= 1e-12
        and abs(max(dca_rates) - 2.0) <= 1e-12
        and abs(audit["external_contribution_spread"]) <= 1e-8
        and one_shot == 0
        and cycle_violations == 0
        and stage4_audit_failures == 0
        and stage3_decoupling_failures == 0
        and prefix["prefix_trades_identical"]
    )
    return audit


def hash_outputs(v2_dir: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(v2_dir.rglob("*")):
        if path.is_file() and path.name != "run_manifest_v2.json":
            hashes[path.relative_to(v2_dir).as_posix()] = sha256_file(path)
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description="Run V2 Fixed DCA + Corrected Cycle Hedge")
    parser.parse_args()
    rules_v1 = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    rules_v2 = load_json(PROJECT_DIR / "config" / "frozen_rules_v2.json")
    frame, data_contract = load_formal_frame(rules_v2)

    champion = run_backtest(frame, rules_v1, make_champion(rules_v1, rules_v2))
    a_history, a_trades = standardize_champion(champion, rules_v2)
    hedge_results = [
        run_cycle_hedge_backtest(frame, rules_v2, make_hedge(float(floor), rules_v2), champion)
        for floor in rules_v2["hard_floors"]
    ]

    histories: dict[str, pd.DataFrame] = {champion.scenario.name: a_history}
    trades_by_strategy: dict[str, pd.DataFrame] = {champion.scenario.name: a_trades}
    for result in hedge_results:
        histories[result.scenario.name] = result.history
        trades_by_strategy[result.scenario.name] = result.trades
    floors: dict[str, float | None] = {champion.scenario.name: None}
    floors.update({result.scenario.name: result.scenario.hard_floor for result in hedge_results})

    summaries = [enriched_summary(champion, a_history, a_trades, rules_v2)]
    summaries.extend(
        enriched_summary(result, result.history, result.trades, rules_v2)
        for result in hedge_results
    )
    summary = pd.DataFrame(summaries)
    daily_by_strategy = {
        strategy: daily_history_v2(history) for strategy, history in histories.items()
    }
    daily = combine_daily(daily_by_strategy, floors)
    trades = pd.concat(trades_by_strategy.values(), ignore_index=True, sort=False)
    signals = pd.concat(
        [
            result.signals.assign(
                strategy=result.scenario.name,
                hard_floor=result.scenario.hard_floor,
            )
            for result in hedge_results
        ],
        ignore_index=True,
    )
    cycles = combine_cycles(hedge_results)
    integrity = fixed_dca_integrity_audit(a_history, a_trades, hedge_results[0])
    exposure = exposure_audit(daily_by_strategy, floors)
    segments = segment_analysis(histories, rules_v2["segments"])

    result_dir = V2_DIR / "results"
    artifact_dir = V2_DIR / "artifacts"
    report_dir = V2_DIR / "report"
    for directory in (result_dir, artifact_dir, report_dir, V2_DIR / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    summary.to_csv(result_dir / "summary_v2.csv", index=False)
    daily.to_csv(result_dir / "daily_portfolio_v2.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v2.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    signals.to_csv(result_dir / "signal_log_v2.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_audit.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    exposure.to_csv(result_dir / "exposure_audit.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    integrity.to_csv(result_dir / "fixed_dca_integrity_audit.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    segments.to_csv(result_dir / "segment_analysis_v2.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    (artifact_dir / "data_contract_v2.json").write_text(
        json.dumps(data_contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    audit = no_lookahead_and_state_audit(
        frame,
        rules_v1,
        rules_v2,
        champion,
        hedge_results,
        integrity,
        cycles,
        exposure,
        data_contract,
    )
    (artifact_dir / "no_lookahead_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not audit["pass"]:
        raise RuntimeError(f"V2 audit failed; performance verdict withheld: {audit}")

    create_v2_figures(V2_DIR, daily_by_strategy)
    verdict = write_v2_report(
        V2_DIR,
        summary,
        histories,
        daily_by_strategy,
        cycles,
        exposure,
        integrity,
        audit,
    )
    analysis_log = f"""# V2 analysis log

## Accepted patterns

- V1 Model A was called directly and its normal-DCA schedule was replayed exactly in every Model E run.
- Formal performance was reinitialized at 2020-01-01; 2019 was warm-up only.
- Daily signals executed no earlier than the next available 4H open.
- Sell stages, drift-band maintenance, one-shot buybacks, NEW_BULL deployment, and reset state are explicit and audited.
- Only the frozen E20/E30/E40 floor comparison was run.

## Rejected patterns

- Dynamic DCA, annual rebalancing, cash protection, V1 Full Strategy, automated optimization, and choosing a floor then rerunning rules were not used.
- An always-on daily hard-floor rebalance was rejected because it would add an unfrozen forced-buy rule. The hard floor constrains tactical sells; mark-to-market breaches are disclosed.

## Gates

- Audit pass: {audit['pass']}
- Fixed-DCA mismatch rows: {audit['fixed_dca_integrity_mismatch_rows']}
- Prefix invariant: {audit['prefix_invariance']['prefix_trades_identical']}
- Final verdict: {verdict}
"""
    (artifact_dir / "analysis_log_v2.md").write_text(analysis_log, encoding="utf-8")

    manifest = {
        "status": "COMPLETE",
        "strategy_version": rules_v2["strategy_version"],
        "command": "python run_backtest_v2.py",
        "python": sys.version,
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "seed": rules_v2["seed"],
        "config_v1_sha256": sha256_file(PROJECT_DIR / "config" / "frozen_rules.json"),
        "config_v2_sha256": sha256_file(PROJECT_DIR / "config" / "frozen_rules_v2.json"),
        "engine_v1_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        "engine_v2_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v2_engine.py"),
        "runner_sha256": sha256_file(PROJECT_DIR / "run_backtest_v2.py"),
        "data_contract": data_contract,
        "no_lookahead_and_state_audit": audit,
        "final_verdict": verdict,
        "file_sha256": hash_outputs(V2_DIR),
    }
    (artifact_dir / "run_manifest_v2.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "status": "COMPLETE",
                "audit_pass": True,
                "verdict": verdict,
                "summary": summary[
                    ["strategy", "final_portfolio_value", "time_weighted_cagr", "maximum_drawdown", "calmar"]
                ].to_dict("records"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
