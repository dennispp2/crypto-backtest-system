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
OUTPUT_DIR = PROJECT_DIR / "v3_9"
RESULTS_DIR = OUTPUT_DIR / "results"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
FIGURES_DIR = OUTPUT_DIR / "figures"
REPORT_DIR = OUTPUT_DIR / "report"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.metrics import calculate_summary  # noqa: E402
from crypto_backtest.v31_engine import (  # noqa: E402
    ASSETS_V31,
    V31BacktestResult,
    V31Scenario,
    V31State,
    _allocations,
    _buy,
    _portfolio_value,
    _values,
    run_v31_backtest,
)
from crypto_backtest.v39_analysis import (  # noqa: E402
    append_forward_returns,
    build_event_drawdown_audit,
    build_peak_guard_audit,
    build_summary,
    complete_drift_audit,
    crash_integrity,
    daily_history_v39,
    fixed_dca_integrity,
    promotion_evaluation,
    stage4_integrity,
    transition_statistics,
)
from crypto_backtest.v39_engine import run_v39_backtest  # noqa: E402
from crypto_backtest.v39_reporting import create_v39_figures, write_v39_report  # noqa: E402
from run_backtest_v3_1 import load_formal_data  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def make_scenario(model: str, rules: dict[str, Any], *, capital_test: str = "test2_v3_9") -> V31Scenario:
    labels = {
        "H0": "H0 Initial Only - No DCA / No Tactical Trading",
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM",
        "P": "MODEL P - BTC+ETH V3.9 Bull Persistence Challenger",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "P"}, use_ai=False,
        hard_floor=float(rules["hard_floor"]), initial_capital=float(rules["initial_capital"]),
        capital_test=capital_test, fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
    )


def run_initial_only(frame: pd.DataFrame, rules: dict[str, Any]) -> V31BacktestResult:
    scenario = make_scenario("H0", rules)
    state = V31State(normal_cash=float(scenario.initial_capital))
    trades: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    first = frame.iloc[0]
    first_prices = {asset: float(first[f"{asset}_open"]) for asset in ASSETS_V31}
    for asset in ASSETS_V31:
        _buy(
            state, asset, float(rules["initial_allocation_usd"][asset]),
            first_prices[asset], first_prices, timestamp=pd.Timestamp(first["open_time"]),
            scenario=scenario, action="INITIAL_ALLOCATION", ledger="normal", trades=trades,
            signal_date=first.get("signal_date"), reason="FRESH_2020_START",
        )
    previous_value = float(scenario.initial_capital)
    previous_closes: dict[str, float] | None = None
    unit_nav, peak_nav = 1.0, 1.0
    for _, row in frame.iterrows():
        timestamp = pd.Timestamp(row["open_time"])
        prices = {asset: float(row[f"{asset}_close"]) for asset in ASSETS_V31}
        end_value = _portfolio_value(state, prices)
        twr_return = end_value / previous_value - 1.0
        unit_nav *= 1.0 + twr_return
        peak_nav = max(peak_nav, unit_nav)
        values = _values(state, prices)
        allocations = _allocations(state, prices)
        cash = state.normal_cash
        basket_return = 0.0 if previous_closes is None else sum(
            float(rules["target_weights"][asset]) * (prices[asset] / previous_closes[asset] - 1.0)
            for asset in ASSETS_V31
        )
        histories.append({
            "timestamp": timestamp, "portfolio_value": end_value,
            "btc_value": values["BTC"], "eth_value": values["ETH"],
            "unit_nav": unit_nav, "drawdown": unit_nav / peak_nav - 1.0,
            "twr_return": twr_return, "external_flow": 0.0, "elapsed_4h_intervals": 0,
            "normal_cash": cash, "pending_dca_cash": 0.0,
            "tactical_bear_cash": 0.0, "temporary_hedge_cash": 0.0,
            "tactical_cash": 0.0, "normal_cash_ratio": cash / end_value,
            "tactical_bear_cash_ratio": 0.0, "temporary_hedge_cash_ratio": 0.0,
            "tactical_cash_ratio": 0.0, "total_cash_ratio": cash / end_value,
            "crypto_exposure": sum(values.values()) / end_value,
            "BTC_allocation": allocations["BTC"], "ETH_allocation": allocations["ETH"],
            "BTC_close": prices["BTC"], "ETH_close": prices["ETH"],
            "BTC_signal_close": row.get("BTC_daily_close"),
            "sma10": row.get("sma10"), "sma20": row.get("sma20"),
            "sma50": row.get("sma50"), "sma200": row.get("sma200"),
            "ahr999": row.get("ahr999_fixed_arithmetic"), "bear_risk": np.nan,
            "ai_enabled": False, "ai_intervention": "NONE",
            "macro_state_previous": "N/A", "macro_state": "N/A", "sell_stage": 0,
            "active_target": np.nan, "cycle_id": 0, "macro_cooldown_days": 0,
            "accumulation_lock": False, "crash_level1_active": False,
            "theoretical_dca": 0.0, "protected_dca": 0.0,
            "committed_dca": 0.0, "executed_dca": 0.0,
            "dca_alloc_BTC": 0.0, "dca_alloc_ETH": 0.0,
            "target_basket_return": basket_return,
            "cash_drag_increment": (cash / end_value) * basket_return,
            "tactical_cash_drag_increment": 0.0, "daily_floor_breach_reason": "none",
        })
        previous_value = end_value
        previous_closes = prices
    history = pd.DataFrame(histories)
    trade_frame = pd.DataFrame(trades)
    counters: dict[str, Any] = {}
    summary = calculate_summary(history, trade_frame, scenario=scenario, counters=counters, rules=rules)
    return V31BacktestResult(
        scenario=scenario, summary=summary, history=history, trades=trade_frame,
        signals=pd.DataFrame(), transitions=pd.DataFrame(), cycles=pd.DataFrame(),
        temporary_lots=pd.DataFrame(), cash_events=pd.DataFrame(), counters=counters,
    )


def replay_ok(summary_row: pd.Series, reference: dict[str, Any]) -> bool:
    tolerance = float(reference["metric_abs_tolerance"])
    checks = [
        abs(float(summary_row["final_portfolio_value"]) - float(reference["final_portfolio_value_reference"]))
        <= float(reference["final_portfolio_value_abs_usd"]),
        abs(float(summary_row["twr_cagr"]) - float(reference["twr_cagr_reference"])) <= tolerance,
        abs(float(summary_row["maximum_drawdown"]) - float(reference["maximum_drawdown_reference"])) <= tolerance,
        abs(float(summary_row["calmar"]) - float(reference["calmar_reference"])) <= tolerance,
        int(summary_row["tactical_event_count"]) == int(reference["tactical_events_reference"]),
        abs(float(summary_row["tactical_turnover"]) - float(reference["tactical_turnover_reference"])) <= tolerance,
    ]
    return bool(all(checks))


def trade_prefix_identity(full: pd.DataFrame, prefix: pd.DataFrame, end: pd.Timestamp) -> bool:
    left = full.loc[pd.to_datetime(full["timestamp"], utc=True) <= end].reset_index(drop=True)
    right = prefix.reset_index(drop=True)
    if len(left) != len(right):
        return False
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date", "reason"]
    numeric = ["quantity", "raw_open_price", "effective_price", "gross_notional_usd", "cash_change_usd"]
    for column in keys:
        if not left[column].fillna("").astype(str).equals(right[column].fillna("").astype(str)):
            return False
    return bool(all(np.allclose(left[column], right[column], rtol=0.0, atol=1e-10) for column in numeric))


def rolling_start_table(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    starts: list[str],
    main: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for start in starts:
        if start == "2020-01-01":
            a, b, p = main["A"], main["B"], main["P"]
        else:
            sub = frame.loc[frame["open_time"] >= pd.Timestamp(start, tz="UTC")].copy().reset_index(drop=True)
            tag = f"rolling_{start[:4]}"
            a = run_v31_backtest(sub, rules, make_scenario("A", rules, capital_test=tag))
            b = run_v31_backtest(sub, rules, make_scenario("B", rules, capital_test=tag), model_a=a)
            p = run_v39_backtest(sub, rules, make_scenario("P", rules, capital_test=tag), model_a=a, shadow_v31=b)
        values: dict[str, Any] = {"fresh_start": start, "end": p.history.iloc[-1]["timestamp"]}
        for model, result in (("B", b), ("P", p)):
            values.update({
                f"{model}_final_portfolio_value": float(result.summary["final_portfolio_value"]),
                f"{model}_twr_cagr": float(result.summary["time_weighted_cagr"]),
                f"{model}_maximum_drawdown": float(result.summary["maximum_drawdown"]),
                f"{model}_calmar": float(result.summary["calmar"]),
            })
        values.update({
            "delta_final_p_minus_b": values["P_final_portfolio_value"] - values["B_final_portfolio_value"],
            "delta_cagr_p_minus_b_pp": 100.0 * (values["P_twr_cagr"] - values["B_twr_cagr"]),
            "delta_max_dd_p_minus_b_pp": 100.0 * (values["P_maximum_drawdown"] - values["B_maximum_drawdown"]),
            "delta_calmar_p_minus_b": values["P_calmar"] - values["B_calmar"],
        })
        rows.append(values)
    return pd.DataFrame(rows)


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_9.json"
    }


def main() -> int:
    frozen = load_json(PROJECT_DIR / "config" / "config_frozen_v3_9.json")
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_1.json")
    base_rules = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    if not frozen.get("frozen_before_formal_run") or not frozen.get("post_backtest_only"):
        raise RuntimeError("V3.9 was not frozen before formal execution")
    hash_checks = {
        "base_config_hash": sha256_file(PROJECT_DIR / frozen["base_config_path"]) == frozen["base_config_sha256"].lower(),
        "base_engine_hash": sha256_file(PROJECT_DIR / frozen["base_engine_path"]) == frozen["base_engine_sha256"].lower(),
        "request_hash": sha256_file(Path(r"C:\Users\denni\.codex\attachments\6c75db21-b086-4765-b470-a6beb1ed6d8c\pasted-text.txt")) == frozen["request_sha256"].lower(),
    }
    if not all(hash_checks.values()):
        raise RuntimeError(f"Frozen-source hash mismatch: {hash_checks}")

    for directory in (RESULTS_DIR, ARTIFACTS_DIR, FIGURES_DIR, REPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(PROJECT_DIR / "config" / "config_frozen_v3_9.json", OUTPUT_DIR / "config_frozen_v3_9.json")

    source_manifest = pd.read_csv(PROJECT_DIR / "v3_1" / "artifacts" / "source_manifest_v3_1.csv")
    source_checks = []
    for _, row in source_manifest.iterrows():
        path = PROJECT_DIR / str(row["path"])
        source_checks.append(path.exists() and sha256_file(path) == str(row["sha256"]).lower())
    if not all(source_checks):
        raise RuntimeError("Frozen V3.1 source snapshot hash mismatch")
    source_manifest.to_csv(ARTIFACTS_DIR / "source_manifest_v3_9.csv", index=False)

    frame, daily_features, _, _, data_contract = load_formal_data(rules, base_rules, source_manifest)
    write_json(ARTIFACTS_DIR / "data_contract_v3_9.json", data_contract)

    h0 = run_initial_only(frame, rules)
    model_a = run_v31_backtest(frame, rules, make_scenario("A", rules))
    model_b = run_v31_backtest(frame, rules, make_scenario("B", rules), model_a=model_a)
    pre_summary = build_summary([h0, model_a, model_b], rules, frozen["audit_conventions"]["event_windows"])
    b_pre = pre_summary.set_index("model").loc["B"]
    if not replay_ok(b_pre, frozen["baseline_replay_tolerances"]):
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL: {b_pre.to_dict()}")

    model_p = run_v39_backtest(
        frame, rules, make_scenario("P", rules), model_a=model_a, shadow_v31=model_b
    )
    results = [h0, model_a, model_b, model_p]
    result_map = {result.scenario.model: result for result in results}
    daily_map = {model: daily_history_v39(result) for model, result in result_map.items()}
    summary = build_summary(results, rules, frozen["audit_conventions"]["event_windows"])

    dca = fixed_dca_integrity([model_a, model_b, model_p])
    dca.to_csv(RESULTS_DIR / "fixed_dca_integrity_v3_9.csv", index=False)
    event_audit = build_event_drawdown_audit(daily_map, frozen["audit_conventions"]["event_windows"])
    peak_audit = build_peak_guard_audit(
        daily_map["B"], daily_map["P"], model_b.signals, model_p.signals,
        *frozen["audit_conventions"]["event_windows"]["SEP_2021_JUN_2022_PEAK_AUDIT"],
    )
    blocked = complete_drift_audit(model_p.blocked_sells, model_b.signals, model_p.signals)
    blocked = append_forward_returns(blocked, model_b.signals)
    reentry = model_p.bear_reentry_audit.copy()
    stage4 = stage4_integrity({"B": model_b.trades, "P": model_p.trades})
    crash = crash_integrity(model_b.signals, model_p.signals)
    transitions = transition_statistics(daily_map)
    rolling = rolling_start_table(frame, rules, frozen["rolling_starts"], result_map)

    prefix_end = pd.Timestamp("2024-12-31 20:00:00", tz="UTC")
    prefix_frame = frame.loc[frame["open_time"] <= prefix_end].copy().reset_index(drop=True)
    prefix_a = run_v31_backtest(prefix_frame, rules, make_scenario("A", rules, capital_test="prefix_audit"))
    prefix_b = run_v31_backtest(prefix_frame, rules, make_scenario("B", rules, capital_test="prefix_audit"), model_a=prefix_a)
    prefix_p = run_v39_backtest(
        prefix_frame, rules, make_scenario("P", rules, capital_test="prefix_audit"),
        model_a=prefix_a, shadow_v31=prefix_b,
    )

    signal_execution_ok = bool(
        (pd.to_datetime(model_p.signals["signal_available_at"], utc=True)
         <= pd.to_datetime(model_p.signals["execution_4h_open"], utc=True)).all()
        and (pd.to_datetime(model_p.signals["signal_date"], utc=True)
             < pd.to_datetime(model_p.signals["execution_4h_open"], utc=True)).all()
    )
    engine_text = (PROJECT_DIR / "src" / "crypto_backtest" / "v39_engine.py").read_text(encoding="utf-8")
    no_lookahead = {
        "status": "PASS",
        "data_contract_pass": bool(data_contract["pass"]),
        "completed_daily_signal_before_execution": signal_execution_ok,
        "future_label_columns_in_execution_frame": data_contract["future_label_columns_in_execution_frame"],
        "forward_return_terms_in_engine": [term for term in ("forward_return_30", "forward_return_60", "shift(-") if term in engine_text],
        "prefix_trade_identity_through_2024_12_31": trade_prefix_identity(model_p.trades, prefix_p.trades, prefix_end),
        "three_close_source": "completed daily closes carried to next tradable 4h open",
        "ex_post_forward_returns_appended_after_engine": True,
    }
    no_lookahead["status"] = "PASS" if bool(
        no_lookahead["data_contract_pass"]
        and no_lookahead["completed_daily_signal_before_execution"]
        and not no_lookahead["future_label_columns_in_execution_frame"]
        and not no_lookahead["forward_return_terms_in_engine"]
        and no_lookahead["prefix_trade_identity_through_2024_12_31"]
    ) else "FAIL"
    write_json(ARTIFACTS_DIR / "no_lookahead_audit_v3_9.json", no_lookahead)

    execution_integrity = bool(
        signal_execution_ok
        and set(model_p.trades.loc[model_p.trades["action"].str.startswith("TACTICAL", na=False), "asset"]) <= {"BTC", "ETH"}
        and (model_p.trades["gross_notional_usd"] >= 0).all()
    )
    integrity = {
        "V3_1_REPLAY": replay_ok(summary.set_index("model").loc["B"], frozen["baseline_replay_tolerances"]),
        "FIXED_DCA_INTEGRITY": bool(dca["all_match"].all()),
        "NO_LOOK_AHEAD": no_lookahead["status"] == "PASS",
        "EXECUTION_INTEGRITY": execution_integrity,
        "FROZEN_SOURCE_HASHES": all(hash_checks.values()) and all(source_checks),
    }
    promotion = promotion_evaluation(
        summary, event_audit, stage4, crash, integrity, frozen["promotion_gates"]
    )
    write_json(ARTIFACTS_DIR / "promotion_verdict_v3_9.json", promotion)

    summary.to_csv(RESULTS_DIR / "summary_v3_9.csv", index=False)
    pd.concat(daily_map.values(), ignore_index=True).to_csv(RESULTS_DIR / "daily_portfolio_v3_9.csv", index=False)
    pd.concat([
        result.trades.assign(model=result.scenario.model, strategy=result.scenario.name)
        for result in results
    ], ignore_index=True).to_csv(RESULTS_DIR / "trade_log_v3_9.csv", index=False)
    pd.concat([
        model_b.signals.assign(model="B", strategy=model_b.scenario.name),
        model_p.signals.assign(model="P", strategy=model_p.scenario.name),
    ], ignore_index=True).to_csv(RESULTS_DIR / "regime_log_v3_9.csv", index=False)
    blocked.to_csv(RESULTS_DIR / "bull_persistence_blocked_sells_v3_9.csv", index=False)
    reentry.to_csv(RESULTS_DIR / "bear_reentry_audit_v3_9.csv", index=False)
    peak_audit.to_csv(RESULTS_DIR / "2021_peak_guard_audit_v3_9.csv", index=False)
    event_audit.to_csv(RESULTS_DIR / "event_drawdown_audit_v3_9.csv", index=False)
    rolling.to_csv(RESULTS_DIR / "rolling_start_v3_9.csv", index=False)
    transitions.to_csv(RESULTS_DIR / "regime_transition_stats_v3_9.csv", index=False)
    stage4.to_csv(RESULTS_DIR / "stage4_integrity_v3_9.csv", index=False)
    crash.to_csv(RESULTS_DIR / "crash_integrity_v3_9.csv", index=False)

    create_v39_figures(
        daily_map, {"B": model_b.trades, "P": model_p.trades}, blocked, reentry, FIGURES_DIR
    )
    write_v39_report(
        REPORT_DIR / "FINAL_REPORT_V3_9.md", summary=summary,
        event_audit=event_audit, rolling=rolling, blocked=blocked, reentry=reentry,
        stage4=stage4, crash=crash, transition_stats=transitions,
        promotion=promotion, integrity=integrity, formal_end=frame.iloc[-1]["open_time"],
    )

    manifest = {
        "schema_version": "3.9",
        "status": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_start": frame.iloc[0]["open_time"],
        "formal_end": frame.iloc[-1]["open_time"],
        "formal_4h_rows": len(frame),
        "python": sys.version,
        "platform": platform.platform(),
        "matplotlib_backend": matplotlib.get_backend(),
        "frozen_config_sha256": sha256_file(PROJECT_DIR / "config" / "config_frozen_v3_9.json"),
        "v39_engine_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v39_engine.py"),
        "v39_analysis_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v39_analysis.py"),
        "v39_reporting_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v39_reporting.py"),
        "source_hash_checks": bool(all(source_checks)),
        "integrity": integrity,
        "promotion": promotion,
        "outputs_sha256": output_hashes(OUTPUT_DIR),
    }
    write_json(ARTIFACTS_DIR / "run_manifest_v3_9.json", manifest)

    print(json.dumps({
        "status": "COMPLETE", "verdict": promotion["verdict"],
        "summary": summary[["model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]].to_dict("records"),
        "blocked_drift_sells": int((blocked["blocked_or_executed"] == "BLOCKED").sum()) if not blocked.empty else 0,
        "bear_reentry_rows": len(reentry),
        "all_integrity_pass": all(integrity.values()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
