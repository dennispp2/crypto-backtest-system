from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v3_9"


def test_all_required_v39_outputs_exist_and_are_nonempty() -> None:
    required = [
        "report/FINAL_REPORT_V3_9.md",
        "results/summary_v3_9.csv",
        "results/daily_portfolio_v3_9.csv",
        "results/trade_log_v3_9.csv",
        "results/regime_log_v3_9.csv",
        "results/bull_persistence_blocked_sells_v3_9.csv",
        "results/bear_reentry_audit_v3_9.csv",
        "results/2021_peak_guard_audit_v3_9.csv",
        "results/event_drawdown_audit_v3_9.csv",
        "results/rolling_start_v3_9.csv",
        "artifacts/no_lookahead_audit_v3_9.json",
        "config_frozen_v3_9.json",
        "artifacts/run_manifest_v3_9.json",
        *[f"figures/{idx:02d}_{name}_v3_9.png" for idx, name in enumerate([
            "equity_curve", "normalized_growth", "drawdown", "bull_participation",
            "2021_2022_safety", "2025_2026_safety",
        ], start=1)],
    ]
    assert all((OUT / relative).is_file() and (OUT / relative).stat().st_size > 0 for relative in required)


def test_v31_replay_and_challenger_metrics_are_stable() -> None:
    summary = pd.read_csv(OUT / "results" / "summary_v3_9.csv").set_index("model")
    assert np.isclose(summary.loc["B", "final_portfolio_value"], 348746.8528777533, atol=1e-8)
    assert np.isclose(summary.loc["B", "twr_cagr"], 0.4769146261923145, atol=1e-12)
    assert np.isclose(summary.loc["B", "maximum_drawdown"], -0.3951313419600695, atol=1e-12)
    assert np.isclose(summary.loc["P", "final_portfolio_value"], 367407.5071839701, atol=1e-8)


def test_frozen_verdict_fails_only_material_bull_edge_gates() -> None:
    verdict = json.loads((OUT / "artifacts" / "promotion_verdict_v3_9.json").read_text(encoding="utf-8"))
    assert verdict["verdict"] == "D. V3.9 REJECTED - NO MATERIAL BULL EDGE"
    failed = {key for key, value in verdict["checks"].items() if not value}
    assert failed == {
        "G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP",
        "G2_BULL_TIME_GTE85_DELTA_GTE_15PP",
    }


def test_drift_audit_does_not_mislabel_guard_inactive_events_as_blocked() -> None:
    audit = pd.read_csv(OUT / "results" / "bull_persistence_blocked_sells_v3_9.csv")
    assert len(audit) == 3
    assert not audit["blocked_or_executed"].eq("BLOCKED").any()
    assert audit["blocked_or_executed"].eq("NOT_EXECUTED_GUARD_INACTIVE").all()


def test_stage4_and_crash_integrity_pass() -> None:
    stage4 = pd.read_csv(OUT / "results" / "stage4_integrity_v3_9.csv")
    assert set(stage4["model"]) >= {"B", "P"}
    p = stage4.loc[stage4["model"].eq("P")].iloc[0]
    assert np.isclose(float(p["exposure_after"]), 0.25, atol=1e-10)
    crash = pd.read_csv(OUT / "results" / "crash_integrity_v3_9.csv")
    assert len(crash) > 0 and crash["not_suppressed"].all()


def test_no_lookahead_and_all_fixed_dca_rows_pass() -> None:
    audit = json.loads((OUT / "artifacts" / "no_lookahead_audit_v3_9.json").read_text(encoding="utf-8"))
    assert audit["status"] == "PASS"
    assert audit["prefix_trade_identity_through_2024_12_31"] is True
    dca = pd.read_csv(OUT / "results" / "fixed_dca_integrity_v3_9.csv")
    assert dca["all_match"].all()


def test_report_states_2020_guard_activation_correctly() -> None:
    report = (OUT / "report" / "FINAL_REPORT_V3_9.md").read_text(encoding="utf-8")
    assert "Guard 曾在 2020/5 NEW_BULL 後啟動" in report
    assert "Guard 尚未啟動" not in report
