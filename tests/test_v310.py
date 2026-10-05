from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def test_v310_config_is_frozen_and_one_change_only() -> None:
    frozen = json.loads((ROOT / "config" / "config_frozen_v3_10.json").read_text(encoding="utf-8"))
    rule = frozen["isolated_stage3_confirmation"]
    assert frozen["frozen_before_formal_run"] is True
    assert frozen["post_backtest_only"] is True
    assert frozen["base_version"] == "V3.1 Model B"
    assert rule["confirmation_completed_closes"] == 3
    assert rule["sma200_hard_failure_completed_closes"] == 3
    assert rule["drift_sell"] == "unchanged V3.1; never directly suppressed"


def test_frozen_source_hashes_match() -> None:
    frozen = json.loads((ROOT / "config" / "config_frozen_v3_10.json").read_text(encoding="utf-8"))
    pairs = [
        ("base_config_path", "base_config_sha256"),
        ("base_engine_path", "base_engine_sha256"),
        ("v39_config_path", "v39_config_sha256"),
        ("v39_engine_path", "v39_engine_sha256"),
        ("v39_runner_path", "v39_runner_sha256"),
        ("v39_manifest_path", "v39_manifest_sha256"),
        ("v39_summary_path", "v39_summary_sha256"),
    ]
    for path_key, hash_key in pairs:
        digest = hashlib.sha256((ROOT / frozen[path_key]).read_bytes()).hexdigest().upper()
        assert digest == frozen[hash_key]


def test_v310_engine_has_no_v39_drift_guard_or_forward_feature() -> None:
    source = (ROOT / "src" / "crypto_backtest" / "v310_engine.py").read_text(encoding="utf-8")
    assert "from .v39_engine import _new_candidate, _resolve_candidate" in source
    assert "_process_drift(state, row" in source
    assert "_healthy_bull" not in source
    assert "blocked_drift" not in source
    assert "forward_return_30" not in source
    assert "forward_return_60" not in source
    assert "shift(-" not in source


def test_second_candidate_does_not_claim_a_shadow_b_stage3_fill() -> None:
    audit = pd.read_csv(ROOT / "v3_10" / "results" / "stage3_candidate_audit_v3_10.csv")
    second = audit.loc[audit["candidate_id"].eq(2)].iloc[0]
    assert not bool(second["shadow_v31_stage3_executed"])
    assert pd.isna(second["B_stage3_execution_date"])

