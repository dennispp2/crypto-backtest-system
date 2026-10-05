from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v3_10"


def test_all_required_v310_outputs_exist_and_are_nonempty() -> None:
    required = [
        "report/FINAL_REPORT_V3_10.md",
        "results/summary_v3_10.csv",
        "results/daily_portfolio_v3_10.csv",
        "results/trade_log_v3_10.csv",
        "results/regime_log_v3_10.csv",
        "results/stage3_candidate_audit_v3_10.csv",
        "results/stage3_scope_integrity_v3_10.csv",
        "results/causal_lineage_audit_v3_10.csv",
        "results/bearish_rebreak_scope_audit_v3_10.csv",
        "results/event_drawdown_audit_v3_10.csv",
        "results/rolling_start_v3_10.csv",
        "results/v39_uplift_attribution_v3_10.csv",
        "results/stage4_integrity_v3_10.csv",
        "results/crash_integrity_v3_10.csv",
        "artifacts/no_lookahead_audit_v3_10.json",
        "artifacts/run_manifest_v3_10.json",
        "config_frozen_v3_10.json",
        *[f"figures/{name}.png" for name in [
            "01_equity_curve_v3_10", "02_normalized_growth_v3_10",
            "03_drawdown_v3_10", "04_2023_stage3_isolation_v3_10",
            "05_2021_2022_safety_v3_10", "06_2025_2026_safety_v3_10",
            "07_rolling_start_v3_10",
        ]],
    ]
    assert all((OUT / relative).is_file() and (OUT / relative).stat().st_size > 0 for relative in required)


def test_baseline_reference_and_q_metrics_are_exact() -> None:
    summary = pd.read_csv(OUT / "results" / "summary_v3_10.csv").set_index("model")
    assert np.isclose(summary.loc["B", "final_portfolio_value"], 348746.8528777533, atol=1e-8)
    assert np.isclose(summary.loc["P39", "final_portfolio_value"], 367407.5071839701, atol=1e-8)
    assert np.isclose(summary.loc["Q", "final_portfolio_value"], 367407.5071839701, atol=1e-8)
    for metric in ["final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]:
        assert np.isclose(summary.loc["P39", metric], summary.loc["Q", metric], atol=1e-12)


def test_candidate_and_causal_scope_audits_pass() -> None:
    candidates = pd.read_csv(OUT / "results" / "stage3_candidate_audit_v3_10.csv")
    assert len(candidates) == 2
    assert candidates["confirmed_or_rejected"].eq("REJECTED").all()
    assert int(candidates["resolution_reason"].eq("SMA200_HARD_FAILURE").sum()) == 1
    scope = pd.read_csv(OUT / "results" / "stage3_scope_integrity_v3_10.csv")
    assert not scope["classification"].eq("UNEXPECTED_DIFFERENCE").any()
    assert int(scope["classification"].eq("DIRECT_STAGE3_DELAY").sum()) == 1
    lineage = pd.read_csv(OUT / "results" / "causal_lineage_audit_v3_10.csv")
    assert not lineage["classification"].eq("UNEXPLAINED_PATH_DIFFERENCE").any()


def test_drift_differences_are_indirect_not_blocked() -> None:
    scope = pd.read_csv(OUT / "results" / "stage3_scope_integrity_v3_10.csv")
    drift = scope.loc[scope["B_actions"].str.contains("DRIFT_SELL", na=False)]
    assert len(drift) == 3
    assert drift["classification"].eq("INDIRECT_PATH_DIFFERENCE").all()
    assert not drift["Q_actions"].str.contains("BLOCK", na=False).any()


def test_promotion_integrity_and_rolling_starts_pass() -> None:
    verdict = json.loads((OUT / "artifacts" / "promotion_verdict_v3_10.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "A. V3.10 STAGE3 CONFIRMATION PROMOTED"
    assert verdict["all_gates_pass"] is True
    assert np.isclose(verdict["uplift_capture_ratio"], 1.0, atol=1e-12)
    no_lookahead = json.loads((OUT / "artifacts" / "no_lookahead_audit_v3_10.json").read_text(encoding="utf-8"))
    assert no_lookahead["status"] == "PASS"
    assert no_lookahead["prefix_trade_identity_through_2024_12_31"] is True
    dca = pd.read_csv(OUT / "results" / "fixed_dca_integrity_v3_10.csv")
    assert dca["all_match"].all()
    rolling = pd.read_csv(OUT / "results" / "rolling_start_v3_10.csv")
    assert int((rolling["Q_final_portfolio_value"] > rolling["B_final_portfolio_value"]).sum()) == 4


def test_stage4_and_crashes_are_not_suppressed() -> None:
    stage4 = pd.read_csv(OUT / "results" / "stage4_integrity_v3_10.csv")
    assert set(stage4["model"]) >= {"B", "P39", "Q"}
    assert np.isclose(stage4.loc[stage4["model"].eq("Q"), "exposure_after"].iloc[0], 0.25, atol=1e-10)
    crash = pd.read_csv(OUT / "results" / "crash_integrity_v3_10.csv")
    assert len(crash) > 0 and crash["q_not_suppressed"].all()

