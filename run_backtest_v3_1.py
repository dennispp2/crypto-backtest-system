from __future__ import annotations

import argparse
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
import sklearn
import xgboost


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "v3_1"
RAW_DIR = OUTPUT_DIR / "data" / "raw"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import (  # noqa: E402
    binance_server_time_ms,
    build_common_4h_frame,
    download_binance_klines,
    download_bitstamp_daily,
    read_csv_gz,
    sha256_file,
    write_csv_gz,
)
from crypto_backtest.v31_ai import annual_walk_forward_predictions  # noqa: E402
from crypto_backtest.v31_analysis import (  # noqa: E402
    audit_cases,
    build_ai_metrics,
    build_comparison_and_gates,
    buyback_forward_excursions,
    cash_audit,
    cycle_frequency,
    daily_history_v31,
    enriched_summary,
    fixed_dca_integrity,
    fsm_audit,
    no_lookahead_audit,
    prefix_trade_identity,
)
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v31_indicators import build_v31_daily, merge_v31_features_to_bars  # noqa: E402
from crypto_backtest.v31_reporting import create_v31_figures, write_v31_report  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _raw_paths(rules: dict[str, Any]) -> list[Path]:
    paths = [RAW_DIR / f"binance_{symbol}_{interval}.csv.gz" for symbol in rules["symbols"].values() for interval in ("4h", "1d")]
    return [*paths, RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz"]


def prepare_raw_data(rules: dict[str, Any], *, refresh: bool) -> pd.DataFrame:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    paths = _raw_paths(rules)
    if not refresh and not all(path.exists() for path in paths):
        source = PROJECT_DIR / "data" / "raw"
        for path in paths:
            source_path = source / path.name
            if not source_path.exists():
                raise FileNotFoundError(f"Missing frozen input {source_path}")
            shutil.copy2(source_path, path)
    retrieved = datetime.now(timezone.utc).isoformat()
    server_ms = binance_server_time_ms() if refresh else None
    if refresh:
        start_ms = int(pd.Timestamp("2017-08-01T00:00:00Z").timestamp() * 1000)
        for asset, symbol in rules["symbols"].items():
            for interval in ("4h", "1d"):
                data = download_binance_klines(symbol, interval, start_ms, int(server_ms))
                write_csv_gz(data, RAW_DIR / f"binance_{symbol}_{interval}.csv.gz")
        bitstamp = download_bitstamp_daily(
            int(pd.Timestamp(rules["extended_btc_start"]).timestamp()), int(server_ms) // 1000
        )
        server_time = pd.to_datetime(int(server_ms), unit="ms", utc=True)
        bitstamp = bitstamp.loc[bitstamp["close_time"] < server_time].copy()
        write_csv_gz(bitstamp, RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz")

    rows: list[dict[str, Any]] = []
    for asset, symbol in rules["symbols"].items():
        for interval in ("4h", "1d"):
            path = RAW_DIR / f"binance_{symbol}_{interval}.csv.gz"
            data = read_csv_gz(path)
            rows.append({
                "asset": asset, "source": "Binance Spot", "interval": interval,
                "start": data["open_time"].min(), "end": data["close_time"].max(),
                "rows": len(data), "retrieved_at": retrieved,
                "path": path.relative_to(PROJECT_DIR).as_posix(), "sha256": sha256_file(path),
            })
    path = RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz"
    data = read_csv_gz(path)
    rows.append({
        "asset": "BTC", "source": "Bitstamp BTCUSD", "interval": "1d",
        "start": data["open_time"].min(), "end": data["close_time"].max(),
        "rows": len(data), "retrieved_at": retrieved,
        "path": path.relative_to(PROJECT_DIR).as_posix(), "sha256": sha256_file(path),
    })
    manifest = pd.DataFrame(rows)
    artifact_dir = OUTPUT_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    manifest.to_csv(artifact_dir / "source_manifest_v3_1.csv", index=False)
    return manifest


def load_formal_data(
    rules: dict[str, Any], base_rules: dict[str, Any], manifest: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    bars = {
        asset: read_csv_gz(RAW_DIR / f"binance_{symbol}_4h.csv.gz")
        for asset, symbol in rules["symbols"].items()
    }
    daily_btc = read_csv_gz(RAW_DIR / "binance_BTCUSDT_1d.csv.gz")
    bitstamp = read_csv_gz(RAW_DIR / "bitstamp_BTCUSD_1d.csv.gz")
    common, common_contract = build_common_4h_frame(bars)
    daily_features, source_switch = build_v31_daily(bitstamp, daily_btc, base_rules, rules)
    formal_start = pd.Timestamp(rules["formal_start"])
    formal_end = pd.Timestamp(common["open_time"].max())
    predictions, training_audit = annual_walk_forward_predictions(
        daily_features, rules, formal_start, formal_end
    )
    ai_columns = [
        "signal_date", "training_cutoff", "training_rows", "training_positive_rows",
        "training_negative_rows", "ai_enabled", "feature_complete", "bear_risk",
        "model_version", "scale_pos_weight",
    ]
    daily_with_ai = daily_features.merge(
        predictions[ai_columns], on="signal_date", how="left", validate="one_to_one"
    )
    merged = merge_v31_features_to_bars(common, daily_with_ai)
    formal = merged.loc[merged["open_time"] >= formal_start].copy().reset_index(drop=True)
    required = [
        "open_time", "signal_date", "signal_available_at", "BTC_open", "BTC_close",
        "ETH_open", "ETH_close", "BTC_daily_close", "sma10", "sma20", "sma50",
        "sma200", "bb_mid", "bb_upper", "bb_lower", "ahr999_fixed_arithmetic",
        "bull_condition", "distribution_confirmed", "early_bear_confirmed",
        "stage3_confirmed", "deep_bear_structural_confirmed", "right_50_confirmed",
        "right_60_confirmed", *rules["ai"]["features"],
    ]
    missing = sorted(set(required) - set(formal.columns))
    nulls = {column: int(formal[column].isna().sum()) for column in required if column in formal}
    used_dates = formal["signal_date"].dropna().unique()
    completed = daily_features.loc[daily_features["signal_date"].isin(used_dates)]
    contract = {
        "manifest_rows": len(manifest), "source_switch_date": source_switch,
        "common_4h_contract": common_contract, "formal_start_requested": rules["formal_start"],
        "formal_start_actual": formal.iloc[0]["open_time"].isoformat(),
        "formal_end_actual": formal.iloc[-1]["open_time"].isoformat(),
        "formal_4h_rows": len(formal), "daily_rows": len(daily_features),
        "warmup_2019_rows": int(daily_features["signal_date"].between(
            pd.Timestamp("2019-01-01", tz="UTC"), formal_start, inclusive="left"
        ).sum()),
        "missing_required_columns": missing,
        "required_null_counts": nulls,
        "duplicate_formal_timestamps": int(formal["open_time"].duplicated().sum()),
        "signal_availability_violations": int((formal["signal_available_at"] > formal["open_time"]).sum()),
        "completed_daily_candle_violations": int((completed["close_time"] >= completed["signal_available_at"]).sum()),
        "future_label_columns_in_execution_frame": sorted(set(["bear_label", "future_min_return_60d", "label_end_date"]) & set(formal.columns)),
        "input_sha256": dict(zip(manifest["path"], manifest["sha256"])),
    }
    contract["pass"] = bool(
        not missing and all(value == 0 for value in nulls.values())
        and contract["duplicate_formal_timestamps"] == 0
        and contract["signal_availability_violations"] == 0
        and contract["completed_daily_candle_violations"] == 0
        and not contract["future_label_columns_in_execution_frame"]
        and contract["warmup_2019_rows"] >= 365
        and formal.iloc[0]["open_time"] == formal_start
    )
    if not contract["pass"]:
        raise RuntimeError(f"V3.1 data contract failed: {contract}")
    return formal, daily_features, predictions, training_audit, contract


def make_scenario(model: str, rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM",
        "C": "MODEL C - BTC+ETH Fixed DCA + V3.1 FSM + Bear Risk AI",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "C"}, use_ai=model == "C",
        hard_floor=float(rules["hard_floor"]), initial_capital=float(rules["initial_capital"]),
        fee=float(rules["costs"]["fee"]), slippage=float(rules["costs"]["slippage"]),
    )


def add_identity(frame: pd.DataFrame, model: str, strategy: str) -> pd.DataFrame:
    out = frame.copy()
    out.insert(0, "model", model)
    out.insert(1, "strategy", strategy)
    return out


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_1.json"
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen BTC+ETH V3.1 and annual OOS AI challenger")
    parser.add_argument("--refresh", action="store_true", help="Download fresh completed BTC/ETH data into v3_1/data/raw")
    args = parser.parse_args()
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_1.json")
    base_rules = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    if not rules.get("frozen_before_formal_run"):
        raise RuntimeError("V3.1 config is not marked frozen")

    manifest = prepare_raw_data(rules, refresh=args.refresh)
    frame, daily_features, predictions, training_audit, data_contract = load_formal_data(
        rules, base_rules, manifest
    )
    model_a = run_v31_backtest(frame, rules, make_scenario("A", rules))
    model_b = run_v31_backtest(frame, rules, make_scenario("B", rules), model_a=model_a)
    model_c = run_v31_backtest(frame, rules, make_scenario("C", rules), model_a=model_a)
    results = [model_a, model_b, model_c]

    daily_by_model = {result.scenario.model: daily_history_v31(result.history) for result in results}
    signals_by_model = {result.scenario.model: result.signals for result in results}
    summary = pd.DataFrame([enriched_summary(result, rules) for result in results])
    integrity = fixed_dca_integrity(results)
    fsm = fsm_audit(results, rules)
    frequency = cycle_frequency(results)
    temp_frames: list[pd.DataFrame] = []
    cycle_frames: list[pd.DataFrame] = []
    cash_event_frames: list[pd.DataFrame] = []
    for result in results:
        if not result.temporary_lots.empty:
            temp_frames.append(add_identity(result.temporary_lots, result.scenario.model, result.scenario.name))
        if not result.cycles.empty:
            cycles = add_identity(result.cycles, result.scenario.model, result.scenario.name)
            cycles["duration_days"] = (
                pd.to_datetime(cycles["end"], utc=True) - pd.to_datetime(cycles["start"], utc=True)
            ).dt.total_seconds() / 86_400.0
            cycle_frames.append(cycles)
        if not result.cash_events.empty:
            cash_event_frames.append(add_identity(result.cash_events.drop(columns=["strategy"], errors="ignore"), result.scenario.model, result.scenario.name))
    temp_lots = pd.concat(temp_frames, ignore_index=True) if temp_frames else pd.DataFrame(columns=["model", "strategy", "ever_over_30_without_bear"])
    cycles = pd.concat(cycle_frames, ignore_index=True) if cycle_frames else pd.DataFrame()
    cash_events = pd.concat(cash_event_frames, ignore_index=True) if cash_event_frames else pd.DataFrame()

    prefix_n = max(500, len(frame) // 2)
    prefix_frame = frame.iloc[:prefix_n].copy()
    prefix_a = run_v31_backtest(prefix_frame, rules, make_scenario("A", rules))
    prefix_b = run_v31_backtest(prefix_frame, rules, make_scenario("B", rules), model_a=prefix_a)
    prefix_c = run_v31_backtest(prefix_frame, rules, make_scenario("C", rules), model_a=prefix_a)
    cutoff = pd.Timestamp(prefix_frame.iloc[-1]["open_time"])
    prefix_checks = {
        "model_a_trade_prefix_identical": prefix_trade_identity(model_a, prefix_a, cutoff),
        "model_b_trade_prefix_identical": prefix_trade_identity(model_b, prefix_b, cutoff),
        "model_c_trade_prefix_identical": prefix_trade_identity(model_c, prefix_c, cutoff),
    }
    audit = no_lookahead_audit(
        frame, daily_features, predictions, training_audit, results,
        integrity, fsm, data_contract, prefix_checks, rules,
    )
    comparisons, verdict = build_comparison_and_gates(
        summary, frequency, temp_lots, bool(audit["pass"]), rules
    )
    ai_metrics = build_ai_metrics(predictions, float(rules["ai"]["high_risk_threshold"]))
    cases = audit_cases(daily_by_model, signals_by_model, rules["audit_windows"])
    buyback = buyback_forward_excursions(results, daily_features)

    c_signals = model_c.signals[[
        "signal_date", "state_after", "stage_after", "ai_intervention", "ai_intervention_reason"
    ]].copy()
    ai_predictions = predictions.merge(c_signals, on="signal_date", how="left", validate="one_to_one")
    ai_predictions = ai_predictions.rename(columns={
        "signal_date": "date", "close": "btc_close",
        "state_after": "fsm_state", "stage_after": "fsm_stage",
    })
    ai_columns = [
        "date", "prediction_available_at", "training_cutoff", "model_version", "btc_close",
        *rules["ai"]["features"], "bear_risk", "fsm_state", "fsm_stage",
        "ai_intervention", "ai_intervention_reason", "ai_enabled", "feature_complete",
        "training_rows", "training_positive_rows", "training_negative_rows", "scale_pos_weight",
        "bear_label", "label_end_date", "future_min_return_60d",
    ]
    ai_predictions = ai_predictions[ai_columns]
    interventions = ai_predictions.loc[ai_predictions["ai_intervention"].fillna("NONE").ne("NONE")].copy()

    result_dir = OUTPUT_DIR / "results"
    artifact_dir = OUTPUT_DIR / "artifacts"
    report_dir = OUTPUT_DIR / "report"
    figure_dir = OUTPUT_DIR / "figures"
    for directory in (result_dir, artifact_dir, report_dir, figure_dir):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_DIR / "config" / "config_frozen_v3_1.json", OUTPUT_DIR / "config_frozen_v3_1.json")

    daily = pd.concat([
        add_identity(daily_by_model[result.scenario.model], result.scenario.model, result.scenario.name)
        for result in results
    ], ignore_index=True)
    trades = pd.concat([result.trades for result in results], ignore_index=True)
    regimes = pd.concat([result.signals for result in results], ignore_index=True)
    cash_daily = cash_audit(daily_by_model)
    stage_special = regimes.loc[
        regimes["model"].isin(["B", "C"])
        & pd.to_datetime(regimes["signal_date"], utc=True).between(
            pd.Timestamp("2021-11-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC")
        )
    ].copy()
    cycle_start = pd.to_datetime(cycles["start"], utc=True, errors="coerce")
    cycle_end = pd.to_datetime(cycles["end"], utc=True, errors="coerce")
    special_cycles = cycles.loc[
        cycles["model"].isin(["B", "C"]) & cycles["confirmed"].astype(bool)
        & (cycle_start <= pd.Timestamp("2022-06-30", tz="UTC"))
        & (cycle_end >= pd.Timestamp("2021-11-01", tz="UTC"))
    ].copy()

    summary.to_csv(result_dir / "summary_v3_1.csv", index=False)
    daily.to_csv(result_dir / "daily_portfolio_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    regimes.to_csv(result_dir / "regime_log_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_log_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cash_daily.to_csv(result_dir / "cash_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    ai_predictions.to_csv(result_dir / "ai_predictions_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    ai_metrics.to_csv(result_dir / "ai_metrics_v3_1.csv", index=False)
    interventions.to_csv(result_dir / "ai_intervention_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    fsm.to_csv(result_dir / "fsm_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    comparisons.to_csv(result_dir / "model_comparison_v3_1.csv", index=False)
    integrity.to_csv(result_dir / "fixed_dca_row_integrity_v3_1.csv", index=False)
    frequency.to_csv(result_dir / "macro_cycle_frequency_v3_1.csv", index=False)
    temp_lots.to_csv(result_dir / "temporary_hedge_lot_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cash_events.to_csv(result_dir / "cash_ledger_events_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cases.to_csv(result_dir / "audit_cases_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    stage_special.to_csv(result_dir / "special_2021_2022_stage_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    special_cycles.to_csv(result_dir / "special_2021_2022_cycle_stage_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    buyback.to_csv(result_dir / "buyback_forward_10d_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    training_audit.to_csv(result_dir / "ai_training_audit_v3_1.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    (artifact_dir / "data_contract_v3_1.json").write_text(json.dumps(data_contract, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "no_lookahead_audit_v3_1.json").write_text(json.dumps(audit, indent=2, default=str), encoding="utf-8")
    (artifact_dir / "promotion_verdict_v3_1.json").write_text(json.dumps(verdict, indent=2, default=str), encoding="utf-8")

    create_v31_figures(OUTPUT_DIR, daily_by_model, signals_by_model, trades)
    write_v31_report(
        OUTPUT_DIR, summary, comparisons, verdict, ai_metrics, frequency,
        temp_lots, cases, cycles, interventions, audit, rules,
    )
    analysis_log = """# V3.1 analysis log

## Accepted
- Frozen two-asset 62.5/37.5 universe and exact Model-A DCA replay in B/C.
- Seven-state FSM, separate temporary/bear cash ownership, sell-time hard floor, and next-bar execution.
- Exactly seven XGBoost inputs and annual expanding-window training using matured labels only.

## Rejected
- BNB, dynamic DCA, date hard-coding, extra features/models, AI direct trading, parameter search, and post-result retuning.

## Scope
- This is a deterministic historical simulation plus annual OOS classifier diagnostics, not a causal estimate or future-return guarantee.
"""
    (artifact_dir / "analysis_log_v3_1.md").write_text(analysis_log, encoding="utf-8")

    manifest_out = {
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": "python run_backtest_v3_1.py" + (" --refresh" if args.refresh else ""),
        "python": sys.version, "platform": platform.platform(),
        "package_versions": {
            "numpy": np.__version__, "pandas": pd.__version__,
            "matplotlib": matplotlib.__version__, "scikit_learn": sklearn.__version__,
            "xgboost": xgboost.__version__,
        },
        "config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_1.json"),
        "formal_start": data_contract["formal_start_actual"],
        "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "no_lookahead_pass": audit["pass"], "fixed_dca_integrity_pass": audit["fixed_dca_row_integrity_pass"],
        "verdict": verdict, "output_sha256": output_hashes(OUTPUT_DIR),
    }
    (artifact_dir / "run_manifest_v3_1.json").write_text(
        json.dumps(manifest_out, indent=2, default=str), encoding="utf-8"
    )
    print(summary[["model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]].to_string(index=False))
    print(json.dumps(verdict, indent=2))
    print(f"NO_LOOK_AHEAD={audit['pass']} FIXED_DCA_ROW_INTEGRITY={audit['fixed_dca_row_integrity_pass']}")
    return 0 if audit["pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
