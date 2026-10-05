from __future__ import annotations

import copy
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
OUTPUT_DIR = PROJECT_DIR / "v3_6"
V31_DIR = PROJECT_DIR / "v3_1"
RAW_DIR = V31_DIR / "data" / "raw"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import build_common_4h_frame, read_csv_gz, sha256_file  # noqa: E402
from crypto_backtest.v31_analysis import prefix_trade_identity  # noqa: E402
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v31_indicators import build_v31_daily, merge_v31_features_to_bars  # noqa: E402
from crypto_backtest.v36_analysis import (  # noqa: E402
    bottom_whipsaw_audit,
    bottom_whipsaw_summary,
    daily_history_v36,
    event_drawdown_audit,
    fixed_dca_integrity,
    fsm_audit,
    no_lookahead_audit,
    promotion_evaluation,
    summary_v36,
    tactical_statistics,
    v31_replay_integrity,
)
from crypto_backtest.v36_engine import run_v36_backtest  # noqa: E402
from crypto_backtest.v36_indicators import add_v36_features  # noqa: E402
from crypto_backtest.v36_reporting import create_v36_figures, write_v36_report  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def make_scenario(model: str, base_rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "H0": "H0 - Initial allocation only",
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - V3.1 FSM-only Frozen Champion",
        "H": "MODEL H - V3.6 V3.1 + Isolated Anti-Whipsaw Lite",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "H"}, use_ai=False,
        hard_floor=float(base_rules["hard_floor"]),
        initial_capital=float(base_rules["initial_capital"]),
        capital_test="v3_6_formal", variant="frozen", cost_case="v3_1_frozen",
        fee=float(base_rules["costs"]["fee"]), slippage=float(base_rules["costs"]["slippage"]),
    )


def run_initial_only(frame: pd.DataFrame, base_rules: dict[str, Any]) -> V31BacktestResult:
    zero_rules = copy.deepcopy(base_rules)
    zero_rules["external_contribution_per_4h"] = 0.0
    temp = make_scenario("H0", base_rules)
    engine_scenario = V31Scenario(
        name=temp.name, model="A", use_fsm=False, use_ai=False, hard_floor=temp.hard_floor,
        initial_capital=temp.initial_capital, capital_test=temp.capital_test,
        variant=temp.variant, cost_case=temp.cost_case, fee=temp.fee, slippage=temp.slippage,
    )
    result = run_v31_backtest(frame, zero_rules, engine_scenario)
    result.scenario = temp
    result.trades.loc[:, "model"] = "H0"
    result.trades.loc[:, "strategy"] = temp.name
    return result


def load_formal_data(
    base_rules: dict[str, Any], rules: dict[str, Any], source_manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    for row in source_manifest.itertuples():
        path = PROJECT_DIR / str(row.path)
        if not path.exists() or sha256_file(path) != str(row.sha256):
            raise RuntimeError(f"Frozen source hash mismatch: {path}")
    bars = {
        asset: read_csv_gz(RAW_DIR / f"binance_{symbol}_4h.csv.gz")
        for asset, symbol in base_rules["symbols"].items()
    }
    daily_btc = read_csv_gz(RAW_DIR / "binance_BTCUSDT_1d.csv.gz")
    bitstamp = read_csv_gz(RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz")
    common, common_contract = build_common_4h_frame(bars)
    daily_v31, source_switch = build_v31_daily(bitstamp, daily_btc, load_json(PROJECT_DIR / "config" / "frozen_rules.json"), base_rules)
    daily = add_v36_features(daily_v31, rules)
    merged = merge_v31_features_to_bars(common, daily)
    formal_start = pd.Timestamp(base_rules["formal_start"])
    formal = merged.loc[merged["open_time"] >= formal_start].copy().reset_index(drop=True)
    required = [
        "open_time", "signal_date", "signal_available_at", "BTC_open", "BTC_close",
        "ETH_open", "ETH_close", "BTC_daily_close", "sma10", "sma20", "sma50", "sma200",
        "ahr999_fixed_arithmetic", "distribution_confirmed", "early_bear_confirmed",
        "stage3_confirmed", "deep_bear_structural_confirmed", "confirmed_lower_low",
        "right_50_confirmed", "right_60_confirmed", "new_20d_closing_low",
        "no_new_20d_closing_low_recent3",
    ]
    missing = sorted(set(required) - set(formal.columns))
    nulls = {column: int(formal[column].isna().sum()) for column in required if column in formal}
    used_dates = formal["signal_date"].dropna().unique()
    completed = daily.loc[daily["signal_date"].isin(used_dates)]
    future = sorted(set(["bear_label", "future_min_return_60d", "label_end_date"]) & set(formal.columns))
    contract = {
        "source_switch_date": source_switch, "common_4h_contract": common_contract,
        "formal_start_requested": base_rules["formal_start"],
        "formal_start_actual": formal.iloc[0]["open_time"].isoformat(),
        "formal_end_actual": formal.iloc[-1]["open_time"].isoformat(),
        "formal_4h_rows": len(formal), "daily_rows": len(daily),
        "warmup_2019_rows": int(daily["signal_date"].between(
            pd.Timestamp("2019-01-01", tz="UTC"), formal_start, inclusive="left"
        ).sum()),
        "missing_required_columns": missing, "required_null_counts": nulls,
        "duplicate_formal_timestamps": int(formal["open_time"].duplicated().sum()),
        "signal_availability_violations": int((formal["signal_available_at"] > formal["open_time"]).sum()),
        "completed_daily_candle_violations": int((completed["close_time"] >= completed["signal_available_at"]).sum()),
        "future_label_columns_in_execution_frame": future,
        "input_sha256": dict(zip(source_manifest["path"], source_manifest["sha256"])),
    }
    contract["pass"] = bool(
        not missing and all(value == 0 for value in nulls.values())
        and contract["duplicate_formal_timestamps"] == 0
        and contract["signal_availability_violations"] == 0
        and contract["completed_daily_candle_violations"] == 0
        and not future and contract["warmup_2019_rows"] >= 365
        and formal.iloc[0]["open_time"] == formal_start
    )
    if not contract["pass"]:
        raise RuntimeError(f"V3.6 data contract failed: {contract}")
    return formal, daily, contract


def add_identity(frame: pd.DataFrame, result: V31BacktestResult) -> pd.DataFrame:
    out = frame.copy()
    if "model" not in out:
        out.insert(0, "model", result.scenario.model)
    if "strategy" not in out:
        out.insert(1, "strategy", result.scenario.name)
    return out


def tactical_event_frame(results: list[V31BacktestResult]) -> pd.DataFrame:
    frames = []
    for result in results:
        if result.scenario.model not in {"B", "H"}:
            continue
        tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
        if tactical.empty:
            continue
        events = tactical.groupby(["model", "tactical_event_id"], as_index=False).agg(
            timestamp=("timestamp", "first"), side=("side", "first"), action=("action", "first"),
            gross_notional_usd=("gross_notional_usd", "sum"),
        )
        frames.append(events)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_6.json"
    }


def main() -> int:
    config_path = PROJECT_DIR / "config" / "config_frozen_v3_6.json"
    base_path = PROJECT_DIR / "config" / "config_frozen_v3_1.json"
    rules = load_json(config_path)
    base_rules = load_json(base_path)
    if not rules.get("frozen_before_formal_run") or not rules.get("forbid_parameter_search"):
        raise RuntimeError("V3.6 was not frozen before formal execution")
    if sha256_file(base_path) != rules["base_config_sha256"]:
        raise RuntimeError("V3.1 frozen base config changed; V3.6 stopped")
    source_manifest = pd.read_csv(V31_DIR / "artifacts" / "source_manifest_v3_1.csv")
    frame, daily_features, data_contract = load_formal_data(base_rules, rules, source_manifest)

    model_h0 = run_initial_only(frame, base_rules)
    model_a = run_v31_backtest(frame, base_rules, make_scenario("A", base_rules))
    model_b = run_v31_backtest(frame, base_rules, make_scenario("B", base_rules), model_a=model_a)
    replay = v31_replay_integrity(model_b, V31_DIR, rules["reference_v31_b"])
    if not replay["pass"]:
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL; formal challenger not run: {replay}")
    model_h = run_v36_backtest(
        frame, base_rules, rules, make_scenario("H", base_rules), model_a=model_a
    )
    results = [model_h0, model_a, model_b, model_h]

    prefix_n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:prefix_n].copy()
    prefix_h0 = run_initial_only(prefix_frame, base_rules)
    prefix_a = run_v31_backtest(prefix_frame, base_rules, make_scenario("A", base_rules))
    prefix_b = run_v31_backtest(prefix_frame, base_rules, make_scenario("B", base_rules), model_a=prefix_a)
    prefix_h = run_v36_backtest(
        prefix_frame, base_rules, rules, make_scenario("H", base_rules), model_a=prefix_a
    )
    cutoff = pd.Timestamp(prefix_frame.iloc[-1]["open_time"])
    prefix_checks = {
        "model_h0_trade_prefix_identical": prefix_trade_identity(model_h0, prefix_h0, cutoff),
        "model_a_trade_prefix_identical": prefix_trade_identity(model_a, prefix_a, cutoff),
        "model_b_trade_prefix_identical": prefix_trade_identity(model_b, prefix_b, cutoff),
        "model_h_trade_prefix_identical": prefix_trade_identity(model_h, prefix_h, cutoff),
    }

    daily_by_model = {result.scenario.model: daily_history_v36(result.history) for result in results}
    summary = pd.DataFrame([summary_v36(result, base_rules) for result in results])
    fixed_dca = fixed_dca_integrity(results)
    fsm = fsm_audit(results, base_rules)
    bottom_audit = bottom_whipsaw_audit(results, daily_features)
    bottom_summary = bottom_whipsaw_summary(bottom_audit, daily_by_model, rules["audit_windows"])
    tactical_stats = tactical_statistics(results)
    event_audit = event_drawdown_audit(daily_by_model, results, rules["audit_windows"])
    engine_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v36_engine.py").read_text(encoding="utf-8")
    indicator_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v36_indicators.py").read_text(encoding="utf-8")
    integrity = no_lookahead_audit(
        frame, daily_features, results, data_contract, fixed_dca, fsm, replay,
        prefix_checks, engine_source, indicator_source,
    )
    all_integrity = bool(
        integrity["no_lookahead_pass"] and integrity["execution_integrity_pass"]
        and replay["pass"] and fixed_dca["all_match"].all() and fsm["legal_transition"].all()
    )
    comparison, verdict = promotion_evaluation(
        summary, bottom_summary, event_audit, tactical_stats, rules, integrity_pass=all_integrity
    )

    result_dir, artifact_dir = OUTPUT_DIR / "results", OUTPUT_DIR / "artifacts"
    for directory in (result_dir, artifact_dir, OUTPUT_DIR / "report", OUTPUT_DIR / "figures"):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(config_path, OUTPUT_DIR / "config_frozen_v3_6.json")
    source_manifest.to_csv(artifact_dir / "source_manifest_v3_6.csv", index=False)
    daily_all = pd.concat([add_identity(daily_by_model[result.scenario.model], result) for result in results], ignore_index=True, sort=False)
    trades = pd.concat([result.trades for result in results], ignore_index=True, sort=False)
    regimes = pd.concat([model_b.signals, model_h.signals], ignore_index=True, sort=False)
    transitions = pd.concat([add_identity(model_b.transitions, model_b), add_identity(model_h.transitions, model_h)], ignore_index=True, sort=False)
    cycles = pd.concat([add_identity(model_b.cycles, model_b), add_identity(model_h.cycles, model_h)], ignore_index=True, sort=False)
    tactical_events = tactical_event_frame(results)

    summary.to_csv(result_dir / "summary_v3_6.csv", index=False)
    daily_all.to_csv(result_dir / "daily_portfolio_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    regimes.to_csv(result_dir / "regime_log_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    transitions.to_csv(result_dir / "fsm_transition_log_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_log_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fixed_dca.to_csv(result_dir / "fixed_dca_row_integrity_v3_6.csv", index=False)
    fsm.to_csv(result_dir / "fsm_audit_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom_audit.to_csv(result_dir / "bottom_whipsaw_audit_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    bottom_summary.to_csv(result_dir / "bottom_whipsaw_summary_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    tactical_stats.to_csv(result_dir / "tactical_statistics_v3_6.csv", index=False)
    tactical_events.to_csv(result_dir / "tactical_event_log_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    event_audit.to_csv(result_dir / "event_drawdown_audit_v3_6.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    comparison.to_csv(result_dir / "model_comparison_v3_6.csv", index=False)

    (artifact_dir / "data_contract_v3_6.json").write_text(json.dumps(data_contract, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "v3_1_replay_integrity_v3_6.json").write_text(json.dumps(replay, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "no_lookahead_audit_v3_6.json").write_text(json.dumps(integrity, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "execution_integrity_v3_6.json").write_text(json.dumps({
        "pass": all_integrity, "prefix_invariance": prefix_checks,
        "fixed_dca_row_integrity": bool(fixed_dca["all_match"].all()),
        "fsm_audit": bool(fsm["legal_transition"].all()),
        "v3_1_replay": bool(replay["pass"]),
        "same_timestamp_opposite_action_violations": integrity["same_timestamp_opposite_tactical_action_violations"],
    }, indent=2), encoding="utf-8")
    (artifact_dir / "promotion_verdict_v3_6.json").write_text(json.dumps(verdict, indent=2), encoding="utf-8")
    (artifact_dir / "analysis_log_v3_6.md").write_text(
        "# V3.6 analysis log\n\nThe V3.1 base and the isolated Anti-Whipsaw Lite rules were frozen before execution. "
        "All performance thresholds were evaluated only after the histories and trade ledgers were complete. "
        "No search or post-result threshold change was performed.\n",
        encoding="utf-8",
    )

    create_v36_figures(OUTPUT_DIR, daily_by_model, bottom_audit, tactical_events)
    write_v36_report(
        OUTPUT_DIR, summary, comparison, verdict, bottom_summary, tactical_stats,
        event_audit, integrity, replay,
    )
    (OUTPUT_DIR / "README_V3_6.md").write_text(
        "# BTC+ETH Macro Hedge V3.6\n\nRun with `.venv\\Scripts\\python.exe run_backtest_v3_6.py`. "
        "Model H imports the V3.1 engine only and adds the frozen buy-frequency guard.\n",
        encoding="utf-8",
    )
    manifest = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": ".venv\\Scripts\\python.exe run_backtest_v3_6.py",
        "python": sys.version, "platform": platform.platform(),
        "package_versions": {"numpy": np.__version__, "pandas": pd.__version__, "matplotlib": matplotlib.__version__},
        "config_sha256": sha256_file(config_path), "base_v31_config_sha256": sha256_file(base_path),
        "formal_start": data_contract["formal_start_actual"], "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "v3_1_replay_integrity_pass": replay["pass"],
        "fixed_dca_row_integrity_pass": bool(fixed_dca["all_match"].all()),
        "no_lookahead_pass": integrity["no_lookahead_pass"],
        "execution_integrity_pass": integrity["execution_integrity_pass"],
        "fsm_audit_pass": bool(fsm["legal_transition"].all()),
        "verdict": verdict, "output_sha256": output_hashes(OUTPUT_DIR),
    }
    (artifact_dir / "run_manifest_v3_6.json").write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
    print(summary[["model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover", "tactical_event_count"]].to_string(index=False))
    print(json.dumps(verdict, indent=2))
    print(f"NO_LOOK_AHEAD={integrity['no_lookahead_pass']} EXECUTION_INTEGRITY={integrity['execution_integrity_pass']} V3_1_REPLAY={replay['pass']}")
    return 0 if all_integrity else 2


if __name__ == "__main__":
    raise SystemExit(main())
