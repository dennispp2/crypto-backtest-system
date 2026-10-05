from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v3_7"


def test_required_v37_deliverables_exist_and_are_nonempty() -> None:
    required = [
        OUT / "FINAL_REPORT_V3_7.md",
        OUT / "config_frozen_v3_7.json",
        OUT / "results" / "summary_v3_7.csv",
        OUT / "results" / "daily_portfolio_v3_7.csv",
        OUT / "results" / "trade_log_v3_7.csv",
        OUT / "results" / "shadow_state_parity_audit_v3_7.csv",
        OUT / "results" / "execution_overlay_audit_v3_7.csv",
        OUT / "results" / "bottom_whipsaw_audit_v3_7.csv",
        OUT / "results" / "event_drawdown_audit_v3_7.csv",
        OUT / "artifacts" / "no_lookahead_audit_v3_7.json",
        OUT / "artifacts" / "run_manifest_v3_7.json",
    ]
    required.extend(OUT / "figures" / name for name in [
        "01_equity_curve_v3_7.png", "02_normalized_growth_v3_7.png",
        "03_drawdown_v3_7.png", "04_2022_execution_overlay_v3_7.png",
        "05_2026_execution_overlay_v3_7.png", "06_tactical_frequency_v3_7.png",
        "07_shadow_state_parity_v3_7.png",
    ])
    assert all(path.exists() and path.stat().st_size > 0 for path in required)


def test_v31_replay_and_shadow_parity_are_exact() -> None:
    summary = pd.read_csv(OUT / "results" / "summary_v3_7.csv").set_index("model")
    b = summary.loc["B"]
    assert np.isclose(b["final_portfolio_value"], 348746.8528777533, atol=1e-8, rtol=0)
    assert np.isclose(b["twr_cagr"], 0.4769146261923145, atol=1e-12, rtol=0)
    assert np.isclose(b["maximum_drawdown"], -0.3951313419600695, atol=1e-12, rtol=0)
    assert int(b["tactical_event_count"]) == 106
    parity = json.loads((OUT / "artifacts" / "shadow_state_parity_summary_v3_7.json").read_text(encoding="utf-8"))
    assert parity["pass"] is True
    assert all(value == 0 for key, value in parity.items() if key.endswith("_mismatch_days"))


def test_overlay_restricts_only_ahr_and_preserves_non_ahr_orders() -> None:
    audit = pd.read_csv(OUT / "results" / "execution_overlay_audit_v3_7.csv")
    restricted = audit.loc[audit["restricted_by_overlay"].astype(str).str.lower().eq("true")]
    assert set(restricted["shadow_signal_type"]) == {"AHR_VALUE_BUY"}
    nonexecute = audit.loc[audit["overlay_decision"].ne("EXECUTE")]
    assert not nonexecute["shadow_signal_type"].isin([
        "RISK_SELL", "RIGHT_SIDE_TO_50", "RIGHT_SIDE_TO_60", "NEW_BULL_REDEPLOY",
    ]).any()
    scope = json.loads((OUT / "artifacts" / "overlay_scope_audit_v3_7.json").read_text(encoding="utf-8"))
    assert scope["pass"] is True
    assert scope["shadow_tactical_events_represented"] == 106


def test_dca_and_execution_integrity_pass() -> None:
    dca = pd.read_csv(OUT / "results" / "fixed_dca_row_integrity_v3_7.csv")
    assert set(dca["model"]) == {"A", "B", "J"}
    assert dca["all_match"].astype(bool).all()
    integrity = json.loads((OUT / "artifacts" / "no_lookahead_audit_v3_7.json").read_text(encoding="utf-8"))
    assert integrity["no_lookahead_pass"] is True
    assert integrity["execution_integrity_pass"] is True
    assert integrity["same_timestamp_opposite_tactical_action_violations"] == 0


def test_reported_verdict_matches_frozen_gate_failures() -> None:
    verdict = json.loads((OUT / "artifacts" / "promotion_verdict_v3_7.json").read_text(encoding="utf-8"))
    assert verdict["promotion_gate"] == "FAIL"
    assert verdict["final_verdict"] == "B. V3.1 REMAINS CHAMPION"
    assert verdict["checks"]["G0_SHADOW_STATE_PARITY_ALL_ZERO"] is True
    assert verdict["checks"]["G1_OVERLAY_RESTRICTED_ACTIONS_AHR_ONLY"] is True
    assert verdict["checks"]["G11_ALL_INTEGRITY_PASS"] is True
    assert not all(verdict["checks"].values())
