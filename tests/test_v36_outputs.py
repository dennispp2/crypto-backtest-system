from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v3_6"


def test_v36_required_delivery_files_exist() -> None:
    required = [
        OUT / "FINAL_REPORT_V3_6.md",
        OUT / "results" / "summary_v3_6.csv",
        OUT / "results" / "daily_portfolio_v3_6.csv",
        OUT / "results" / "trade_log_v3_6.csv",
        OUT / "results" / "bottom_whipsaw_audit_v3_6.csv",
        OUT / "results" / "bottom_whipsaw_summary_v3_6.csv",
        OUT / "results" / "event_drawdown_audit_v3_6.csv",
        OUT / "artifacts" / "no_lookahead_audit_v3_6.json",
        OUT / "artifacts" / "run_manifest_v3_6.json",
        *[OUT / "figures" / name for name in (
            "01_equity_curve_h0_a_b_h_v3_6.png",
            "02_normalized_twr_h0_a_b_h_v3_6.png",
            "03_drawdown_h0_a_b_h_v3_6.png",
            "04_2022_bottom_zoom_v3_6.png",
            "05_2026_bottom_zoom_v3_6.png",
            "06_monthly_tactical_event_frequency_b_vs_h_v3_6.png",
        )],
    ]
    assert all(path.exists() and path.stat().st_size > 0 for path in required)


def test_v31_replay_and_integrity_are_pass() -> None:
    replay = json.loads((OUT / "artifacts" / "v3_1_replay_integrity_v3_6.json").read_text(encoding="utf-8"))
    audit = json.loads((OUT / "artifacts" / "no_lookahead_audit_v3_6.json").read_text(encoding="utf-8"))
    assert replay["pass"] and replay["trade_rows_exact"]
    assert replay["tactical_event_count"] == 106
    assert audit["no_lookahead_pass"] and audit["execution_integrity_pass"]
    assert audit["same_timestamp_opposite_tactical_action_violations"] == 0


def test_v36_summary_and_frozen_verdict_are_consistent() -> None:
    summary = pd.read_csv(OUT / "results" / "summary_v3_6.csv").set_index("model")
    verdict = json.loads((OUT / "artifacts" / "promotion_verdict_v3_6.json").read_text(encoding="utf-8"))
    assert set(summary.index) == {"H0", "A", "B", "H"}
    assert abs(float(summary.loc["B", "final_portfolio_value"]) - 348746.8528777533) <= 1e-8
    assert abs(float(summary.loc["B", "tactical_turnover"]) - 9.367689873226654) <= 1e-10
    assert verdict["promotion_gate"] == "FAIL"
    assert verdict["final_verdict"] == "B. V3.1 REMAINS CHAMPION"


def test_bottom_audit_schema_and_required_counts() -> None:
    audit = pd.read_csv(OUT / "results" / "bottom_whipsaw_audit_v3_6.csv")
    required = {
        "timestamp", "model", "cycle_id", "accumulation_episode_id", "action",
        "signal_type", "reason", "exposure_before", "exposure_after",
        "days_since_previous_tactical_action", "days_since_previous_opposite_action",
        "ahr999", "btc_close", "sma20", "sma50", "sma200",
        "new_20d_closing_low", "rearm_status", "rebuy_cooldown",
        "gross_notional", "fee", "slippage",
    }
    assert required.issubset(audit.columns)
    summary = pd.read_csv(OUT / "results" / "bottom_whipsaw_summary_v3_6.csv").set_index(["period", "model"])
    assert int(summary.loc[("BOTTOM_2022", "B"), "bottom_tactical_event_count"]) == 12
    assert int(summary.loc[("BOTTOM_2026", "B"), "bottom_tactical_event_count"]) == 22
    assert int(summary.loc[("BOTTOM_2022", "H"), "bottom_tactical_event_count"]) == 4
    assert int(summary.loc[("BOTTOM_2026", "H"), "bottom_tactical_event_count"]) == 12
