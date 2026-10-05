from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_universe_diagnostic", ROOT / "run_universe_diagnostic.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_frozen_universe_weights_and_cash_are_exact() -> None:
    rules = json.loads((ROOT / "config" / "frozen_universe_rules.json").read_text(encoding="utf-8"))
    assert rules["universes"]["U1"]["weights"] == {"BTC": 1.0, "ETH": 0.0, "BNB": 0.0}
    assert rules["universes"]["U2"]["weights"] == {"BTC": 0.625, "ETH": 0.375, "BNB": 0.0}
    assert rules["universes"]["U3"]["weights"] == {"BTC": 0.5, "ETH": 0.3, "BNB": 0.2}
    for universe in rules["universes"].values():
        assert sum(universe["weights"].values()) == 1.0
        assert sum(universe["initial_allocation_usd"].values()) == 20_000.0
        assert universe["initial_allocation_usd"]["USD"] == 6_000.0


def test_scenario_disables_every_non_fixed_dca_feature() -> None:
    rules = json.loads((ROOT / "config" / "frozen_universe_rules.json").read_text(encoding="utf-8"))
    rules["resolved_costs"] = {"fee": 0.001, "slippage": 0.0005}
    scenario = MODULE.build_scenario("U3", 2020, rules)
    assert not scenario.dynamic_dca
    assert not scenario.tactical
    assert not scenario.annual_rebalance
    assert not scenario.cash_protection
    assert scenario.fee == 0.001
    assert scenario.slippage == 0.0005


def test_comparison_sign_convention() -> None:
    summary = pd.DataFrame(
        [
            {"start_year": 2020, "universe": "U1", "final_portfolio_value": 100.0, "twr_cagr": 0.1, "maximum_drawdown": -0.5, "calmar": 0.2},
            {"start_year": 2020, "universe": "U2", "final_portfolio_value": 120.0, "twr_cagr": 0.2, "maximum_drawdown": -0.4, "calmar": 0.5},
            {"start_year": 2020, "universe": "U3", "final_portfolio_value": 150.0, "twr_cagr": 0.3, "maximum_drawdown": -0.3, "calmar": 1.0},
        ]
    )
    out = MODULE.build_comparisons(summary, [["U3", "U2"]]).iloc[0]
    assert out["delta_final_value"] == 30.0
    assert out["delta_cagr_percentage_points"] == pytest.approx(10.0)
    assert out["delta_max_drawdown_percentage_points"] == pytest.approx(10.0)
    assert out["delta_calmar"] == 0.5
