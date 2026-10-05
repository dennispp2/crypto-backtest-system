from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "src"))

from crypto_backtest.v31_ai import annual_walk_forward_predictions
from crypto_backtest.v31_engine import V31Scenario, run_v31_backtest
from crypto_backtest.v31_indicators import add_v31_features


def rules() -> dict:
    return json.loads((PROJECT / "config" / "config_frozen_v3_1.json").read_text(encoding="utf-8"))


def scenario(model: str) -> V31Scenario:
    return V31Scenario(
        name=f"MODEL {model}", model=model, use_fsm=model != "A", use_ai=model == "C"
    )


def test_future_label_requires_all_60_completed_closes() -> None:
    n = 800
    dates = pd.date_range("2013-01-01", periods=n, freq="D", tz="UTC")
    close = pd.Series(np.linspace(100.0, 400.0, n))
    daily = pd.DataFrame({
        "signal_date": dates, "signal_available_at": dates + pd.Timedelta(days=1),
        "open_time": dates, "close_time": dates + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1),
        "open": close, "high": close * 1.01, "low": close * 0.99, "close": close,
        "sma10": close.rolling(10).mean(), "sma20": close.rolling(20).mean(),
        "sma50": close.rolling(50).mean(), "sma200": close.rolling(200).mean(),
        "bb_mid": close.rolling(20).mean(),
        "bb_upper": close.rolling(20).mean() + 2 * close.rolling(20).std(ddof=0),
        "bb_lower": close.rolling(20).mean() - 2 * close.rolling(20).std(ddof=0),
        "ahr999_fixed_arithmetic": 1.0,
    })
    out = add_v31_features(daily, rules())
    assert out["bear_label"].tail(60).isna().all()
    assert out["label_end_date"].iloc[250] == out["signal_date"].iloc[310]
    assert set(rules()["ai"]["features"]) == {
        "feature_price_sma50", "feature_price_sma200", "feature_sma50_slope",
        "feature_sma200_slope", "feature_drawdown30", "feature_bb_position",
        "feature_bb_width",
    }


def test_annual_ai_training_uses_only_prior_year_matured_labels() -> None:
    n = 1800
    dates = pd.date_range("2015-01-01", periods=n, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    features = rules()["ai"]["features"]
    daily = pd.DataFrame({
        "signal_date": dates, "signal_available_at": dates + pd.Timedelta(days=1),
        "label_end_date": dates + pd.Timedelta(days=60),
        "bear_label": (np.arange(n) % 7 == 0).astype(float),
        "close": 100 + np.arange(n), "future_min_return_60d": -0.1,
        **{column: rng.normal(size=n) for column in features},
    })
    test_rules = copy.deepcopy(rules())
    test_rules["ai"]["hyperparameters"]["n_estimators"] = 2
    predictions, audit = annual_walk_forward_predictions(
        daily, test_rules, pd.Timestamp("2019-01-01", tz="UTC"), pd.Timestamp("2019-06-01", tz="UTC")
    )
    row = audit.iloc[0]
    assert row["prediction_year"] == 2019
    assert row["training_last_label_end_date"] <= row["training_cutoff"]
    assert row["cutoff_violation_count"] == 0
    assert predictions["bear_risk"].between(0, 1).all()


def test_models_replay_identical_fixed_dca_rows() -> None:
    timestamps = pd.date_range("2020-01-01", periods=30, freq="4h", tz="UTC")
    frame = pd.DataFrame({
        "open_time": timestamps, "signal_date": pd.NaT,
        "BTC_open": 10_000.0, "BTC_close": 10_010.0,
        "ETH_open": 200.0, "ETH_close": 201.0,
    })
    test_rules = rules()
    model_a = run_v31_backtest(frame, test_rules, scenario("A"))
    model_b = run_v31_backtest(frame, test_rules, scenario("B"), model_a=model_a)
    model_c = run_v31_backtest(frame, test_rules, scenario("C"), model_a=model_a)
    columns = ["timestamp", "asset", "quantity", "cash_change_usd"]
    expected = model_a.trades.loc[model_a.trades["action"].eq("NORMAL_DCA"), columns].reset_index(drop=True)
    for result in (model_b, model_c):
        actual = result.trades.loc[result.trades["action"].eq("NORMAL_DCA"), columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(actual, expected)
        assert result.history["theoretical_dca"].eq(2.0).all()
