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
OUTPUT_DIR = PROJECT_DIR / "v3_5"
V31_DIR = PROJECT_DIR / "v3_1"
V34_DIR = PROJECT_DIR / "v3_4"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v34_engine import run_initial_only, run_v34_backtest  # noqa: E402
from crypto_backtest.v35_analysis import (  # noqa: E402
    bottom_action_audit,
    build_no_lookahead_audit_v35,
    bull_participation_audit_v35,
    cash_reset_audit_v35,
    comparison_and_promotion_v35,
    daily_history_v34,
    event_window_audit_v35,
    fixed_dca_integrity,
    fsm_audit_v35,
    prefix_trade_identity,
    summary_v34,
    v31_replay_integrity,
    v34_replay_integrity,
)
from crypto_backtest.v35_engine import run_v35_backtest  # noqa: E402
from crypto_backtest.v35_indicators import add_v35_features  # noqa: E402
from crypto_backtest.v35_reporting import create_v35_figures, write_v35_report  # noqa: E402
from run_backtest_v3_4 import load_formal_data as load_v34_formal_data  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_scenario(model: str, rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "H0": "H0 Initial Only - No DCA / No Trading",
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM Frozen Champion",
        "F": "MODEL F - BTC+ETH Fixed DCA + V3.4 FINAL Frozen Challenger",
        "G": "MODEL G - BTC+ETH Fixed DCA + V3.5 Patch D Challenger",
    }
    return V31Scenario(
        name=labels[model],
        model=model,
        use_fsm=model in {"B", "F", "G"},
        use_ai=False,
        hard_floor=float(rules["hard_floor"]),
        initial_capital=float(rules["initial_capital"]),
        capital_test="v3_5_formal",
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
    v34_rules: dict[str, Any],
    rules: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any], pd.DataFrame]:
    frame, daily_v34, contract, source_manifest = load_v34_formal_data(
        base_rules, primary_rules, v34_rules
    )
    daily_v35 = add_v35_features(daily_v34, v34_rules, rules)
    patch_columns = [
        "no_new_20d_low_5d", "no_new_20d_low_10d",
        "patch_d_close_above_sma20_3d", "patch_d_right_50_confirmed",
        "patch_d_close_above_sma50_5d", "patch_d_right_60_confirmed",
        "patch_d_hard_failure_raw", "patch_d_hard_failure_confirmed",
    ]
    frame = frame.drop(columns=[column for column in patch_columns if column in frame], errors="ignore").merge(
        daily_v35[["signal_date", *patch_columns]], on="signal_date", how="left", validate="many_to_one"
    )
    nulls = {column: int(frame[column].isna().sum()) for column in patch_columns}
    contract = {**contract, "patch_d_required_null_counts": nulls}
    contract["pass"] = bool(contract["pass"] and all(value == 0 for value in nulls.values()))
    if not contract["pass"]:
        raise RuntimeError(f"V3.5 data contract failed: {contract}")
    return frame, daily_v35, contract, source_manifest


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_5.json"
    }


def main() -> int:
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_5.json")
    v34_rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_4.json")
    primary_rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_1.json")
    base_rules = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    if not rules.get("frozen_before_formal_run"):
        raise RuntimeError("V3.5 config is not frozen")
    if sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_4.json") != rules["base_config_sha256"]:
        raise RuntimeError("Frozen V3.4 base config hash changed")

    frame, daily_features, data_contract, source_manifest = load_formal_data(
        base_rules, primary_rules, v34_rules, rules
    )
    model_h0 = run_initial_only(frame, primary_rules, make_scenario("H0", primary_rules))
    model_a = run_v31_backtest(frame, primary_rules, make_scenario("A", primary_rules))
    model_b = run_v31_backtest(frame, primary_rules, make_scenario("B", primary_rules), model_a=model_a)
    replay = v31_replay_integrity(model_b, V31_DIR, v34_rules["reference_v31_b"])
    if not replay["pass"]:
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL: {replay}")
    model_f = run_v34_backtest(
        frame, primary_rules, v34_rules, make_scenario("F", primary_rules), model_a=model_a
    )
    replay_v34 = v34_replay_integrity(model_f, V34_DIR, primary_rules)
    if not replay_v34["pass"]:
        raise RuntimeError(f"V3_4_REPLAY_INTEGRITY=FAIL: {replay_v34}")
    model_g = run_v35_backtest(
        frame, primary_rules, v34_rules, rules, make_scenario("G", primary_rules), model_a=model_a
    )
    results = [model_h0, model_a, model_b, model_f, model_g]
    daily_by_model = {result.scenario.model: daily_history_v34(result.history) for result in results}
    summary = pd.DataFrame([summary_v34(result, primary_rules) for result in results])
    fixed_dca = fixed_dca_integrity(results)
    fsm = fsm_audit_v35(results, primary_rules)
    events = event_window_audit_v35(daily_by_model, results, v34_rules["audit_windows"])
    bottom_audit, bottom_summary = bottom_action_audit(results, daily_by_model, rules)
    cash_reset = cash_reset_audit_v35(model_g)
    participation = bull_participation_audit_v35(results, daily_by_model)

    prefix_n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:prefix_n].copy()
    prefix_h0 = run_initial_only(prefix_frame, primary_rules, make_scenario("H0", primary_rules))
    prefix_a = run_v31_backtest(prefix_frame, primary_rules, make_scenario("A", primary_rules))
    prefix_b = run_v31_backtest(prefix_frame, primary_rules, make_scenario("B", primary_rules), model_a=prefix_a)
    prefix_f = run_v34_backtest(
        prefix_frame, primary_rules, v34_rules, make_scenario("F", primary_rules), model_a=prefix_a
    )
    prefix_g = run_v35_backtest(
        prefix_frame, primary_rules, v34_rules, rules, make_scenario("G", primary_rules), model_a=prefix_a
    )
    cutoff = pd.Timestamp(prefix_frame.iloc[-1]["open_time"])
    prefix_checks = {
        "model_h0_trade_prefix_identical": prefix_trade_identity(model_h0, prefix_h0, cutoff),
        "model_a_trade_prefix_identical": prefix_trade_identity(model_a, prefix_a, cutoff),
        "model_b_trade_prefix_identical": prefix_trade_identity(model_b, prefix_b, cutoff),
        "model_f_trade_prefix_identical": prefix_trade_identity(model_f, prefix_f, cutoff),
        "model_g_trade_prefix_identical": prefix_trade_identity(model_g, prefix_g, cutoff),
    }
    engine_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v35_engine.py").read_text(encoding="utf-8")
    indicator_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v35_indicators.py").read_text(encoding="utf-8")
    audit = build_no_lookahead_audit_v35(
        frame, daily_features, results, data_contract, fixed_dca, fsm, replay,
        prefix_checks, engine_source, indicator_source,
    )
    fsm_pass = bool(not fsm.empty and fsm["legal_transition"].all())
    fixed_dca_pass = bool(fixed_dca["all_match"].all())
    comparison, verdict = comparison_and_promotion_v35(
        summary, events, bottom_summary, participation, cash_reset, rules, v34_rules,
        no_lookahead_pass=bool(audit["no_lookahead_pass"]),
        execution_pass=bool(audit["execution_integrity_pass"]),
        replay_pass=bool(replay["pass"] and replay_v34["pass"]),
        fixed_dca_pass=fixed_dca_pass,
        fsm_pass=fsm_pass,
    )

    result_dir, artifact_dir = OUTPUT_DIR / "results", OUTPUT_DIR / "artifacts"
    for directory in (result_dir, artifact_dir, OUTPUT_DIR / "report", OUTPUT_DIR / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_DIR / "config" / "config_frozen_v3_5.json", OUTPUT_DIR / "config_frozen_v3_5.json")
    source_manifest.to_csv(artifact_dir / "source_manifest_v3_5.csv", index=False)
    daily_all = pd.concat([add_identity(daily_by_model[result.scenario.model], result) for result in results], ignore_index=True, sort=False)
    trades = pd.concat([result.trades for result in results], ignore_index=True, sort=False)
    regimes = pd.concat([model_b.signals, model_f.signals, model_g.signals], ignore_index=True, sort=False)
    cycles = pd.concat([add_identity(result.cycles, result) for result in (model_b, model_f, model_g) if not result.cycles.empty], ignore_index=True, sort=False)

    summary.to_csv(result_dir / "summary_v3_5.csv", index=False)
    daily_all.to_csv(result_dir / "daily_portfolio_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    regimes.to_csv(result_dir / "regime_log_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_log_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fixed_dca.to_csv(result_dir / "fixed_dca_row_integrity_v3_5.csv", index=False)
    fsm.to_csv(result_dir / "fsm_audit_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    events.to_csv(result_dir / "event_window_audit_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom_audit.to_csv(result_dir / "bottom_whipsaw_audit_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom_summary.to_csv(result_dir / "bottom_whipsaw_summary_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cash_reset.to_csv(result_dir / "cash_reset_audit_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    participation.to_csv(result_dir / "bull_participation_audit_v3_5.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    comparison.to_csv(result_dir / "model_comparison_v3_5.csv", index=False)

    (artifact_dir / "data_contract_v3_5.json").write_text(json.dumps(data_contract, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "v3_1_replay_integrity_v3_5.json").write_text(json.dumps(replay, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "v3_4_replay_integrity_v3_5.json").write_text(json.dumps(replay_v34, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "no_lookahead_audit_v3_5.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "execution_integrity_v3_5.json").write_text(json.dumps({
        "pass": bool(audit["execution_integrity_pass"]),
        "fixed_dca_row_integrity": fixed_dca_pass,
        "v3_1_replay_integrity": bool(replay["pass"]),
        "v3_4_replay_integrity": bool(replay_v34["pass"]),
        "fsm_audit": fsm_pass,
        "prefix_invariance": prefix_checks,
    }, indent=2), encoding="utf-8")
    (artifact_dir / "promotion_verdict_v3_5.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")

    create_v35_figures(OUTPUT_DIR, daily_by_model, bottom_audit)
    write_v35_report(
        OUTPUT_DIR, summary, comparison, verdict, bottom_summary, bottom_audit,
        events, audit, replay_v34,
    )
    (artifact_dir / "analysis_log_v3_5.md").write_text(
        "# V3.5 Patch D analysis log\n\n"
        "Patch D was frozen and isolated from V3.4. Audit windows and evaluation gates are not present in the trading engine. "
        "Exact V3.1 and V3.4 replay, prefix invariance, event-level ledgers, and post-backtest gate evaluation are the applicable evidence.\n",
        encoding="utf-8",
    )
    (OUTPUT_DIR / "README_V3_5.md").write_text(
        "# BTC+ETH Macro Hedge V3.5 — Patch D\n\n"
        "Run with `.venv\\Scripts\\python.exe run_backtest_v3_5.py`. "
        "V3.4 is replayed unchanged; Model G contains only the separately frozen accumulation anti-whipsaw patch.\n",
        encoding="utf-8",
    )

    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python run_backtest_v3_5.py",
        "python": sys.version,
        "platform": platform.platform(),
        "package_versions": {"numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__},
        "config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_5.json"),
        "base_v34_config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_4.json"),
        "formal_start": data_contract["formal_start_actual"],
        "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "no_lookahead_pass": audit["no_lookahead_pass"],
        "execution_integrity_pass": audit["execution_integrity_pass"],
        "v3_1_replay_integrity_pass": replay["pass"],
        "v3_4_replay_integrity_pass": replay_v34["pass"],
        "fixed_dca_row_integrity_pass": fixed_dca_pass,
        "fsm_audit_pass": fsm_pass,
        "code_sha256": {
            path.relative_to(PROJECT_DIR).as_posix(): sha256_file(path)
            for path in [
                PROJECT_DIR / "run_backtest_v3_5.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v35_indicators.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v35_engine.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v35_analysis.py",
                PROJECT_DIR / "src" / "crypto_backtest" / "v35_reporting.py",
            ]
        },
        "promotion_verdict": verdict,
        "output_sha256": output_hashes(OUTPUT_DIR),
    }
    (artifact_dir / "run_manifest_v3_5.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")

    print(summary[["model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]].to_string(index=False))
    print(bottom_summary.to_string(index=False))
    print(json.dumps(verdict, indent=2))
    print(
        f"NO_LOOK_AHEAD={audit['no_lookahead_pass']} "
        f"EXECUTION_INTEGRITY={audit['execution_integrity_pass']} "
        f"V3_1_REPLAY={replay['pass']} V3_4_REPLAY={replay_v34['pass']}"
    )
    return 0 if audit["no_lookahead_pass"] and audit["execution_integrity_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
