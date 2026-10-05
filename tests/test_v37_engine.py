from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from crypto_backtest.v37_analysis import shadow_state_parity_audit
from crypto_backtest.v37_engine import (
    AHR_ACTION,
    V37OverlayState,
    _ahr_condition,
    _cooldown_active,
    _priority,
)


def test_v37_config_is_frozen_and_uses_v31_only() -> None:
    rules = json.loads((PROJECT / "config" / "config_frozen_v3_7.json").read_text(encoding="utf-8"))
    assert rules["frozen_before_formal_run"] is True
    assert rules["forbid_parameter_search"] is True
    assert rules["base_version"] == "V3.1 Model B"
    assert rules["execution_overlay"]["restrictable_action"] == f"{AHR_ACTION} only"


def test_seven_day_cooldown_boundary_is_calendar_exact() -> None:
    start = pd.Timestamp("2022-06-10", tz="UTC")
    state = V37OverlayState(normal_cash=6000.0, ahr_cooldown_until=start + pd.Timedelta(days=7))
    assert _cooldown_active(state, start + pd.Timedelta(days=6, hours=23))
    assert not _cooldown_active(state, start + pd.Timedelta(days=7))


def test_ahr_condition_uses_completed_value_and_shadow_bear_family() -> None:
    rules = {"buyback": {"ahr999_threshold": 0.35}}
    row = pd.Series({"ahr999_fixed_arithmetic": 0.34})
    assert _ahr_condition(row, "BEAR", rules)
    assert _ahr_condition(row, "DEEP_BEAR", rules)
    assert _ahr_condition(row, "ACCUMULATION", rules)
    assert not _ahr_condition(row, "NEW_BULL", rules)
    assert not _ahr_condition(pd.Series({"ahr999_fixed_arithmetic": 0.36}), "BEAR", rules)


def test_tactical_priority_puts_sell_before_newbull_right_and_ahr() -> None:
    events = [
        {"action": AHR_ACTION, "side": "BUY"},
        {"action": "TACTICAL_BUYBACK_RIGHT_TO_50", "side": "BUY"},
        {"action": "TACTICAL_BUYBACK_NEW_BULL_REDEPLOY", "side": "BUY"},
        {"action": "TACTICAL_SELL_STAGE4", "side": "SELL"},
    ]
    assert [event["action"] for event in sorted(events, key=_priority)] == [
        "TACTICAL_SELL_STAGE4",
        "TACTICAL_BUYBACK_NEW_BULL_REDEPLOY",
        "TACTICAL_BUYBACK_RIGHT_TO_50",
        AHR_ACTION,
    ]


def test_parity_audit_detects_zero_and_one_mismatch() -> None:
    date = pd.to_datetime(["2022-01-01", "2022-01-02"], utc=True)
    b = pd.DataFrame({
        "date": date, "macro_state": ["BULL", "BEAR"], "sell_stage": [0, 2],
        "cycle_id": [0, 1], "active_target": [0.95, 0.50],
        "crash_level1_active": [False, True],
    })
    j = pd.DataFrame({
        "date": date, "macro_state_shadow": ["BULL", "BEAR"], "sell_stage_shadow": [0, 2],
        "cycle_id_shadow": [0, 1], "active_target_shadow": [0.95, 0.50],
        "crash_state_shadow": [False, True], "new_bull_state_shadow": [False, False],
    })
    _, summary = shadow_state_parity_audit(b, j)
    assert summary["pass"] is True
    j.loc[1, "sell_stage_shadow"] = 3
    _, mismatch = shadow_state_parity_audit(b, j)
    assert mismatch["pass"] is False
    assert mismatch["stage_mismatch_days"] == 1


def test_v37_engine_does_not_import_later_strategy_versions() -> None:
    source = (PROJECT / "src" / "crypto_backtest" / "v37_engine.py").read_text(encoding="utf-8").lower()
    for token in ("v32_", "v33_", "v34_", "v35_", "v36_", "requalification", "level3"):
        assert token not in source
