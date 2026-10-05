from __future__ import annotations

import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "v3_4"
V31_DIR = PROJECT_DIR / "v3_1"
RAW_DIR = V31_DIR / "data" / "raw"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import build_common_4h_frame, read_csv_gz, sha256_file  # noqa: E402
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v31_indicators import build_v31_daily, merge_v31_features_to_bars  # noqa: E402
from crypto_backtest.v34_analysis import (  # noqa: E402
    build_no_lookahead_audit_v34,
    bull_participation_audit_v34,
    cash_reset_audit_v34,
    churn_audit_v34,
    comparison_and_promotion_v34,
    crash_false_positive_audit,
    crash_level3_audit,
    cycle_duration_audit_v34,
    daily_history_v34,
    event_window_audit_v34,
    fixed_dca_integrity,
    fsm_audit_v34,
    macro_bull_requalification_audit,
    prefix_trade_identity,
    summary_v34,
    v31_replay_integrity,
)
from crypto_backtest.v34_engine import run_initial_only, run_v34_backtest  # noqa: E402
from crypto_backtest.v34_indicators import add_v34_features  # noqa: E402
from crypto_backtest.v34_reporting import create_v34_figures, write_v34_report  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_scenario(model: str, rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "H0": "H0 Initial Only - No DCA / No Trading",
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM Frozen Champion",
        "F": "MODEL F - BTC+ETH Fixed DCA + V3.4 FINAL Challenger",
    }
    return V31Scenario(
        name=labels[model],
        model=model,
        use_fsm=model in {"B", "F"},
        use_ai=False,
        hard_floor=float(rules["hard_floor"]),
        initial_capital=float(rules["initial_capital"]),
        capital_test="v3_4_formal",
        variant="frozen",
        cost_case="v3_1_frozen",
        fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
    )


def add_identity(frame: pd.DataFrame, result: V31BacktestResult) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "model", result.scenario.model)
    out.insert(1, "strategy", result.scenario.name)
    return out


def load_formal_data(
    base_rules: dict[str, Any],
    primary_rules: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    paths = {
        "BTC_4h": RAW_DIR / "binance_BTCUSDT_4h.csv.gz",
        "ETH_4h": RAW_DIR / "binance_ETHUSDT_4h.csv.gz",
        "BTC_1d": RAW_DIR / "binance_BTCUSDT_1d.csv.gz",
        "ETH_1d": RAW_DIR / "binance_ETHUSDT_1d.csv.gz",
        "BITSTAMP_1d": RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz",
    }
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing frozen V3.1 inputs: {missing}")
    bars = {"BTC": read_csv_gz(paths["BTC_4h"]), "ETH": read_csv_gz(paths["ETH_4h"])}
    common, common_contract = build_common_4h_frame(bars)
    daily, source_switch = build_v31_daily(
        read_csv_gz(paths["BITSTAMP_1d"]),
        read_csv_gz(paths["BTC_1d"]),
        base_rules,
        primary_rules,
    )
    daily = add_v34_features(daily, rules)
    merged = merge_v31_features_to_bars(common, daily)
    formal_start = pd.Timestamp(rules["formal_start"])
    formal = merged.loc[merged["open_time"] >= formal_start].copy().reset_index(drop=True)
    required = [
        "open_time", "signal_date", "signal_available_at", "BTC_open", "BTC_close",
        "ETH_open", "ETH_close", "BTC_daily_close", "sma10", "sma20", "sma50", "sma200",
        "bb_lower", "ahr999_fixed_arithmetic", "distribution_confirmed", "early_bear_confirmed",
        "stage3_confirmed", "deep_bear_structural_confirmed", "crash_level1_raw",
        "crash_level2_market_raw", "right_50_confirmed", "right_60_confirmed",
        "new_bull_first_six", "deep_bear_exit_v34_confirmed", "btc_peak_to_close_dd_7d",
        "btc_peak_to_close_dd_10d", "crash_level3_price_raw", "crash_recovery_market_raw",
        "macro_bull_requalification_market_candidate", "macro_bull_candidate_confirmation_market",
        "macro_bull_new_bull_confirmation_market",
    ]
    nulls = {column: int(formal[column].isna().sum()) for column in required if column in formal}
    missing_columns = sorted(set(required) - set(formal.columns))
    used_dates = formal["signal_date"].dropna().unique()
    completed = daily.loc[daily["signal_date"].isin(used_dates)]
    future = sorted({"future_min_return_60d", "bear_label", "label_end_date"} & set(formal.columns))
    contract = {
        "source_switch_date": source_switch,
        "common_4h_contract": common_contract,
        "formal_start_requested": rules["formal_start"],
        "formal_start_actual": formal.iloc[0]["open_time"].isoformat(),
        "formal_end_actual": formal.iloc[-1]["open_time"].isoformat(),
        "formal_4h_rows": len(formal),
        "daily_rows": len(daily),
        "warmup_2019_rows": int(daily["signal_date"].between(
            pd.Timestamp("2019-01-01", tz="UTC"), formal_start, inclusive="left"
        ).sum()),
        "missing_required_columns": missing_columns,
        "required_null_counts": nulls,
        "duplicate_formal_timestamps": int(formal["open_time"].duplicated().sum()),
        "signal_availability_violations": int((formal["signal_available_at"] > formal["open_time"]).sum()),
        "completed_daily_candle_violations": int((completed["close_time"] >= completed["signal_available_at"]).sum()),
        "future_columns_in_execution_frame": future,
        "input_sha256": {
            path.relative_to(PROJECT_DIR).as_posix(): sha256_file(path) for path in paths.values()
        },
    }
    contract["pass"] = bool(
        not missing_columns
        and all(value == 0 for value in nulls.values())
        and contract["duplicate_formal_timestamps"] == 0
        and contract["signal_availability_violations"] == 0
        and contract["completed_daily_candle_violations"] == 0
        and not future
        and contract["warmup_2019_rows"] >= 365
        and formal.iloc[0]["open_time"] == formal_start
    )
    if not contract["pass"]:
        raise RuntimeError(f"V3.4 data contract failed: {contract}")
    source_manifest = pd.DataFrame([
        {
            "source_key": key,
            "path": path.relative_to(PROJECT_DIR).as_posix(),
            "sha256": sha256_file(path),
            "rows": len(read_csv_gz(path)),
            "inherited_from": "V3.1 frozen raw inputs",
        }
        for key, path in paths.items()
    ])
    return formal, daily, contract, source_manifest


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_4.json"
    }


def main() -> int:
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_4.json")
    primary_rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_1.json")
    base_rules = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    if not rules.get("frozen_before_formal_run"):
        raise RuntimeError("V3.4 config is not frozen")
    if sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_1.json") != rules["base_config_sha256"]:
        raise RuntimeError("Frozen V3.1 base config hash changed")

    frame, daily_features, data_contract, source_manifest = load_formal_data(
        base_rules, primary_rules, rules
    )
    model_h0 = run_initial_only(frame, primary_rules, make_scenario("H0", primary_rules))
    model_a = run_v31_backtest(frame, primary_rules, make_scenario("A", primary_rules))
    model_b = run_v31_backtest(
        frame, primary_rules, make_scenario("B", primary_rules), model_a=model_a
    )
    replay = v31_replay_integrity(model_b, V31_DIR, rules["reference_v31_b"])
    if not replay["pass"]:
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL: {replay}")
    model_f = run_v34_backtest(
        frame, primary_rules, rules, make_scenario("F", primary_rules), model_a=model_a
    )
    results = [model_h0, model_a, model_b, model_f]
    daily_by_model = {
        result.scenario.model: daily_history_v34(result.history) for result in results
    }
    summary = pd.DataFrame([summary_v34(result, primary_rules) for result in results])
    fixed_dca = fixed_dca_integrity(results)
    fsm = fsm_audit_v34(results, primary_rules)
    churn = churn_audit_v34(results)
    events = event_window_audit_v34(daily_by_model, results, rules["audit_windows"])
    crash_audit = crash_level3_audit(model_f)
    crash_false = crash_false_positive_audit(crash_audit, daily_by_model["F"], rules)
    requal = macro_bull_requalification_audit(model_f, daily_by_model["F"], rules)
    cycles = cycle_duration_audit_v34(results, daily_by_model, rules)
    cash_reset = cash_reset_audit_v34(model_f)
    participation = bull_participation_audit_v34(results, daily_by_model, rules)

    prefix_n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:prefix_n].copy()
    prefix_h0 = run_initial_only(prefix_frame, primary_rules, make_scenario("H0", primary_rules))
    prefix_a = run_v31_backtest(prefix_frame, primary_rules, make_scenario("A", primary_rules))
    prefix_b = run_v31_backtest(
        prefix_frame, primary_rules, make_scenario("B", primary_rules), model_a=prefix_a
    )
    prefix_f = run_v34_backtest(
        prefix_frame, primary_rules, rules, make_scenario("F", primary_rules), model_a=prefix_a
    )
    prefix_cutoff = pd.Timestamp(prefix_frame.iloc[-1]["open_time"])
    prefix_checks = {
        "model_h0_trade_prefix_identical": prefix_trade_identity(model_h0, prefix_h0, prefix_cutoff),
        "model_a_trade_prefix_identical": prefix_trade_identity(model_a, prefix_a, prefix_cutoff),
        "model_b_trade_prefix_identical": prefix_trade_identity(model_b, prefix_b, prefix_cutoff),
        "model_f_trade_prefix_identical": prefix_trade_identity(model_f, prefix_f, prefix_cutoff),
    }
    engine_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v34_engine.py").read_text(encoding="utf-8")
    indicator_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v34_indicators.py").read_text(encoding="utf-8")
    audit = build_no_lookahead_audit_v34(
        frame,
        daily_features,
        results,
        data_contract,
        fixed_dca,
        fsm,
        replay,
        cash_reset,
        prefix_checks,
        engine_source,
        indicator_source,
    )
    fsm_pass = bool(not fsm.empty and fsm["legal_transition"].all())
    fixed_dca_pass = bool(fixed_dca["all_match"].all())
    comparison, verdict = comparison_and_promotion_v34(
        summary,
        churn,
        events,
        participation,
        cycles,
        cash_reset,
        rules,
        replay_pass=bool(replay["pass"]),
        fixed_dca_pass=fixed_dca_pass,
        no_lookahead_pass=bool(audit["no_lookahead_pass"]),
        execution_pass=bool(audit["execution_integrity_pass"]),
        fsm_pass=fsm_pass,
    )

    result_dir = OUTPUT_DIR / "results"
    artifact_dir = OUTPUT_DIR / "artifacts"
    report_dir = OUTPUT_DIR / "report"
    figure_dir = OUTPUT_DIR / "figures"
    for directory in (result_dir, artifact_dir, report_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(
        PROJECT_DIR / "config" / "config_frozen_v3_4.json",
        OUTPUT_DIR / "config_frozen_v3_4.json",
    )
    source_manifest.to_csv(artifact_dir / "source_manifest_v3_4.csv", index=False)

    daily_all = pd.concat([
        add_identity(daily_by_model[result.scenario.model], result) for result in results
    ], ignore_index=True, sort=False)
    trades = pd.concat([result.trades for result in results], ignore_index=True, sort=False)
    regimes = pd.concat([model_b.signals, model_f.signals], ignore_index=True, sort=False)
    raw_cycles = pd.concat([
        add_identity(result.cycles, result)
        for result in (model_b, model_f) if not result.cycles.empty
    ], ignore_index=True, sort=False)
    summary.to_csv(result_dir / "summary_v3_4.csv", index=False)
    daily_all.to_csv(result_dir / "daily_portfolio_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    regimes.to_csv(result_dir / "regime_log_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    raw_cycles.to_csv(result_dir / "cycle_log_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    crash_audit.to_csv(result_dir / "crash_level3_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    crash_false.to_csv(result_dir / "crash_false_positive_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    requal.to_csv(result_dir / "macro_bull_requalification_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_duration_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cash_reset.to_csv(result_dir / "cash_reset_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    churn.to_csv(result_dir / "fsm_churn_audit_v3_4.csv", index=False)
    participation.to_csv(result_dir / "bull_participation_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fixed_dca.to_csv(result_dir / "fixed_dca_row_integrity_v3_4.csv", index=False)
    fsm.to_csv(result_dir / "fsm_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    events.to_csv(result_dir / "event_window_audit_v3_4.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    comparison.to_csv(result_dir / "model_comparison_v3_4.csv", index=False)

    (artifact_dir / "data_contract_v3_4.json").write_text(json.dumps(data_contract, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "v3_1_replay_integrity_v3_4.json").write_text(json.dumps(replay, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "no_lookahead_audit_v3_4.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "execution_integrity_v3_4.json").write_text(json.dumps({
        "pass": bool(audit["execution_integrity_pass"]),
        "fixed_dca_row_integrity": fixed_dca_pass,
        "v3_1_replay_integrity": bool(replay["pass"]),
        "fsm_audit": fsm_pass,
        "cash_reset_audit": bool(audit["cash_reset_integrity_pass"]),
        "prefix_invariance": prefix_checks,
    }, indent=2), encoding="utf-8")
    (artifact_dir / "promotion_verdict_v3_4.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    create_v34_figures(OUTPUT_DIR, daily_by_model, model_b, model_f)
    write_v34_report(
        OUTPUT_DIR, summary, comparison, verdict, events, crash_audit, crash_false,
        requal, cycles, cash_reset, churn, participation, audit,
    )
    analysis_log = """# V3.4 analysis log

## Accepted
- Frozen V3.1 A/B exact replay and isolated V3.4 F engine.
- Completed-daily, next-common-4H Crash L3, Macro Bull Requalification, Final Cash Sweep, and V3.3 BEAR/DEEP_BEAR hysteresis only.
- Exact Fixed-DCA ledger replay, prefix invariance, per-event audits, and post-backtest-only promotion evaluation.

## Rejected before formal execution
- V3.3 accumulation drift cap, V3.2 acceleration/recovery changes, AI, BNB, dynamic DCA, portfolio-drawdown trading, date-specific trading code, parameter search, and performance-aware decisions.

## Non-applicable skill artifacts
- Regression tables, standard errors, and causal treatment effects are not applicable to this deterministic historical backtest. Exact replay, pathwise ledger tests, event-window diagnostics, prefix invariance, CSV/JSON audits, and seven PNG/PDF figures are the relevant evidence bundle.
"""
    (artifact_dir / "analysis_log_v3_4.md").write_text(analysis_log, encoding="utf-8")
    readme = """# BTC+ETH Macro Hedge V3.4 FINAL

Run from the project root with `.venv\\Scripts\\python.exe run_backtest_v3_4.py`.

V3.1 Model B is replayed through the unchanged V3.1 engine. Model F is isolated in `v34_engine.py` and contains only the frozen V3.4 patches plus V3.3 state hysteresis. Promotion gates are post-backtest diagnostics.
"""
    (OUTPUT_DIR / "README_V3_4.md").write_text(readme, encoding="utf-8")

    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python run_backtest_v3_4.py",
        "python": sys.version,
        "platform": platform.platform(),
        "package_versions": {
            "numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__
        },
        "config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_4.json"),
        "base_v31_config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_1.json"),
        "formal_start": data_contract["formal_start_actual"],
        "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "no_lookahead_pass": audit["no_lookahead_pass"],
        "execution_integrity_pass": audit["execution_integrity_pass"],
        "v3_1_replay_integrity_pass": replay["pass"],
        "fixed_dca_row_integrity_pass": fixed_dca_pass,
        "fsm_audit_pass": fsm_pass,
        "cash_reset_audit_pass": audit["cash_reset_integrity_pass"],
        "code_sha256": {
            path.relative_to(PROJECT_DIR).as_posix(): sha256_file(path)
            for path in [
                PROJECT_DIR / "run_backtest_v3_4.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v34_indicators.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v34_engine.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v34_analysis.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v34_reporting.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v31_engine.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v31_indicators.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "data.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "metrics.py",
            ]
        },
        "promotion_verdict": verdict,
        "output_sha256": output_hashes(OUTPUT_DIR),
    }
    (artifact_dir / "run_manifest_v3_4.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(summary[[
        "model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"
    ]].to_string(index=False))
    print(json.dumps(verdict, indent=2))
    print(
        f"NO_LOOK_AHEAD={audit['no_lookahead_pass']} "
        f"EXECUTION_INTEGRITY={audit['execution_integrity_pass']} "
        f"V3_1_REPLAY_INTEGRITY={replay['pass']} "
        f"CASH_RESET={audit['cash_reset_integrity_pass']}"
    )
    return 0 if audit["no_lookahead_pass"] and audit["execution_integrity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
