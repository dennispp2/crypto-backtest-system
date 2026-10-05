from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_backtest.v38_engine import (  # noqa: E402
    AHR_ACTION,
    V38OverlayState,
    _advance_completed_close_counter,
    _ahr_condition,
    _clear_cooldown,
    _cooldown_active,
    _cooldown_remaining,
    _reset_cooldown,
)


def _rules() -> dict:
    return json.loads((ROOT / "config" / "config_frozen_v3_8.json").read_text(encoding="utf-8"))


def test_v38_freeze_hashes_and_only_change() -> None:
    rules = _rules()
    assert rules["frozen_before_formal_run"] is True
    assert rules["forbid_parameter_search"] is True
    assert rules["execution_overlay"]["cooldown_completed_daily_closes_after_any_tactical_sell"] == 3
    assert rules["execution_overlay"]["additional_duplicate_suppression"] is False
    assert rules["execution_overlay"]["sell_lock_after_ahr"] is False
    assert rules["execution_overlay"]["restrictable_action"] == f"{AHR_ACTION} only"
    assert hashlib.sha256((ROOT / "config" / "config_frozen_v3_1.json").read_bytes()).hexdigest() == rules["base_config_sha256"]
    assert hashlib.sha256((ROOT / "config" / "config_frozen_v3_7.json").read_bytes()).hexdigest() == rules["v3_7_config_sha256"]
    assert hashlib.sha256((ROOT / "src" / "crypto_backtest" / "v37_engine.py").read_bytes()).hexdigest() == rules["v3_7_engine_sha256"]


def test_three_completed_close_boundary() -> None:
    rules = _rules()
    state = V38OverlayState(normal_cash=6000.0)
    state.signal_index = 10
    _reset_cooldown(state)
    assert _cooldown_remaining(state, rules) == 3
    for expected in (1, 2, 3):
        state.signal_index += 1
        _advance_completed_close_counter(state)
        assert state.cooldown_completed_closes == expected
        assert _cooldown_active(state, rules)
    assert _cooldown_remaining(state, rules) == 0
    state.signal_index += 1
    _advance_completed_close_counter(state)
    assert state.cooldown_completed_closes == 4
    assert _cooldown_remaining(state, rules) == 0
    assert not _cooldown_active(state, rules)
    _clear_cooldown(state)
    assert state.cooldown_start_signal_index is None


def test_ahr_condition_is_frozen_v31_condition() -> None:
    base = {"buyback": {"ahr999_threshold": 0.35}}
    row = pd.Series({"ahr999_fixed_arithmetic": 0.35})
    assert _ahr_condition(row, "BEAR", base)
    assert _ahr_condition(row, "DEEP_BEAR", base)
    assert _ahr_condition(row, "ACCUMULATION", base)
    assert not _ahr_condition(row, "NEW_BULL", base)
    assert not _ahr_condition(pd.Series({"ahr999_fixed_arithmetic": 0.350001}), "BEAR", base)


def test_engine_contains_no_duplicate_or_post_buy_sell_lock_logic() -> None:
    source = (ROOT / "src" / "crypto_backtest" / "v38_engine.py").read_text(encoding="utf-8").lower()
    for token in ("duplicate_suppression", "sticky_base", "sell_cooldown", "episode_lock", "rearm_rule"):
        assert token not in source
    for token in ("2022-06-01", "2022-07-31", "2026-02-01", "2026-06-30", "promotion_gates"):
        assert token not in source
