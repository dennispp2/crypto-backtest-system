from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from crypto_backtest.v36_engine import (
    V36State,
    _crash_sell_pending,
    _end_episode,
    _start_episode,
    _update_rearm,
)
from crypto_backtest.v36_indicators import add_v36_features


def _json(name: str) -> dict:
    return json.loads((ROOT / "config" / name).read_text(encoding="utf-8"))


def test_v36_frozen_directly_on_v31_hash() -> None:
    config = _json("config_frozen_v3_6.json")
    base = ROOT / "config" / "config_frozen_v3_1.json"
    digest = hashlib.sha256(base.read_bytes()).hexdigest()
    assert config["frozen_before_formal_run"] is True
    assert config["forbid_parameter_search"] is True
    assert config["base_version"] == "V3.1 FSM-only Model B"
    assert digest == config["base_config_sha256"]


def test_v36_engine_has_no_later_strategy_inheritance_or_audit_dates() -> None:
    source = (ROOT / "src" / "crypto_backtest" / "v36_engine.py").read_text(encoding="utf-8").lower()
    for forbidden in ("v32_", "v33_", "v34_", "v35_", "2022-06", "2026-02", "promotion_gate"):
        assert forbidden not in source


def test_completed_close_new_low_is_backward_only() -> None:
    dates = pd.date_range("2020-01-01", periods=25, tz="UTC", freq="D")
    daily = pd.DataFrame({
        "signal_date": dates,
        "close_time": dates + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
        "signal_available_at": dates + pd.Timedelta(days=1),
        "close": [100.0] * 20 + [99.0, 101.0, 102.0, 103.0, 104.0],
    })
    out = add_v36_features(daily, _json("config_frozen_v3_6.json"))
    assert bool(out.loc[20, "new_20d_closing_low"])
    assert not bool(out.loc[21, "new_20d_closing_low"])
    assert bool(out.loc[23, "no_new_20d_closing_low_recent3"])
    changed = daily.copy()
    changed.loc[24, "close"] = 1.0
    out_changed = add_v36_features(changed, _json("config_frozen_v3_6.json"))
    pd.testing.assert_frame_equal(out.iloc[:24], out_changed.iloc[:24])


def test_episode_persists_until_explicit_end() -> None:
    state = V36State()
    _start_episode(state)
    episode = state.accumulation_episode_id
    state.macro_state = "DEEP_BEAR"
    _start_episode(state)
    assert state.accumulation_episode_id == episode
    assert state.accumulation_episode_active
    _end_episode(state)
    assert not state.accumulation_episode_active
    _start_episode(state)
    assert state.accumulation_episode_id == episode + 1


def test_value_rearm_requires_all_three_frozen_conditions() -> None:
    state = V36State()
    _start_episode(state)
    state.value_base_buy_used = True
    state.executed_episode_signals.add("AHR_BASE_BUY")
    state.active_target = 0.25
    state.last_accumulation_sell_at = pd.Timestamp("2022-01-01T00:00:00Z")
    row = pd.Series({
        "open_time": pd.Timestamp("2022-01-08T00:00:00Z"),
        "ahr999_fixed_arithmetic": 0.34,
        "no_new_20d_closing_low_recent3": True,
    })
    actions: list[str] = []
    _update_rearm(state, row, _json("config_frozen_v3_1.json"), _json("config_frozen_v3_6.json"), actions)
    assert state.value_buy_rearmed
    assert "AHR_BASE_BUY" not in state.executed_episode_signals
    assert actions == ["VALUE_BUY_REARMED"]


def test_value_rearm_fails_before_seven_days_or_with_new_low() -> None:
    base, rules = _json("config_frozen_v3_1.json"), _json("config_frozen_v3_6.json")
    for timestamp, stable in (("2022-01-07T23:59:59Z", True), ("2022-01-08T00:00:00Z", False)):
        state = V36State(active_target=0.25)
        _start_episode(state)
        state.value_base_buy_used = True
        state.last_accumulation_sell_at = pd.Timestamp("2022-01-01T00:00:00Z")
        row = pd.Series({
            "open_time": pd.Timestamp(timestamp), "ahr999_fixed_arithmetic": 0.34,
            "no_new_20d_closing_low_recent3": stable,
        })
        _update_rearm(state, row, base, rules, [])
        assert not state.value_buy_rearmed


def test_eligible_crash_sell_has_buy_priority_veto() -> None:
    row_l1 = pd.Series({"crash_level1_raw": True, "crash_level2_market_raw": False})
    assert _crash_sell_pending(V36State(crash_armed=True), row_l1)
    assert not _crash_sell_pending(V36State(crash_armed=False), row_l1)
    row_l2 = pd.Series({"crash_level1_raw": False, "crash_level2_market_raw": True})
    assert _crash_sell_pending(V36State(crash_level1_days_remaining=3, crash_level2_fired=False), row_l2)
