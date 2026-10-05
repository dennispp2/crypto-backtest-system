from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pandas as pd

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from crypto_backtest.v31_engine import V31State
from crypto_backtest.v310_forward import (
    add_hash_chain,
    append_verified,
    scale_state,
    state_from_dict,
    state_to_dict,
    state_value,
)
from run_forward_v3_10 import load_exception_ledger, signal_ledger


def test_forward_config_has_strict_cutoff_and_no_optimization() -> None:
    config = json.loads((PROJECT / "config/config_frozen_v3_10_forward.json").read_text(encoding="utf-8"))
    assert config["label"] == "FORWARD_PAPER_ONLY"
    assert config["historical_cutoff"] == "2026-09-03T04:00:00+00:00"
    assert config["checkpoint"]["minimum_oos_calendar_days"] == 180
    assert config["checkpoint"]["minimum_resolved_candidates"] == 3
    assert "historical parameter search" in config["prohibited"]


def test_state_round_trip_keeps_fsm_and_dates() -> None:
    state = V31State(
        normal_cash=123.0, macro_state="ACCUMULATION", stage=4,
        last_signal_date=pd.Timestamp("2026-09-02", tz="UTC"),
        accumulation_lock_until=pd.Timestamp("2026-09-05", tz="UTC"),
    )
    restored = state_from_dict(state_to_dict(state))
    assert restored.macro_state == "ACCUMULATION"
    assert restored.stage == 4
    assert restored.normal_cash == 123.0
    assert restored.last_signal_date == state.last_signal_date
    assert restored.accumulation_lock_until == state.accumulation_lock_until


def test_scale_state_is_value_homogeneous() -> None:
    state = V31State(
        qty={"BTC": 0.1, "ETH": 1.0}, normal_cash=500.0,
        pending={"BTC": 2.0, "ETH": 3.0}, tactical_bear_cash=250.0,
    )
    prices = {"BTC": 50_000.0, "ETH": 2_000.0}
    scaled = scale_state(state, 0.25)
    assert abs(state_value(scaled, prices) - 0.25 * state_value(state, prices)) < 1e-10
    assert scaled.macro_state == state.macro_state
    assert scaled.stage == state.stage


def test_hash_chain_is_order_and_value_sensitive() -> None:
    frame = pd.DataFrame([
        {"record_id": "a", "value": 1.0},
        {"record_id": "b", "value": 2.0},
    ])
    chained = add_hash_chain(frame)
    assert chained.iloc[0]["prev_record_hash"] == "GENESIS"
    assert chained.iloc[1]["prev_record_hash"] == chained.iloc[0]["record_hash"]
    changed = frame.copy()
    changed.loc[0, "value"] = 1.5
    assert add_hash_chain(changed).iloc[-1]["record_hash"] != chained.iloc[-1]["record_hash"]


def test_candidate_outcome_vocabulary_is_closed() -> None:
    config = json.loads((PROJECT / "config/config_frozen_v3_10_forward.json").read_text(encoding="utf-8"))
    assert set(config["candidate_outcomes"]) == {
        "REJECTED_FALSE_BEAR", "CONFIRMED_STAGE3", "SMA200_HARD_FAILURE",
        "STAGE4_OVERRIDE", "CRASH_OVERRIDE", "OPEN_UNRESOLVED",
    }


def test_signal_ledger_keeps_existing_day_as_append_only_prefix() -> None:
    def result(model: str) -> SimpleNamespace:
        rows = []
        for day in ("2026-09-04", "2026-09-05"):
            rows.append({
                "strategy": model,
                "model": model,
                "signal_date": pd.Timestamp(day, tz="UTC") - pd.Timedelta(days=1),
                "signal_available_at": pd.Timestamp(day, tz="UTC"),
                "execution_4h_open": pd.Timestamp(day, tz="UTC"),
            })
        return SimpleNamespace(signals=pd.DataFrame(rows))

    ledger = signal_ledger(result("B"), result("Q"))
    assert ledger["record_id"].tolist() == [
        "SIGNAL:B:2026-09-04T00:00:00+00:00",
        "SIGNAL:Q:2026-09-04T00:00:00+00:00",
        "SIGNAL:B:2026-09-05T00:00:00+00:00",
        "SIGNAL:Q:2026-09-05T00:00:00+00:00",
    ]


def test_successful_run_retains_existing_exception_ledger(tmp_path: Path) -> None:
    path = tmp_path / "forward_execution_exceptions.csv"
    original = pd.DataFrame([{
        "record_id": "EXCEPTION:1",
        "timestamp": "2026-09-05T00:00:00+00:00",
        "event_type": "EXECUTION_EXCEPTION",
        "severity": "SAFETY_FAIL",
        "message": "example",
        "action_taken": "HALT_NO_RECORD_REWRITE",
    }])
    add_hash_chain(original).to_csv(path, index=False)

    loaded = load_exception_ledger(path)
    appended, _ = append_verified(loaded, path)

    assert appended == 0
    assert pd.read_csv(path)["record_id"].tolist() == ["EXCEPTION:1"]
