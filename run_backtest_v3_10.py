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
OUTPUT_DIR = PROJECT_DIR / "v3_10"
RESULTS_DIR = OUTPUT_DIR / "results"
ARTIFACTS_DIR = OUTPUT_DIR / "artifacts"
FIGURES_DIR = OUTPUT_DIR / "figures"
REPORT_DIR = OUTPUT_DIR / "report"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.v31_engine import V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v310_analysis import (  # noqa: E402
    bearish_rebreak_scope_audit,
    build_event_drawdown_audit,
    build_stage_window_detail,
    build_summary,
    candidate_economic_audit,
    causal_lineage_audit,
    crash_integrity,
    daily_history_v310,
    fixed_dca_audit,
    promotion_evaluation,
    stage3_scope_integrity,
    stage4_integrity,
)
from crypto_backtest.v310_engine import run_v310_backtest  # noqa: E402
from crypto_backtest.v310_reporting import create_v310_figures, write_v310_report  # noqa: E402
from crypto_backtest.v39_engine import run_v39_backtest  # noqa: E402
from run_backtest_v3_1 import load_formal_data  # noqa: E402
from run_backtest_v3_9 import run_initial_only  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8",
    )


def make_scenario(model: str, rules: dict[str, Any], *, capital_test: str = "test2_v3_10") -> V31Scenario:
    labels = {
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM",
        "P": "MODEL P39 - V3.9 Frozen Replay Reference",
        "Q": "MODEL Q - BTC+ETH V3.10 Isolated Stage3 Confirmation",
    }
    return V31Scenario(
        name=labels[model], model=model, use_fsm=model in {"B", "P", "Q"}, use_ai=False,
        hard_floor=float(rules["hard_floor"]), initial_capital=float(rules["initial_capital"]),
        capital_test=capital_test, fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
    )


def replay_ok(row: pd.Series, reference: dict[str, Any]) -> bool:
    tolerance = float(reference["metric_abs_tolerance"])
    return bool(all([
        abs(float(row["final_portfolio_value"]) - float(reference["final_portfolio_value_reference"]))
        <= float(reference["final_portfolio_value_abs_usd"]),
        abs(float(row["twr_cagr"]) - float(reference["twr_cagr_reference"])) <= tolerance,
        abs(float(row["maximum_drawdown"]) - float(reference["maximum_drawdown_reference"])) <= tolerance,
        abs(float(row["calmar"]) - float(reference["calmar_reference"])) <= tolerance,
        int(row["tactical_event_count"]) == int(reference["tactical_events_reference"]),
        abs(float(row["tactical_turnover"]) - float(reference["tactical_turnover_reference"])) <= tolerance,
    ]))


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
    return bool(all(
        np.allclose(left[column], right[column], rtol=0.0, atol=1e-10)
        for column in numeric
    ))


def rolling_start_table(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    starts: list[str],
    main: dict[str, Any],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for start in starts:
        if start == "2020-01-01":
            b, p, q = main["B"], main["P39"], main["Q"]
        else:
            sub = frame.loc[frame["open_time"] >= pd.Timestamp(start, tz="UTC")].copy().reset_index(drop=True)
            tag = f"rolling_{start[:4]}"
            a = run_v31_backtest(sub, rules, make_scenario("A", rules, capital_test=tag))
            b = run_v31_backtest(sub, rules, make_scenario("B", rules, capital_test=tag), model_a=a)
            p = run_v39_backtest(
                sub, rules, make_scenario("P", rules, capital_test=tag), model_a=a, shadow_v31=b,
            )
            q = run_v310_backtest(
                sub, rules, make_scenario("Q", rules, capital_test=tag), model_a=a, shadow_v31=b,
            )
        values: dict[str, Any] = {"fresh_start": start, "end": q.history.iloc[-1]["timestamp"]}
        for model, result in (("B", b), ("P39", p), ("Q", q)):
            values.update({
                f"{model}_final_portfolio_value": float(result.summary["final_portfolio_value"]),
                f"{model}_twr_cagr": float(result.summary["time_weighted_cagr"]),
                f"{model}_maximum_drawdown": float(result.summary["maximum_drawdown"]),
                f"{model}_calmar": float(result.summary["calmar"]),
            })
        for challenger in ("P39", "Q"):
            values.update({
                f"delta_final_{challenger}_minus_B": values[f"{challenger}_final_portfolio_value"] - values["B_final_portfolio_value"],
                f"delta_cagr_{challenger}_minus_B_pp": 100.0 * (values[f"{challenger}_twr_cagr"] - values["B_twr_cagr"]),
                f"delta_max_dd_{challenger}_minus_B_pp": 100.0 * (values[f"{challenger}_maximum_drawdown"] - values["B_maximum_drawdown"]),
                f"delta_calmar_{challenger}_minus_B": values[f"{challenger}_calmar"] - values["B_calmar"],
            })
        rows.append(values)
    return pd.DataFrame(rows)


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name != "run_manifest_v3_10.json"
    }


def _stage3_august_audit(
    candidates: pd.DataFrame, daily: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    selected = candidates.loc[
        pd.to_datetime(candidates["candidate_date"], utc=True).between(
            pd.Timestamp("2023-07-15", tz="UTC"), pd.Timestamp("2023-09-30", tz="UTC")
        )
    ].copy()
    rows: list[dict[str, Any]] = []
    for _, item in selected.iterrows():
        date = pd.Timestamp(item["resolution_date"])
        row: dict[str, Any] = {
            "candidate_id": item["candidate_id"],
            "candidate_date": item["candidate_date"],
            "hard_failure_date": date if item["resolution_reason"] == "SMA200_HARD_FAILURE" else pd.NaT,
            "status": item["confirmed_or_rejected"],
            "resolution_reason": item["resolution_reason"],
        }
        for model in ("B", "P39", "Q"):
            model_dates = pd.to_datetime(daily[model]["date"], utc=True)
            matched = daily[model].loc[model_dates.eq(date.floor("D"))]
            row[f"{model}_exposure"] = float(matched.iloc[0]["crypto_exposure"]) if not matched.empty else np.nan
        row["days_delayed_vs_B"] = (
            date - pd.Timestamp(item["candidate_date"])
        ).total_seconds() / 86_400.0
        rows.append(row)
    return pd.DataFrame(rows)


def _peak_safety_audit(
    daily: dict[str, pd.DataFrame], signals: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    return build_stage_window_detail(
        daily, signals, "2021-09-01", "2022-06-30",
    )


def main() -> int:
    frozen_path = PROJECT_DIR / "config" / "config_frozen_v3_10.json"
    frozen = load_json(frozen_path)
    rules = load_json(PROJECT_DIR / "config" / "config_frozen_v3_1.json")
    base_rules = load_json(PROJECT_DIR / "config" / "frozen_rules.json")
    if not frozen.get("frozen_before_formal_run") or not frozen.get("post_backtest_only"):
        raise RuntimeError("V3.10 rules and gates were not frozen before formal execution")

    checked_paths = {
        "base_config_hash": (frozen["base_config_path"], frozen["base_config_sha256"]),
        "base_engine_hash": (frozen["base_engine_path"], frozen["base_engine_sha256"]),
        "v39_config_hash": (frozen["v39_config_path"], frozen["v39_config_sha256"]),
        "v39_engine_hash": (frozen["v39_engine_path"], frozen["v39_engine_sha256"]),
        "v39_runner_hash": (frozen["v39_runner_path"], frozen["v39_runner_sha256"]),
        "v39_manifest_hash": (frozen["v39_manifest_path"], frozen["v39_manifest_sha256"]),
        "v39_summary_hash": (frozen["v39_summary_path"], frozen["v39_summary_sha256"]),
    }
    hash_checks = {
        name: sha256_file(PROJECT_DIR / relative) == expected.lower()
        for name, (relative, expected) in checked_paths.items()
    }
    hash_checks["request_hash"] = sha256_file(Path(frozen["request_path"])) == frozen["request_sha256"].lower()
    if not all(hash_checks.values()):
        raise RuntimeError(f"Frozen-source hash mismatch: {hash_checks}")

    for directory in (RESULTS_DIR, ARTIFACTS_DIR, FIGURES_DIR, REPORT_DIR):
        directory.mkdir(parents=True, exist_ok=True)
    shutil.copy2(frozen_path, OUTPUT_DIR / "config_frozen_v3_10.json")

    source_manifest = pd.read_csv(PROJECT_DIR / "v3_1" / "artifacts" / "source_manifest_v3_1.csv")
    source_checks = []
    for _, row in source_manifest.iterrows():
        source = PROJECT_DIR / str(row["path"])
        source_checks.append(source.exists() and sha256_file(source) == str(row["sha256"]).lower())
    if not all(source_checks):
        raise RuntimeError("Frozen V3.1 source snapshot hash mismatch")
    source_manifest.to_csv(ARTIFACTS_DIR / "source_manifest_v3_10.csv", index=False)

    frame, _, _, _, data_contract = load_formal_data(rules, base_rules, source_manifest)
    write_json(ARTIFACTS_DIR / "data_contract_v3_10.json", data_contract)

    h0 = run_initial_only(frame, rules)
    model_a = run_v31_backtest(frame, rules, make_scenario("A", rules))
    model_b = run_v31_backtest(frame, rules, make_scenario("B", rules), model_a=model_a)
    pre_b_summary = build_summary(
        {"B": model_b}, rules, frozen["audit_conventions"]["event_windows"],
    ).set_index("model").loc["B"]
    if not replay_ok(pre_b_summary, frozen["baseline_replay_tolerances"]):
        raise RuntimeError(f"V3_1_REPLAY_INTEGRITY=FAIL: {pre_b_summary.to_dict()}")

    model_p = run_v39_backtest(
        frame, rules, make_scenario("P", rules), model_a=model_a, shadow_v31=model_b,
    )
    pre_p_summary = build_summary(
        {"P39": model_p}, rules, frozen["audit_conventions"]["event_windows"],
    ).set_index("model").loc["P39"]
    if not replay_ok(pre_p_summary, frozen["v39_replay_tolerances"]):
        raise RuntimeError(f"V39_STAGE3_MODULE_REPRODUCTION_FAIL: {pre_p_summary.to_dict()}")

    model_q = run_v310_backtest(
        frame, rules, make_scenario("Q", rules), model_a=model_a, shadow_v31=model_b,
    )
    results = {"H0": h0, "A": model_a, "B": model_b, "P39": model_p, "Q": model_q}
    daily = {model: daily_history_v310(result, model) for model, result in results.items()}
    signals = {"B": model_b.signals, "P39": model_p.signals, "Q": model_q.signals}
    trades = {"B": model_b.trades, "P39": model_p.trades, "Q": model_q.trades}
    summary = build_summary(results, rules, frozen["audit_conventions"]["event_windows"])

    dca = fixed_dca_audit({"A": model_a, "B": model_b, "P39": model_p, "Q": model_q})
    event_audit = build_event_drawdown_audit(daily, frozen["audit_conventions"]["event_windows"])
    raw_candidates = model_q.stage3_candidates.copy()
    candidates = candidate_economic_audit(raw_candidates, daily["B"], daily["Q"])
    if not candidates.empty:
        candidates["resolution_delay_days"] = (
            pd.to_datetime(candidates["resolution_date"], utc=True)
            - pd.to_datetime(candidates["candidate_date"], utc=True)
        ).dt.total_seconds() / 86_400.0
    scope = stage3_scope_integrity(model_b.signals, model_q.signals, candidates)
    lineage = causal_lineage_audit(model_b.trades, model_q.trades, candidates)
    rebreak = bearish_rebreak_scope_audit(model_b.signals, model_q.signals)
    stage4 = stage4_integrity(trades)
    crash = crash_integrity(signals)
    rolling = rolling_start_table(frame, rules, frozen["rolling_starts"], results)
    detail_2023 = build_stage_window_detail(
        daily, signals, *frozen["audit_conventions"]["event_windows"]["STAGE3_MARCH_2023"],
    )
    august = _stage3_august_audit(candidates, daily)
    peak = _peak_safety_audit(daily, signals)

    candidate_total_incremental = float(candidates["incremental_exposure_days"].sum()) if not candidates.empty else 0.0
    candidate_confirmed_delay = candidates.loc[
        candidates["confirmed_or_rejected"].eq("CONFIRMED"), "days_delayed_vs_v31"
    ] if not candidates.empty else pd.Series(dtype=float)
    summary.loc[summary["model"].eq("Q"), "candidate_count"] = len(candidates)
    summary.loc[summary["model"].eq("Q"), "candidate_rejected"] = int(
        candidates["confirmed_or_rejected"].eq("REJECTED").sum()
    ) if not candidates.empty else 0
    summary.loc[summary["model"].eq("Q"), "candidate_confirmed"] = int(
        candidates["confirmed_or_rejected"].eq("CONFIRMED").sum()
    ) if not candidates.empty else 0
    summary.loc[summary["model"].eq("Q"), "candidate_hard_failure"] = int(
        candidates["resolution_reason"].eq("SMA200_HARD_FAILURE").sum()
    ) if not candidates.empty else 0
    summary.loc[summary["model"].eq("Q"), "average_confirmation_delay_days"] = float(candidate_confirmed_delay.mean()) if not candidate_confirmed_delay.empty else np.nan
    summary.loc[summary["model"].eq("Q"), "median_confirmation_delay_days"] = float(candidate_confirmed_delay.median()) if not candidate_confirmed_delay.empty else np.nan
    summary.loc[summary["model"].eq("Q"), "average_candidate_resolution_days"] = float(candidates["resolution_delay_days"].mean()) if not candidates.empty else np.nan
    summary.loc[summary["model"].eq("Q"), "median_candidate_resolution_days"] = float(candidates["resolution_delay_days"].median()) if not candidates.empty else np.nan
    summary.loc[summary["model"].eq("Q"), "incremental_crypto_exposure_days"] = candidate_total_incremental

    prefix_end = pd.Timestamp("2024-12-31 20:00:00", tz="UTC")
    prefix_frame = frame.loc[frame["open_time"] <= prefix_end].copy().reset_index(drop=True)
    prefix_a = run_v31_backtest(prefix_frame, rules, make_scenario("A", rules, capital_test="prefix_audit"))
    prefix_b = run_v31_backtest(
        prefix_frame, rules, make_scenario("B", rules, capital_test="prefix_audit"), model_a=prefix_a,
    )
    prefix_q = run_v310_backtest(
        prefix_frame, rules, make_scenario("Q", rules, capital_test="prefix_audit"),
        model_a=prefix_a, shadow_v31=prefix_b,
    )

    signal_execution_ok = bool(
        (pd.to_datetime(model_q.signals["signal_available_at"], utc=True)
         <= pd.to_datetime(model_q.signals["execution_4h_open"], utc=True)).all()
        and (pd.to_datetime(model_q.signals["signal_date"], utc=True)
             < pd.to_datetime(model_q.signals["execution_4h_open"], utc=True)).all()
    )
    engine_text = (PROJECT_DIR / "src" / "crypto_backtest" / "v310_engine.py").read_text(encoding="utf-8")
    no_lookahead = {
        "status": "PASS",
        "data_contract_pass": bool(data_contract["pass"]),
        "completed_daily_signal_before_execution": signal_execution_ok,
        "future_label_columns_in_execution_frame": data_contract["future_label_columns_in_execution_frame"],
        "forward_return_terms_in_engine": [
            term for term in ("forward_return_30", "forward_return_60", "shift(-") if term in engine_text
        ],
        "prefix_trade_identity_through_2024_12_31": trade_prefix_identity(
            model_q.trades, prefix_q.trades, prefix_end,
        ),
        "stage3_module_source": frozen["v39_engine_path"],
        "stage3_module_source_sha256": frozen["v39_engine_sha256"],
        "three_close_source": "completed daily closes carried to next tradable 4h open",
        "ex_post_candidate_economics_appended_after_engine": True,
    }
    no_lookahead["status"] = "PASS" if bool(
        no_lookahead["data_contract_pass"]
        and no_lookahead["completed_daily_signal_before_execution"]
        and not no_lookahead["future_label_columns_in_execution_frame"]
        and not no_lookahead["forward_return_terms_in_engine"]
        and no_lookahead["prefix_trade_identity_through_2024_12_31"]
    ) else "FAIL"
    write_json(ARTIFACTS_DIR / "no_lookahead_audit_v3_10.json", no_lookahead)

    allowed = rules["allowed_transitions"]
    fsm_ok = True
    for _, transition in model_q.transitions.iterrows():
        if transition["reason"] == "V31_SHADOW_STAGE4_PRIORITY":
            continue
        fsm_ok &= str(transition["to_state"]) in allowed.get(str(transition["from_state"]), [])
    execution_integrity = bool(
        signal_execution_ok
        and set(model_q.trades.loc[model_q.trades["action"].str.startswith("TACTICAL", na=False), "asset"]) <= {"BTC", "ETH"}
        and (model_q.trades["gross_notional_usd"] >= 0).all()
        and (model_q.history["crypto_exposure"] >= -1e-12).all()
        and fsm_ok
    )
    integrity = {
        "V3_1_REPLAY": replay_ok(summary.set_index("model").loc["B"], frozen["baseline_replay_tolerances"]),
        "V3_9_REPLAY": replay_ok(summary.set_index("model").loc["P39"], frozen["v39_replay_tolerances"]),
        "FIXED_DCA_INTEGRITY": bool(dca["all_match"].all()),
        "NO_LOOK_AHEAD": no_lookahead["status"] == "PASS",
        "EXECUTION_INTEGRITY": execution_integrity,
        "FSM_AUDIT": bool(fsm_ok),
        "STAGE3_SCOPE_INTEGRITY": bool(not scope["classification"].eq("UNEXPECTED_DIFFERENCE").any()),
        "CAUSAL_LINEAGE": bool(
            lineage.empty or not lineage["classification"].eq("UNEXPLAINED_PATH_DIFFERENCE").any()
        ),
        "BEARISH_REBREAK_SCOPE": bool(not rebreak["unexpected_delay"].any()),
        "FROZEN_SOURCE_HASHES": bool(all(hash_checks.values()) and all(source_checks)),
    }
    promotion = promotion_evaluation(
        summary, event_audit, rolling, stage4, crash, integrity, frozen["promotion_gates"],
    )
    summary.loc[summary["model"].eq("Q"), "uplift_capture_ratio"] = promotion["uplift_capture_ratio"]
    write_json(ARTIFACTS_DIR / "promotion_verdict_v3_10.json", promotion)

    uplift = pd.DataFrame([{
        "B_final_portfolio_value": float(summary.set_index("model").loc["B", "final_portfolio_value"]),
        "P39_final_portfolio_value": float(summary.set_index("model").loc["P39", "final_portfolio_value"]),
        "Q_final_portfolio_value": float(summary.set_index("model").loc["Q", "final_portfolio_value"]),
        "V39_RETURN_UPLIFT": promotion["v39_return_uplift_usd"],
        "V310_RETURN_UPLIFT": promotion["v310_return_uplift_usd"],
        "UPLIFT_CAPTURE_RATIO": promotion["uplift_capture_ratio"],
        "GATE_75PCT_FINAL_THRESHOLD": promotion["precise_75pct_final_value_threshold_usd"],
        "attribution_interpretation": (
            "MOST_V39_UPLIFT_REPRODUCED_BY_STAGE3_CONFIRMATION"
            if promotion["uplift_capture_ratio"] >= 0.75
            else "MOST_V39_UPLIFT_NOT_REPRODUCED_BY_STAGE3_CONFIRMATION"
        ),
    }])

    summary.to_csv(RESULTS_DIR / "summary_v3_10.csv", index=False)
    pd.concat(daily.values(), ignore_index=True).to_csv(RESULTS_DIR / "daily_portfolio_v3_10.csv", index=False)
    pd.concat([
        result.trades.assign(model=model, strategy=result.scenario.name)
        for model, result in results.items()
    ], ignore_index=True).to_csv(RESULTS_DIR / "trade_log_v3_10.csv", index=False)
    pd.concat([
        signals[model].assign(model=model, strategy=results[model].scenario.name)
        for model in ("B", "P39", "Q")
    ], ignore_index=True).to_csv(RESULTS_DIR / "regime_log_v3_10.csv", index=False)
    candidates.to_csv(RESULTS_DIR / "stage3_candidate_audit_v3_10.csv", index=False)
    scope.to_csv(RESULTS_DIR / "stage3_scope_integrity_v3_10.csv", index=False)
    lineage.to_csv(RESULTS_DIR / "causal_lineage_audit_v3_10.csv", index=False)
    rebreak.to_csv(RESULTS_DIR / "bearish_rebreak_scope_audit_v3_10.csv", index=False)
    event_audit.to_csv(RESULTS_DIR / "event_drawdown_audit_v3_10.csv", index=False)
    rolling.to_csv(RESULTS_DIR / "rolling_start_v3_10.csv", index=False)
    uplift.to_csv(RESULTS_DIR / "v39_uplift_attribution_v3_10.csv", index=False)
    stage4.to_csv(RESULTS_DIR / "stage4_integrity_v3_10.csv", index=False)
    crash.to_csv(RESULTS_DIR / "crash_integrity_v3_10.csv", index=False)
    dca.to_csv(RESULTS_DIR / "fixed_dca_integrity_v3_10.csv", index=False)
    detail_2023.to_csv(RESULTS_DIR / "2023_stage3_detail_v3_10.csv", index=False)
    august.to_csv(RESULTS_DIR / "2023_august_safety_audit_v3_10.csv", index=False)
    peak.to_csv(RESULTS_DIR / "2021_peak_safety_audit_v3_10.csv", index=False)

    create_v310_figures(daily, trades, candidates, rolling, FIGURES_DIR)
    write_v310_report(
        REPORT_DIR / "FINAL_REPORT_V3_10.md", summary=summary,
        event_audit=event_audit, rolling=rolling, candidates=candidates,
        scope=scope, lineage=lineage, stage4=stage4, crash=crash,
        promotion=promotion, integrity=integrity, formal_end=frame.iloc[-1]["open_time"],
    )

    manifest = {
        "schema_version": "3.10",
        "status": "COMPLETE",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "formal_start": frame.iloc[0]["open_time"],
        "formal_end": frame.iloc[-1]["open_time"],
        "formal_4h_rows": len(frame),
        "python": sys.version,
        "platform": platform.platform(),
        "matplotlib_backend": matplotlib.get_backend(),
        "frozen_config_sha256": sha256_file(frozen_path),
        "v310_engine_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v310_engine.py"),
        "v310_analysis_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v310_analysis.py"),
        "v310_reporting_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "v310_reporting.py"),
        "v39_stage3_module_sha256": sha256_file(PROJECT_DIR / frozen["v39_engine_path"]),
        "source_hash_checks": bool(all(source_checks)),
        "integrity": integrity,
        "promotion": promotion,
        "outputs_sha256": output_hashes(OUTPUT_DIR),
    }
    write_json(ARTIFACTS_DIR / "run_manifest_v3_10.json", manifest)

    print(json.dumps({
        "status": "COMPLETE",
        "verdict": promotion["verdict"],
        "summary": summary.loc[summary["model"].isin(["B", "P39", "Q"]), [
            "model", "final_portfolio_value", "twr_cagr", "maximum_drawdown",
            "calmar", "tactical_turnover",
        ]].to_dict("records"),
        "uplift_capture_ratio": promotion["uplift_capture_ratio"],
        "candidate_count": len(candidates),
        "unexpected_scope_differences": int(scope["classification"].eq("UNEXPECTED_DIFFERENCE").sum()),
        "unexplained_trade_differences": int(
            lineage["classification"].eq("UNEXPLAINED_PATH_DIFFERENCE").sum()
        ) if not lineage.empty else 0,
        "all_integrity_pass": all(integrity.values()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
