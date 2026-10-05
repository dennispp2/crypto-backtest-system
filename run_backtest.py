from __future__ import annotations

import argparse
import copy
import gzip
import hashlib
import json
import platform
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.analysis import (  # noqa: E402
    btc_extended_validation,
    cash_analysis,
    cycle_analysis,
    run_parameter_sensitivity,
    tactical_event_effectiveness,
)
from crypto_backtest.data import (  # noqa: E402
    acquire_raw_data,
    build_common_4h_frame,
    load_raw_bundle,
    sha256_file,
)
from crypto_backtest.engine import BacktestResult, Scenario, run_backtest  # noqa: E402
from crypto_backtest.indicators import (  # noqa: E402
    add_daily_indicators,
    build_primary_daily,
    merge_daily_signals_to_bars,
)
from crypto_backtest.metrics import daily_history  # noqa: E402
from crypto_backtest.reporting import (  # noqa: E402
    create_figures,
    write_final_report,
    write_run_manifest,
)


def load_rules() -> dict[str, Any]:
    return json.loads((PROJECT_DIR / "config" / "frozen_rules.json").read_text(encoding="utf-8"))


def write_gzip_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        df.to_csv(handle, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")


def prepare_data(rules: dict[str, Any], refresh: bool) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    source_manifest = acquire_raw_data(PROJECT_DIR, rules, refresh=refresh)
    bars_by_asset, daily_by_asset_raw, bitstamp = load_raw_bundle(PROJECT_DIR, rules)
    common, contract = build_common_4h_frame(bars_by_asset)
    primary_daily, switch_date = build_primary_daily(bitstamp, daily_by_asset_raw["BTC"], rules)
    asset_daily = {
        asset: add_daily_indicators(df, rules, include_ahr=False)
        for asset, df in daily_by_asset_raw.items()
    }
    frame = merge_daily_signals_to_bars(common, primary_daily, asset_daily)
    required = [
        "ahr999_fixed_arithmetic",
        "sma200",
        "signal_available_at",
        *[f"{asset}_open" for asset in rules["assets"]],
        *[f"{asset}_close" for asset in rules["assets"]],
    ]
    before = len(frame)
    frame = frame.dropna(subset=required).reset_index(drop=True)
    if frame.empty:
        raise RuntimeError("No common 4H bars remain after point-in-time signal warm-up")

    extended = add_daily_indicators(bitstamp, rules, include_ahr=True)
    write_gzip_csv(frame, PROJECT_DIR / "data" / "processed" / "backtest_4h_signals.csv.gz")
    write_gzip_csv(primary_daily, PROJECT_DIR / "data" / "processed" / "btc_primary_daily_signals.csv.gz")
    write_gzip_csv(extended, PROJECT_DIR / "data" / "processed" / "btc_extended_daily_signals.csv.gz")

    actual_start = frame["open_time"].min()
    expected = int((frame["open_time"].max() - actual_start) / pd.Timedelta(hours=4)) + 1
    source_days_before = int((actual_start.floor("D") - primary_daily["signal_date"].min()).days)
    contract.update(
        {
            "requested_primary_start": rules["requested_primary_start"],
            "actual_backtest_start": actual_start.isoformat(),
            "actual_backtest_end": frame["open_time"].max().isoformat(),
            "rows_before_signal_gate": before,
            "rows_after_signal_gate": len(frame),
            "expected_regular_4h_rows": expected,
            "missing_common_4h_rows": expected - len(frame),
            "calendar_4h_contribution_intervals": expected,
            "warmup_calendar_days_available": source_days_before,
            "warmup_requirement_days": rules["warmup_days"],
            "warmup_pass": source_days_before >= rules["warmup_days"],
            "btc_daily_source_switch_date": switch_date,
            "signal_availability_violations": int((frame["signal_available_at"] > frame["open_time"]).sum()),
            "requested_start_unavailable_reason": "BNBUSDT first Binance 4H bar is 2017-11-06; no synthetic BNB backfill",
        }
    )
    (PROJECT_DIR / "artifacts" / "data_contract.json").write_text(
        json.dumps(contract, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not contract["warmup_pass"]:
        raise RuntimeError(
            f"Indicator warm-up gate failed: {source_days_before} calendar days available, "
            f"requires at least {rules['warmup_days']}"
        )
    return frame, primary_daily, extended, source_manifest, contract


def make_scenario(
    rules: dict[str, Any],
    *,
    name: str,
    capital_test: str,
    cost_case: str = "primary",
    variant: str = "primary",
    cash_protection: bool = True,
    sell_order: str = "overweight",
) -> Scenario:
    initial = rules["initial_tests"][capital_test]
    cost = rules["costs"][cost_case]
    return Scenario(
        name=name,
        capital_test=capital_test,
        initial_capital=initial["initial_capital"],
        initial_crypto_fraction=initial["initial_crypto_fraction"],
        dynamic_dca=name in {"Benchmark C - Dynamic DCA", "Strategy D - Full"},
        tactical=name == "Strategy D - Full",
        annual_rebalance=name == "Benchmark B - Annual Rebalance",
        cash_protection=cash_protection,
        sell_order=sell_order,
        fee=cost["fee"],
        slippage=cost["slippage"],
        cost_case=cost_case,
        variant=variant,
    )


def run_scenarios(frame: pd.DataFrame, rules: dict[str, Any]) -> tuple[list[BacktestResult], dict[str, BacktestResult]]:
    names = [
        "Benchmark A - Fixed DCA",
        "Benchmark B - Annual Rebalance",
        "Benchmark C - Dynamic DCA",
        "Strategy D - Full",
    ]
    results: list[BacktestResult] = []
    chart_results: dict[str, BacktestResult] = {}
    for capital_test in ("test1", "test2"):
        for name in names:
            result = run_backtest(frame, rules, make_scenario(rules, name=name, capital_test=capital_test))
            results.append(result)
            if capital_test == "test2":
                chart_results[name] = result

    # Cash protection attribution and sell-order secondary test.
    results.append(
        run_backtest(
            frame,
            rules,
            make_scenario(
                rules,
                name="Strategy D - Full",
                capital_test="test2",
                variant="cash_protection_off",
                cash_protection=False,
            ),
        )
    )
    results.append(
        run_backtest(
            frame,
            rules,
            make_scenario(
                rules,
                name="Strategy D - Full",
                capital_test="test2",
                variant="overweight_plus_technical_weakness",
                sell_order="overweight_weakness",
            ),
        )
    )
    # Cost cases compare Full and Fixed at the same cost assumption.
    for cost_case in ("low", "high"):
        for name in ("Benchmark A - Fixed DCA", "Strategy D - Full"):
            results.append(
                run_backtest(
                    frame,
                    rules,
                    make_scenario(
                        rules,
                        name=name,
                        capital_test="test2",
                        cost_case=cost_case,
                        variant=f"{cost_case}_cost",
                    ),
                )
            )
    return results, chart_results


def combine_outputs(results: list[BacktestResult], chart_results: dict[str, BacktestResult]) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary = pd.DataFrame([r.summary for r in results])
    trade_frames: list[pd.DataFrame] = []
    daily_frames: list[pd.DataFrame] = []
    for result in results:
        trades = result.trades.copy()
        trade_frames.append(trades)
        daily = daily_history(result.history)
        daily.insert(0, "capital_test", result.scenario.capital_test)
        daily.insert(1, "strategy", result.scenario.name)
        daily.insert(2, "variant", result.scenario.variant)
        daily.insert(3, "cost_case", result.scenario.cost_case)
        daily_frames.append(daily)
    trades = pd.concat(trade_frames, ignore_index=True)
    daily_portfolio = pd.concat(daily_frames, ignore_index=True)
    signals = chart_results["Strategy D - Full"].signals.copy()
    signals.insert(0, "capital_test", "test2")
    signals.insert(1, "strategy", "Strategy D - Full")
    return summary, trades, daily_portfolio, signals


def prefix_invariance_audit(frame: pd.DataFrame, rules: dict[str, Any], full: BacktestResult) -> dict[str, Any]:
    n = min(5000, max(100, len(frame) // 3))
    prefix_scenario = full.scenario
    prefix = run_backtest(frame.iloc[:n].copy(), rules, prefix_scenario)
    end = frame.iloc[n - 1]["open_time"]
    full_trades = full.trades.loc[full.trades["timestamp"] <= end].copy()
    columns = ["timestamp", "action", "side", "asset", "quantity", "gross_notional_usd", "ledger"]
    left = prefix.trades[columns].copy().reset_index(drop=True)
    right = full_trades[columns].copy().reset_index(drop=True)
    for col in ("quantity", "gross_notional_usd"):
        left[col] = left[col].round(10)
        right[col] = right[col].round(10)
    equal = left.equals(right)
    return {
        "prefix_bars": n,
        "prefix_end": end.isoformat(),
        "prefix_trade_rows": len(left),
        "full_matching_trade_rows": len(right),
        "prefix_trades_identical": bool(equal),
    }


def no_lookahead_audit(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    results: list[BacktestResult],
    full: BacktestResult,
) -> dict[str, Any]:
    tactical = full.trades[full.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if not tactical.empty:
        available = pd.to_datetime(tactical["signal_date"], utc=True) + pd.Timedelta(days=1)
        tactical_violations = int((tactical["timestamp"] < available).sum())
    else:
        tactical_violations = 0
    summaries = pd.DataFrame([r.summary for r in results])
    primary = summaries[(summaries["variant"] == "primary") & (summaries["cost_case"] == "primary")]
    contribution_spreads = (
        primary.groupby("capital_test")["external_contributions"].agg(lambda x: float(x.max() - x.min())).to_dict()
    )
    expected_intervals = int((frame["open_time"].max() - frame["open_time"].min()) / pd.Timedelta(hours=4)) + 1
    expected_periodic = expected_intervals * float(rules["external_contribution_per_4h"])
    periodic_deviations = {
        r.scenario.capital_test + "|" + r.scenario.name + "|" + r.scenario.variant + "|" + r.scenario.cost_case:
        float(r.summary["periodic_external_contributions"] - expected_periodic)
        for r in results
    }
    normal_dca_wrong_ledger = int(
        sum(
            (
                (r.trades["action"].eq("NORMAL_DCA"))
                & (~r.trades["ledger"].eq("pending"))
            ).sum()
            for r in results
        )
    )
    tactical_buy_wrong_ledger = int(
        sum(
            (
                r.trades["action"].str.startswith("TACTICAL_BUYBACK", na=False)
                & (~r.trades["ledger"].eq("tactical"))
            ).sum()
            for r in results
        )
    )
    max_dca = max(float(r.history["theoretical_dca"].max()) for r in results)
    min_normal = min(float(r.history["normal_cash"].min()) for r in results)
    min_tactical = min(float(r.history["tactical_cash"].min()) for r in results)
    prefix = prefix_invariance_audit(frame, rules, full)
    audit = {
        "daily_signal_available_after_candle_close_violations": int(
            (frame["signal_available_at"] > frame["open_time"]).sum()
        ),
        "tactical_trade_before_signal_available_violations": tactical_violations,
        "normal_dca_wrong_ledger_count": normal_dca_wrong_ledger,
        "tactical_buy_wrong_ledger_count": tactical_buy_wrong_ledger,
        "max_theoretical_dca": max_dca,
        "dca_hard_cap": rules["dca_rates"]["hard_max"],
        "minimum_normal_cash": min_normal,
        "minimum_tactical_cash": min_tactical,
        "contribution_spread_by_capital_test": contribution_spreads,
        "expected_calendar_4h_intervals": expected_intervals,
        "expected_periodic_contributions_usd": expected_periodic,
        "periodic_contribution_deviation_by_run": periodic_deviations,
        "prefix_invariance": prefix,
    }
    audit["pass"] = bool(
        audit["daily_signal_available_after_candle_close_violations"] == 0
        and tactical_violations == 0
        and normal_dca_wrong_ledger == 0
        and tactical_buy_wrong_ledger == 0
        and max_dca <= rules["dca_rates"]["hard_max"] + 1e-12
        and min_normal >= -1e-8
        and min_tactical >= -1e-8
        and all(abs(v) <= 1e-8 for v in contribution_spreads.values())
        and all(abs(v) <= 1e-8 for v in periodic_deviations.values())
        and prefix["prefix_trades_identical"]
    )
    return audit


def file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for folder in ("config", "data", "results", "figures", "report", "artifacts"):
        for path in sorted((root / folder).rglob("*")):
            if path.is_file() and path.name != "run_manifest.json":
                hashes[path.relative_to(root).as_posix()] = sha256_file(path)
    return hashes


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the frozen no-look-ahead crypto backtest")
    parser.add_argument("--refresh-data", action="store_true", help="redownload raw public market data")
    parser.add_argument("--skip-sensitivity", action="store_true", help="development-only; final run must not use")
    args = parser.parse_args()
    rules = load_rules()
    frame, primary_daily, extended_daily, source_manifest, data_contract = prepare_data(rules, args.refresh_data)
    results, chart_results = run_scenarios(frame, rules)
    summary, trades, daily_portfolio, signals = combine_outputs(results, chart_results)

    full = chart_results["Strategy D - Full"]
    fixed = chart_results["Benchmark A - Fixed DCA"]
    cycles = cycle_analysis(full, fixed, rules)
    cash = cash_analysis(results)
    btc_validation, btc_events = btc_extended_validation(extended_daily, seed=rules["seed"])
    stage_effectiveness = tactical_event_effectiveness(full.signals, primary_daily)

    sensitivity_path = PROJECT_DIR / "results" / "parameter_sensitivity.csv"
    if args.skip_sensitivity:
        if not sensitivity_path.exists():
            raise RuntimeError("--skip-sensitivity requested but no frozen sensitivity output exists")
        sensitivity = pd.read_csv(sensitivity_path)
    else:
        sensitivity = run_parameter_sensitivity(
            frame,
            rules,
            make_scenario(rules, name="Strategy D - Full", capital_test="test2"),
        )
        # Add pre-specified transaction-cost rows to the same audit table.
        cost_rows = summary[
            (summary["capital_test"] == "test2")
            & (summary["cost_case"].isin(["low", "high"]))
        ].copy()
        cost_rows.insert(0, "sensitivity_type", "transaction_cost")
        sensitivity = pd.concat([sensitivity, cost_rows], ignore_index=True, sort=False)

    result_dir = PROJECT_DIR / "results"
    result_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(result_dir / "backtest_summary.csv", index=False)
    trades.to_csv(result_dir / "trade_log.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    daily_portfolio.to_csv(result_dir / "daily_portfolio.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    signals.to_csv(result_dir / "signal_log.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    cycles.to_csv(result_dir / "cycle_analysis.csv", index=False)
    cash.to_csv(result_dir / "cash_analysis.csv", index=False)
    sensitivity.to_csv(sensitivity_path, index=False)
    btc_validation.to_csv(result_dir / "btc_extended_validation.csv", index=False)
    btc_events.to_csv(result_dir / "btc_extended_events.csv", index=False, date_format="%Y-%m-%d")
    stage_effectiveness.to_csv(result_dir / "tactical_stage_effectiveness.csv", index=False)

    create_figures(PROJECT_DIR, chart_results, primary_daily)
    worthy = write_final_report(
        PROJECT_DIR,
        summary,
        cycles,
        cash,
        sensitivity[sensitivity["sensitivity_type"] == "frozen_grid_do_not_select"],
        btc_validation,
        stage_effectiveness,
        source_manifest,
    )

    audit = no_lookahead_audit(frame, rules, results, full)
    (PROJECT_DIR / "artifacts" / "no_lookahead_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not audit["pass"]:
        raise RuntimeError(f"No-look-ahead audit failed: {audit}")

    log = f"""# Analysis log

## Accepted patterns

- Point-in-time daily availability and next-4H-open execution passed prefix invariance.
- Equal US$2/4H contributions passed across all primary benchmarks.
- Normal DCA and tactical cash ledgers remained isolated.
- Primary rules remained frozen; the full 54-cell sensitivity grid was reported without promotion.

## Rejected patterns

- 2017-08-01 three-asset initialization: rejected because BNBUSDT was unavailable.
- Historical exchange-filter precision: rejected as unsupported; current US$5 filter is labeled a model proxy.
- Selecting the best sensitivity cell: rejected by design.

## Final live-readiness gate

`FINAL_SIMPLIFIED_STRATEGY.md` produced: {worthy}
"""
    (PROJECT_DIR / "artifacts" / "analysis_log.md").write_text(log, encoding="utf-8")

    manifest_payload = {
        "command": "python run_backtest.py --refresh-data",
        "python": sys.version,
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "config_sha256": sha256_file(PROJECT_DIR / "config" / "frozen_rules.json"),
        "data_contract": data_contract,
        "no_lookahead_audit": audit,
        "final_simplified_strategy_produced": worthy,
        "file_sha256": file_hashes(PROJECT_DIR),
    }
    write_run_manifest(PROJECT_DIR, manifest_payload)
    print(json.dumps({"status": "COMPLETE", "audit_pass": True, "worthy": worthy}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
