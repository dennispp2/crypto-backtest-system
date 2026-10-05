from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

PROJECT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.v31_necessity_analysis import apply_classifications  # noqa: E402


def test_base_diagnostic_classification_direction() -> None:
    rules = json.loads(
        (PROJECT_DIR / "config" / "config_frozen_v31_necessity_audit.json").read_text(encoding="utf-8")
    )
    rows = pd.DataFrame([
        {
            "final_wealth_contribution_fraction": 0.02,
            "dd_protection_contribution_pp": 0.0,
            "max_local_dd_protection_pp": 0.0,
        },
        {
            "final_wealth_contribution_fraction": -0.01,
            "dd_protection_contribution_pp": 0.0,
            "max_local_dd_protection_pp": 0.0,
        },
        {
            "final_wealth_contribution_fraction": 0.0,
            "dd_protection_contribution_pp": 0.0,
            "max_local_dd_protection_pp": 1.1,
        },
        {
            "final_wealth_contribution_fraction": 0.0,
            "dd_protection_contribution_pp": 0.0,
            "max_local_dd_protection_pp": 0.0,
        },
    ])
    classified = apply_classifications(rows, rules)
    assert classified["classification_base"].tolist() == [
        "RETURN_ESSENTIAL", "HARMFUL", "RISK_ESSENTIAL", "REDUNDANT"
    ]


def test_completed_audit_output_integrity() -> None:
    output = PROJECT_DIR / "v31_necessity_audit"
    events = pd.read_csv(output / "results" / "leave_one_event_out_results.csv")
    clusters = pd.read_csv(output / "results" / "round_trip_clusters.csv")
    interaction = pd.read_csv(output / "results" / "interaction_audit.csv")
    event_ids: list[int] = []
    for value in clusters["events_inside"]:
        event_ids.extend(int(item) for item in str(value).split("|"))
    assert len(events) == 106
    assert len(event_ids) == 106
    assert len(set(event_ids)) == 106
    assert set(event_ids) == set(events["tactical_event_id"].astype(int))
    assert len(interaction) == 45
    assert events["forward_outcome_usage"].eq("EX_POST_DIAGNOSTIC_ONLY").all()
    assert events["classification"].notna().all()
