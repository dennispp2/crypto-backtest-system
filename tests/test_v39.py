from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_backtest.v39_engine import _healthy_bull, _new_candidate, _resolve_candidate


def test_v39_config_is_frozen_and_one_change_only() -> None:
    rules = json.loads((ROOT / "config" / "config_frozen_v3_9.json").read_text(encoding="utf-8"))
    assert rules["frozen_before_formal_run"] is True
    assert rules["post_backtest_only"] is True
    assert rules["base_version"] == "V3.1 Model B"
    assert rules["bull_persistence_guard"]["new_exposure_targets"] == []
    assert rules["bull_persistence_guard"]["bear_reentry_confirmation_completed_closes"] == 3


def test_v39_frozen_v31_hashes_match() -> None:
    rules = json.loads((ROOT / "config" / "config_frozen_v3_9.json").read_text(encoding="utf-8"))
    for path_key, hash_key in (("base_config_path", "base_config_sha256"), ("base_engine_path", "base_engine_sha256")):
        digest = hashlib.sha256((ROOT / rules[path_key]).read_bytes()).hexdigest().upper()
        assert digest == rules[hash_key]


def test_healthy_bull_requires_all_completed_structure_conditions() -> None:
    row = pd.Series({
        "BTC_daily_close": 120.0, "sma50": 110.0, "sma200": 100.0,
        "sma200_slope_up": True,
    })
    assert _healthy_bull(row, {"actions": ""})
    assert not _healthy_bull(row, {"actions": "CRASH_L1:EXECUTED"})
    falling = row.copy()
    falling["sma200_slope_up"] = False
    assert not _healthy_bull(falling, {"actions": ""})


def test_stage3_candidate_counts_candidate_close_as_first_close() -> None:
    row = pd.Series({
        "signal_date": pd.Timestamp("2023-03-11", tz="UTC"),
        "open_time": pd.Timestamp("2023-03-12", tz="UTC"),
        "BTC_daily_close": 90.0, "sma20": 95.0, "sma50": 100.0, "sma200": 80.0,
    })
    candidate = _new_candidate(row, {"state_before": "EARLY_BEAR"}, True)
    assert candidate["confirmation_count"] == 1
    assert candidate["confirmation_close_1"] == 90.0


def test_bear_reentry_delay_is_calendar_days_from_original_candidate() -> None:
    first = pd.Series({
        "signal_date": pd.Timestamp("2023-03-11", tz="UTC"),
        "open_time": pd.Timestamp("2023-03-12", tz="UTC"),
        "BTC_daily_close": 90.0, "sma20": 95.0, "sma50": 100.0, "sma200": 80.0,
    })
    candidate = _new_candidate(first, {"state_before": "EARLY_BEAR"}, True)
    final = pd.Series({"signal_date": pd.Timestamp("2023-03-13", tz="UTC")})
    _resolve_candidate(candidate, outcome="CONFIRMED", row=final, reason="THREE_COMPLETED_CLOSES")
    assert candidate["days_delayed_vs_v31"] == 2.0


def test_execution_engine_contains_no_ex_post_forward_return_feature() -> None:
    source = (ROOT / "src" / "crypto_backtest" / "v39_engine.py").read_text(encoding="utf-8")
    assert "forward_return_30" not in source
    assert "forward_return_60" not in source
    assert "shift(-" not in source
