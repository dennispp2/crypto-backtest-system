from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "v3_8"


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_required_v38_deliverables_exist_and_are_nonempty() -> None:
    required = [
        "FINAL_REPORT_V3_8.md",
        "results/summary_v3_8.csv",
        "results/daily_portfolio_v3_8.csv",
        "results/trade_log_v3_8.csv",
        "results/shadow_state_parity_audit_v3_8.csv",
        "results/execution_overlay_audit_v3_8.csv",
        "results/ahr_delay_opportunity_cost_v3_8.csv",
        "results/bottom_whipsaw_audit_v3_8.csv",
        "results/event_drawdown_audit_v3_8.csv",
        "artifacts/no_lookahead_audit_v3_8.json",
        "config_frozen_v3_8.json",
        "artifacts/run_manifest_v3_8.json",
    ]
    required.extend(f"figures/0{i}_{name}_v3_8.png" for i, name in [
        (1, "equity_curve"), (2, "normalized_growth"), (3, "drawdown"),
        (4, "2022_overlay"), (5, "2026_overlay"),
        (6, "tactical_frequency"), (7, "shadow_state_parity"),
    ])
    assert all((OUT / relative).is_file() and (OUT / relative).stat().st_size > 0 for relative in required)


def test_replays_shadow_parity_and_integrity_pass() -> None:
    assert _json(OUT / "artifacts/v3_1_replay_integrity_v3_8.json")["pass"]
    assert _json(OUT / "artifacts/v3_7_j7_replay_integrity_v3_8.json")["pass"]
    assert _json(OUT / "artifacts/shadow_engine_replay_v3_8.json")["pass"]
    parity = _json(OUT / "artifacts/shadow_state_parity_summary_v3_8.json")
    assert parity["pass"] and all(value == 0 for key, value in parity.items() if key.endswith("_mismatch_days"))
    integrity = _json(OUT / "artifacts/execution_integrity_v3_8.json")
    assert integrity["pass"] and integrity["fixed_dca_row_integrity"]


def test_v38_overlay_restricts_only_ahr_and_respects_three_close_boundary() -> None:
    audit = pd.read_csv(OUT / "results/execution_overlay_audit_v3_8.csv")
    restricted = audit.loc[audit["restricted_by_overlay"].astype(str).str.lower().eq("true")]
    assert not restricted.empty
    assert restricted["shadow_signal_type"].eq("AHR_VALUE_BUY").all()
    original_ahr = audit.loc[audit["shadow_action"].eq("TACTICAL_BUYBACK_AHR999_TO_35")]
    delayed = original_ahr.loc[original_ahr["overlay_decision"].eq("DELAY")]
    assert delayed["cooldown_completed_closes"].between(1, 3).all()
    opportunity = pd.read_csv(OUT / "results/ahr_delay_opportunity_cost_v3_8.csv")
    executed = opportunity.loc[opportunity["executed_or_cancelled"].eq("EXECUTED")]
    assert not executed.empty and executed["delay_completed_closes"].eq(3).all()
    assert opportunity["executed_or_cancelled"].ne("PENDING_AT_END").all()


def test_opportunity_cost_is_reporting_only_and_has_forward_returns() -> None:
    opportunity = pd.read_csv(OUT / "results/ahr_delay_opportunity_cost_v3_8.csv")
    assert opportunity["30d_btc_return_after_original_signal"].notna().all()
    assert opportunity["60d_btc_return_after_original_signal"].notna().all()
    engine = (ROOT / "src/crypto_backtest/v38_engine.py").read_text(encoding="utf-8").lower()
    assert "30d_btc_return" not in engine and "60d_btc_return" not in engine


def test_formal_verdict_is_consistent_with_failed_gates() -> None:
    verdict = _json(OUT / "artifacts/promotion_verdict_v3_8.json")
    assert verdict["promotion_gate"] == "FAIL"
    assert verdict["final_verdict"] == "B. V3.1 REMAINS CHAMPION"
    assert not all(verdict["checks"].values())
    comparison = pd.read_csv(OUT / "results/model_comparison_v3_8.csv").iloc[0]
    assert comparison["final_value_fraction_of_b"] < 0.98
    assert comparison["short_three_close_whipsaw_reduction_fraction"] >= 0.50
