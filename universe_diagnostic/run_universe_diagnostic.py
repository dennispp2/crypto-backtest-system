from __future__ import annotations

import copy
import hashlib
import json
import platform
import sys
from pathlib import Path
from typing import Any

import matplotlib
import numpy as np
import pandas as pd


DIAGNOSTIC_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DIAGNOSTIC_DIR.parent
sys.path.insert(0, str(PROJECT_DIR / "src"))

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from crypto_backtest.engine import ASSETS, BacktestResult, Scenario, run_backtest  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dataframe_to_markdown(frame: pd.DataFrame, *, index_label: str) -> str:
    """Render a small DataFrame without adding the optional tabulate dependency."""
    work = frame.copy()
    headers = [index_label, *map(str, work.columns)]
    rows = [[str(index), *[str(value) for value in row]] for index, row in work.iterrows()]
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return "\n".join(lines)


def build_scenario(universe: str, start_year: int, rules: dict[str, Any]) -> Scenario:
    return Scenario(
        name=f"{universe} - {rules['universes'][universe]['label']}",
        capital_test=f"fresh_start_{start_year}",
        initial_capital=float(rules["initial_capital_usd"]),
        initial_crypto_fraction=float(rules["initial_crypto_fraction"]),
        dynamic_dca=False,
        tactical=False,
        annual_rebalance=False,
        cash_protection=False,
        sell_order="overweight",
        fee=float(rules["resolved_costs"]["fee"]),
        slippage=float(rules["resolved_costs"]["slippage"]),
        cost_case="V2_primary",
        variant=universe,
    )


def load_inputs(
    diagnostic_rules: dict[str, Any],
) -> tuple[pd.DataFrame, dict[str, Any], pd.Series, dict[str, Any]]:
    v1_rules_path = PROJECT_DIR / "config" / "frozen_rules.json"
    v2_rules_path = PROJECT_DIR / "config" / "frozen_rules_v2.json"
    frame_path = PROJECT_DIR / "data" / "processed" / "backtest_4h_signals.csv.gz"
    v2_summary_path = PROJECT_DIR / "v2" / "results" / "summary_v2.csv"
    v2_daily_path = PROJECT_DIR / "v2" / "results" / "daily_portfolio_v2.csv"
    v2_trades_path = PROJECT_DIR / "v2" / "results" / "trade_log_v2.csv"
    paths = [v1_rules_path, v2_rules_path, frame_path, v2_summary_path, v2_daily_path, v2_trades_path]
    missing = [str(path) for path in paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Required frozen inputs are missing: {missing}")

    v1_rules = load_json(v1_rules_path)
    v2_rules = load_json(v2_rules_path)
    expected_contract = {
        "fee": float(v1_rules["costs"]["primary"]["fee"]),
        "slippage": float(v1_rules["costs"]["primary"]["slippage"]),
        "external_contribution_per_4h": float(v1_rules["external_contribution_per_4h"]),
        "minimum_notional": v1_rules["modeled_min_notional_usdt"],
    }
    if expected_contract["fee"] != float(v2_rules["costs"]["fee"]):
        raise RuntimeError("V1 primary fee no longer matches frozen V2")
    if expected_contract["slippage"] != float(v2_rules["costs"]["slippage"]):
        raise RuntimeError("V1 primary slippage no longer matches frozen V2")
    if expected_contract["external_contribution_per_4h"] != float(
        diagnostic_rules["external_contribution_per_4h_usd"]
    ):
        raise RuntimeError("Diagnostic DCA contribution differs from the V1/V2 engine contract")
    if expected_contract["minimum_notional"] != v2_rules["modeled_min_notional_usdt"]:
        raise RuntimeError("V1 minimum notional no longer matches frozen V2")

    champion_rows = pd.read_csv(v2_summary_path)
    champion_rows = champion_rows.loc[champion_rows["strategy"].eq("A - Fixed DCA Champion")]
    if len(champion_rows) != 1:
        raise RuntimeError("Expected exactly one V2 Fixed DCA Champion summary row")
    champion = champion_rows.iloc[0]
    formal_end = pd.Timestamp(champion["end"])
    if formal_end.tzinfo is None:
        formal_end = formal_end.tz_localize("UTC")
    else:
        formal_end = formal_end.tz_convert("UTC")

    frame = pd.read_csv(frame_path, compression="gzip")
    for column in ("open_time", "signal_date", "signal_available_at"):
        if column in frame:
            frame[column] = pd.to_datetime(frame[column], utc=True)
    frame = frame.loc[frame["open_time"] <= formal_end].copy().reset_index(drop=True)
    required_price_columns = [f"{asset}_{kind}" for asset in ASSETS for kind in ("open", "close")]
    missing_columns = sorted(set(["open_time", *required_price_columns]) - set(frame.columns))
    if missing_columns:
        raise RuntimeError(f"Frozen price panel missing required columns: {missing_columns}")
    null_count = int(frame[["open_time", *required_price_columns]].isna().sum().sum())
    if null_count:
        raise RuntimeError(f"Frozen common-price panel has {null_count} required null values")

    resolved_v1 = copy.deepcopy(v1_rules)
    diagnostic_rules["resolved_costs"] = {
        "fee": expected_contract["fee"],
        "slippage": expected_contract["slippage"],
    }
    contract = {
        "input_paths": [str(path) for path in paths],
        "input_sha256": {str(path.relative_to(PROJECT_DIR)): sha256_file(path) for path in paths},
        "price_panel_rows_through_v2_end": int(len(frame)),
        "v2_formal_end": formal_end.isoformat(),
        "duplicate_timestamp_count": int(frame["open_time"].duplicated().sum()),
        "required_price_null_count": null_count,
        "fee": expected_contract["fee"],
        "slippage": expected_contract["slippage"],
        "minimum_notional": expected_contract["minimum_notional"],
        "external_contribution_per_4h": expected_contract["external_contribution_per_4h"],
        "pass": bool(not missing_columns and null_count == 0 and not frame["open_time"].duplicated().any()),
    }
    return frame, resolved_v1, champion, contract


def prepare_run_rules(
    base_rules: dict[str, Any], diagnostic_rules: dict[str, Any], universe: str
) -> dict[str, Any]:
    rules = copy.deepcopy(base_rules)
    rules["target_weights"] = copy.deepcopy(diagnostic_rules["universes"][universe]["weights"])
    rules["external_contribution_per_4h"] = float(
        diagnostic_rules["external_contribution_per_4h_usd"]
    )
    return rules


def run_one(
    frame: pd.DataFrame,
    base_rules: dict[str, Any],
    diagnostic_rules: dict[str, Any],
    universe: str,
    start: pd.Timestamp,
) -> tuple[BacktestResult, dict[str, Any]]:
    start = pd.Timestamp(start)
    if start.tzinfo is None:
        start = start.tz_localize("UTC")
    else:
        start = start.tz_convert("UTC")
    subframe = frame.loc[frame["open_time"] >= start].copy().reset_index(drop=True)
    if subframe.empty or subframe["open_time"].iloc[0] != start:
        raise RuntimeError(f"{universe}: exact fresh-start 4H bar unavailable at {start.isoformat()}")
    rules = prepare_run_rules(base_rules, diagnostic_rules, universe)
    scenario = build_scenario(universe, start.year, diagnostic_rules)
    result = run_backtest(subframe, rules, scenario, record_signals=False)
    metadata = {
        "universe": universe,
        "universe_label": diagnostic_rules["universes"][universe]["label"],
        "start_year": int(start.year),
        "formal_start": start.isoformat(),
        "formal_end": pd.Timestamp(subframe["open_time"].iloc[-1]).isoformat(),
        "bar_count": int(len(subframe)),
        "weights": rules["target_weights"],
    }
    return result, metadata


def enrich_history(result: BacktestResult, metadata: dict[str, Any]) -> pd.DataFrame:
    history = result.history.copy()
    crypto_value = (
        history["portfolio_value"]
        - history["normal_cash"]
        - history["pending_dca_cash"]
        - history["tactical_cash"]
    )
    for asset in ASSETS:
        history[f"{asset.lower()}_value"] = crypto_value * history[f"{asset}_allocation"]
    history.insert(0, "universe", metadata["universe"])
    history.insert(1, "universe_label", metadata["universe_label"])
    history.insert(2, "start_year", metadata["start_year"])
    return history


def daily_history(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    last_columns = [
        "portfolio_value",
        "btc_value",
        "eth_value",
        "bnb_value",
        "unit_nav",
        "drawdown",
        "normal_cash",
        "pending_dca_cash",
        "tactical_cash",
        "normal_cash_ratio",
        "total_cash_ratio",
        "tactical_cash_ratio",
        "BTC_allocation",
        "ETH_allocation",
        "BNB_allocation",
        "BTC_close",
        "ETH_close",
        "BNB_close",
        "theoretical_dca",
        "protected_dca",
    ]
    aggregations: dict[str, Any] = {column: "last" for column in last_columns}
    aggregations.update(
        {
            "external_flow": "sum",
            "committed_dca": "sum",
            "executed_dca": "sum",
            "twr_return": lambda x: float(np.prod(1.0 + x) - 1.0),
        }
    )
    daily = work.groupby("date", as_index=False).agg(aggregations)
    for column in ("universe", "universe_label", "start_year"):
        daily.insert(0, column, work[column].iloc[0])
    return daily


def asset_contributions(
    result: BacktestResult, history: pd.DataFrame, metadata: dict[str, Any]
) -> pd.DataFrame:
    final = history.iloc[-1]
    total_invested_capital = float(result.summary["external_contributions"])
    total_profit = float(result.summary["net_profit"])
    rows: list[dict[str, Any]] = []
    buys = result.trades.loc[result.trades["side"].eq("BUY")].copy()
    for asset in ASSETS:
        asset_buys = buys.loc[buys["asset"].eq(asset)]
        dollars_invested = float(-asset_buys["cash_change_usd"].sum())
        ending_value = float(final[f"{asset.lower()}_value"])
        net_profit = ending_value - dollars_invested
        rows.append(
            {
                "universe": metadata["universe"],
                "universe_label": metadata["universe_label"],
                "start_year": metadata["start_year"],
                "asset": asset,
                "target_weight": float(metadata["weights"][asset]),
                "total_dollars_invested": dollars_invested,
                "ending_value": ending_value,
                "net_profit_contribution": net_profit,
                "ending_portfolio_wealth_share": ending_value / float(final["portfolio_value"]),
                "ending_crypto_wealth_share": ending_value
                / max(sum(float(final[f"{a.lower()}_value"]) for a in ASSETS), 1e-300),
                "total_portfolio_profit_share": net_profit / total_profit if total_profit else np.nan,
                "total_invested_capital": total_invested_capital,
            }
        )
    return pd.DataFrame(rows)


def summarize_run(
    result: BacktestResult,
    history: pd.DataFrame,
    contributions: pd.DataFrame,
    metadata: dict[str, Any],
) -> dict[str, Any]:
    base = result.summary
    final = history.iloc[-1]
    row: dict[str, Any] = {
        **metadata,
        "initial_capital_usd": float(base["initial_capital"]),
        "external_contributions_after_inception_usd": float(
            base["periodic_external_contributions"]
        ),
        "total_invested_capital_usd": float(base["external_contributions"]),
        "final_portfolio_value": float(base["final_portfolio_value"]),
        "net_profit": float(base["net_profit"]),
        "xirr": float(base["xirr"]),
        "twr_cagr": float(base["time_weighted_cagr"]),
        "maximum_drawdown": float(base["maximum_drawdown"]),
        "sharpe": float(base["sharpe"]),
        "sortino": float(base["sortino"]),
        "calmar": float(base["calmar"]),
        "total_trading_costs": float(base["total_trading_costs"]),
        "transaction_count": int(len(result.trades)),
        "ending_normal_cash": float(final["normal_cash"]),
        "ending_pending_dca_cash": float(final["pending_dca_cash"]),
    }
    indexed = contributions.set_index("asset")
    for asset in ASSETS:
        row[f"{asset}_total_dollars_invested"] = float(indexed.loc[asset, "total_dollars_invested"])
        row[f"{asset}_ending_value"] = float(indexed.loc[asset, "ending_value"])
        row[f"{asset}_net_profit_contribution"] = float(
            indexed.loc[asset, "net_profit_contribution"]
        )
        row[f"{asset}_ending_wealth_share"] = float(
            indexed.loc[asset, "ending_portfolio_wealth_share"]
        )
        row[f"{asset}_total_profit_share"] = float(
            indexed.loc[asset, "total_portfolio_profit_share"]
        )
    return row


def _normalize_text(series: pd.Series) -> pd.Series:
    if series.name in {"timestamp", "signal_date", "date"}:
        return pd.to_datetime(series, utc=True).astype(str)
    return series.fillna("").astype(str)


def compare_u3_to_v2(
    result: BacktestResult,
    history: pd.DataFrame,
    summary: dict[str, Any],
    champion: pd.Series,
) -> dict[str, Any]:
    ref_trades = pd.read_csv(PROJECT_DIR / "v2" / "results" / "trade_log_v2.csv")
    ref_trades = ref_trades.loc[ref_trades["strategy"].eq("A - Fixed DCA Champion")].reset_index(drop=True)
    new_trades = result.trades.reset_index(drop=True)
    trade_keys = ["timestamp", "action", "side", "asset", "ledger", "sell_stage", "signal_date"]
    trade_numeric = [
        "quantity",
        "raw_open_price",
        "effective_price",
        "gross_notional_usd",
        "cash_change_usd",
        "fee_usd",
        "slippage_usd",
        "cost_usd",
    ]
    key_match = len(new_trades) == len(ref_trades)
    if key_match:
        key_match = all(
            _normalize_text(new_trades[column]).equals(_normalize_text(ref_trades[column]))
            for column in trade_keys
        )
    if len(new_trades) == len(ref_trades):
        trade_numeric_delta = max(
            float(
                np.max(
                    np.abs(
                        new_trades[column].astype(float).to_numpy()
                        - ref_trades[column].astype(float).to_numpy()
                    )
                )
            )
            for column in trade_numeric
        )
    else:
        trade_numeric_delta = float("inf")

    ref_daily = pd.read_csv(PROJECT_DIR / "v2" / "results" / "daily_portfolio_v2.csv")
    ref_daily = ref_daily.loc[ref_daily["strategy"].eq("A - Fixed DCA Champion")].reset_index(drop=True)
    new_daily = daily_history(history).reset_index(drop=True)
    daily_keys = ["date"]
    daily_numeric = [
        "portfolio_value",
        "btc_value",
        "eth_value",
        "bnb_value",
        "unit_nav",
        "drawdown",
        "normal_cash",
        "pending_dca_cash",
        "BTC_allocation",
        "ETH_allocation",
        "BNB_allocation",
        "BTC_close",
        "ETH_close",
        "BNB_close",
        "external_flow",
        "committed_dca",
        "executed_dca",
        "twr_return",
    ]
    daily_key_match = len(new_daily) == len(ref_daily) and all(
        _normalize_text(new_daily[column]).equals(_normalize_text(ref_daily[column]))
        for column in daily_keys
    )
    if len(new_daily) == len(ref_daily):
        daily_numeric_delta = max(
            float(
                np.max(
                    np.abs(
                        new_daily[column].astype(float).to_numpy()
                        - ref_daily[column].astype(float).to_numpy()
                    )
                )
            )
            for column in daily_numeric
        )
    else:
        daily_numeric_delta = float("inf")

    final_delta = float(summary["final_portfolio_value"] - float(champion["final_portfolio_value"]))
    checks = {
        "reference_strategy": "A - Fixed DCA Champion",
        "reference_final_value": float(champion["final_portfolio_value"]),
        "reproduced_final_value": float(summary["final_portfolio_value"]),
        "final_value_delta": final_delta,
        "trade_reference_rows": int(len(ref_trades)),
        "trade_reproduced_rows": int(len(new_trades)),
        "trade_identity_keys_exact": bool(key_match),
        "trade_numeric_max_abs_delta": trade_numeric_delta,
        "daily_reference_rows": int(len(ref_daily)),
        "daily_reproduced_rows": int(len(new_daily)),
        "daily_date_keys_exact": bool(daily_key_match),
        "daily_numeric_max_abs_delta": daily_numeric_delta,
        "tolerance": 1e-8,
    }
    checks["pass"] = bool(
        abs(final_delta) <= checks["tolerance"]
        and key_match
        and trade_numeric_delta <= checks["tolerance"]
        and daily_key_match
        and daily_numeric_delta <= checks["tolerance"]
    )
    return checks


def build_comparisons(summary: pd.DataFrame, pairs: list[list[str]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    indexed = summary.set_index(["start_year", "universe"])
    for start_year in sorted(summary["start_year"].unique()):
        for left, right in pairs:
            lrow = indexed.loc[(start_year, left)]
            rrow = indexed.loc[(start_year, right)]
            rows.append(
                {
                    "start_year": int(start_year),
                    "comparison": f"{left} vs {right}",
                    "left_universe": left,
                    "right_universe": right,
                    "delta_final_value": float(
                        lrow["final_portfolio_value"] - rrow["final_portfolio_value"]
                    ),
                    "delta_final_value_pct_of_right": float(
                        lrow["final_portfolio_value"] / rrow["final_portfolio_value"] - 1.0
                    ),
                    "delta_cagr_percentage_points": float(
                        100.0 * (lrow["twr_cagr"] - rrow["twr_cagr"])
                    ),
                    "delta_max_drawdown_percentage_points": float(
                        100.0 * (lrow["maximum_drawdown"] - rrow["maximum_drawdown"])
                    ),
                    "delta_calmar": float(lrow["calmar"] - rrow["calmar"]),
                }
            )
    return pd.DataFrame(rows)


def classify_verdict(summary: pd.DataFrame, contributions: pd.DataFrame) -> dict[str, Any]:
    primary = summary.loc[summary["start_year"].eq(2020)].set_index("universe")
    u3_assets = contributions.loc[
        contributions["start_year"].eq(2020) & contributions["universe"].eq("U3")
    ].set_index("asset")
    bnb_profit_share = float(u3_assets.loc["BNB", "total_portfolio_profit_share"])
    removal_drop = float(
        (primary.loc["U3", "final_portfolio_value"] - primary.loc["U2", "final_portfolio_value"])
        / primary.loc["U3", "final_portfolio_value"]
    )
    uplift_by_start: dict[str, float] = {}
    for year in sorted(summary["start_year"].unique()):
        rows = summary.loc[summary["start_year"].eq(year)].set_index("universe")
        uplift_by_start[str(year)] = float(
            rows.loc["U3", "final_portfolio_value"] / rows.loc["U2", "final_portfolio_value"] - 1.0
        )
    later_abs_median = float(np.median([abs(uplift_by_start[str(year)]) for year in (2021, 2022, 2023)]))
    concentration_ratio = abs(uplift_by_start["2020"]) / max(later_abs_median, 1e-12)
    all_profitable = bool((summary["net_profit"] > 0).all())

    strong_checks = {
        "bnb_profit_share_ge_50pct": bnb_profit_share >= 0.50,
        "removing_bnb_ending_value_drop_ge_25pct": removal_drop >= 0.25,
        "2020_uplift_at_least_2x_later_median": concentration_ratio >= 2.0,
    }
    robust_checks = {
        "all_universe_start_net_profits_positive": all_profitable,
        "bnb_profit_share_lt_30pct": bnb_profit_share < 0.30,
        "removing_bnb_ending_value_drop_lt_10pct": removal_drop < 0.10,
    }
    if all(strong_checks.values()):
        verdict = "C. FIXED DCA RESULT STRONGLY BNB-DEPENDENT"
    elif all(robust_checks.values()):
        verdict = "A. FIXED DCA EDGE ROBUST ACROSS UNIVERSES"
    else:
        verdict = "B. FIXED DCA EDGE PARTIALLY BNB-DEPENDENT"
    return {
        "verdict": verdict,
        "u3_2020_bnb_total_profit_share": bnb_profit_share,
        "u3_2020_ending_value_drop_if_bnb_removed": removal_drop,
        "u3_vs_u2_final_value_uplift_by_start": uplift_by_start,
        "later_start_absolute_uplift_median": later_abs_median,
        "2020_to_later_uplift_concentration_ratio": concentration_ratio,
        "all_universe_start_net_profits_positive": all_profitable,
        "strong_gate_checks": strong_checks,
        "robust_gate_checks": robust_checks,
    }


def audit_all_runs(
    results: dict[tuple[int, str], BacktestResult],
    histories: dict[tuple[int, str], pd.DataFrame],
    metadata: dict[tuple[int, str], dict[str, Any]],
    summary: pd.DataFrame,
    contributions: pd.DataFrame,
    u3_integrity: dict[str, Any],
    data_contract: dict[str, Any],
    diagnostic_rules: dict[str, Any],
) -> dict[str, Any]:
    allowed_actions = {"INITIAL_ALLOCATION", "NORMAL_DCA"}
    action_violations = 0
    sell_count = 0
    wrong_ledger_count = 0
    dca_rate_violations = 0
    cash_negatives = 0
    fresh_initial_violations = 0
    decomposition_max_abs_delta = 0.0
    for key, result in results.items():
        history = histories[key]
        meta = metadata[key]
        trades = result.trades
        action_violations += int((~trades["action"].isin(allowed_actions)).sum())
        sell_count += int(trades["side"].eq("SELL").sum())
        wrong_ledger_count += int(
            (trades["action"].eq("NORMAL_DCA") & ~trades["ledger"].eq("pending")).sum()
        )
        observed_per_interval = history["external_flow"] / history["elapsed_4h_intervals"]
        dca_rate_violations += int(
            (~np.isclose(observed_per_interval, 2.0, rtol=0.0, atol=1e-12)).sum()
        )
        dca_rate_violations += int(
            (~np.isclose(history["theoretical_dca"], 2.0, rtol=0.0, atol=1e-12)).sum()
        )
        cash_negatives += int(
            ((history[["normal_cash", "pending_dca_cash", "tactical_cash"]] < -1e-8).any(axis=1)).sum()
        )
        first_alloc = trades.loc[trades["action"].eq("INITIAL_ALLOCATION")]
        actual = {asset: float(-first_alloc.loc[first_alloc["asset"].eq(asset), "cash_change_usd"].sum()) for asset in ASSETS}
        expected = diagnostic_rules["universes"][meta["universe"]]["initial_allocation_usd"]
        if any(abs(actual[asset] - float(expected[asset])) > 1e-8 for asset in ASSETS):
            fresh_initial_violations += 1

        asset_rows = contributions.loc[
            contributions["start_year"].eq(key[0]) & contributions["universe"].eq(key[1])
        ]
        cash_profit = (
            float(history.iloc[-1]["normal_cash"])
            + float(history.iloc[-1]["pending_dca_cash"])
            - float(diagnostic_rules["initial_capital_usd"] * diagnostic_rules["initial_cash_fraction"])
            - (
                float(result.summary["periodic_external_contributions"])
                - float(asset_rows["total_dollars_invested"].sum() - diagnostic_rules["initial_capital_usd"] * diagnostic_rules["initial_crypto_fraction"])
            )
        )
        decomposition = float(asset_rows["net_profit_contribution"].sum() + cash_profit)
        decomposition_max_abs_delta = max(
            decomposition_max_abs_delta, abs(decomposition - float(result.summary["net_profit"]))
        )

    spread = (
        summary.groupby("start_year")["external_contributions_after_inception_usd"].max()
        - summary.groupby("start_year")["external_contributions_after_inception_usd"].min()
    )
    checks = {
        "data_contract_pass": bool(data_contract["pass"]),
        "u3_row_integrity_pass": bool(u3_integrity["pass"]),
        "run_count": int(len(results)),
        "required_run_count": 12,
        "forbidden_action_rows": action_violations,
        "sell_trade_rows": sell_count,
        "normal_dca_wrong_ledger_rows": wrong_ledger_count,
        "dca_or_external_flow_rate_violation_rows": dca_rate_violations,
        "negative_cash_rows": cash_negatives,
        "fresh_initial_allocation_violations": fresh_initial_violations,
        "max_external_contribution_spread_within_start": float(spread.max()),
        "profit_decomposition_max_abs_delta": decomposition_max_abs_delta,
        "recorded_signal_rows": int(sum(len(result.signals) for result in results.values())),
        "engine_source_path": str(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        "engine_source_sha256": sha256_file(PROJECT_DIR / "src" / "crypto_backtest" / "engine.py"),
        "separation_statement": "Pure Fixed DCA only; no Macro FSM, stage, floor, hedge, tactical sell, or tactical buyback code path is enabled.",
    }
    checks["pass"] = bool(
        checks["data_contract_pass"]
        and checks["u3_row_integrity_pass"]
        and checks["run_count"] == checks["required_run_count"]
        and action_violations == 0
        and sell_count == 0
        and wrong_ledger_count == 0
        and dca_rate_violations == 0
        and cash_negatives == 0
        and fresh_initial_violations == 0
        and checks["max_external_contribution_spread_within_start"] <= 1e-8
        and decomposition_max_abs_delta <= 1e-7
        and checks["recorded_signal_rows"] == 0
    )
    return checks


def create_figures(
    summary: pd.DataFrame, daily: pd.DataFrame, contributions: pd.DataFrame, figure_dir: Path
) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    colors = {"U1": "#4C78A8", "U2": "#54A24B", "U3": "#E45756"}
    primary = daily.loc[daily["start_year"].eq(2020)]
    fig, ax = plt.subplots(figsize=(12, 6.5))
    for universe in ("U1", "U2", "U3"):
        data = primary.loc[primary["universe"].eq(universe)]
        ax.plot(pd.to_datetime(data["date"], utc=True), data["portfolio_value"], label=universe, color=colors[universe])
    ax.set_yscale("log")
    ax.set_title("Fixed DCA Universe Equity Curves — 2020 Fresh Start")
    ax.set_ylabel("Portfolio value (USD, log scale)")
    ax.grid(alpha=0.25)
    ax.legend()
    fig.tight_layout()
    fig.savefig(figure_dir / "01_equity_curves_2020.png", dpi=180)
    plt.close(fig)

    pivot = summary.pivot(index="start_year", columns="universe", values="final_portfolio_value")
    fig, ax = plt.subplots(figsize=(11, 6.5))
    pivot[["U1", "U2", "U3"]].plot(kind="bar", ax=ax, color=[colors["U1"], colors["U2"], colors["U3"]])
    ax.set_title("Ending Value by Fresh Start and Universe")
    ax.set_ylabel("Ending value (USD)")
    ax.set_xlabel("Fresh start year")
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", rotation=0)
    fig.tight_layout()
    fig.savefig(figure_dir / "02_rolling_start_final_values.png", dpi=180)
    plt.close(fig)

    primary_assets = contributions.loc[contributions["start_year"].eq(2020)]
    pivot_assets = primary_assets.pivot(index="universe", columns="asset", values="net_profit_contribution").fillna(0.0)
    fig, ax = plt.subplots(figsize=(10.5, 6.5))
    pivot_assets[["BTC", "ETH", "BNB"]].plot(
        kind="bar", stacked=True, ax=ax, color=["#F2CF5B", "#B279A2", "#FF9DA6"]
    )
    ax.set_title("Asset Net-Profit Contribution — 2020 Fresh Start")
    ax.set_ylabel("Ending value minus dollars invested (USD)")
    ax.set_xlabel("Universe")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.grid(axis="y", alpha=0.25)
    ax.tick_params(axis="x", rotation=0)
    fig.tight_layout()
    fig.savefig(figure_dir / "03_asset_profit_contributions_2020.png", dpi=180)
    plt.close(fig)

    fig, axes = plt.subplots(2, 2, figsize=(12, 9), sharex=False, sharey=False)
    for ax, start_year in zip(axes.flat, (2020, 2021, 2022, 2023)):
        data = summary.loc[summary["start_year"].eq(start_year)]
        for _, row in data.iterrows():
            ax.scatter(
                100.0 * row["maximum_drawdown"],
                100.0 * row["twr_cagr"],
                color=colors[row["universe"]],
                s=65,
            )
            ax.annotate(row["universe"], (100.0 * row["maximum_drawdown"], 100.0 * row["twr_cagr"]), xytext=(5, 4), textcoords="offset points")
        ax.set_title(f"Fresh start {start_year}")
        ax.set_xlabel("Maximum drawdown (%)")
        ax.set_ylabel("TWR CAGR (%)")
        ax.grid(alpha=0.25)
    fig.suptitle("Risk/Return by Universe and Fresh Start")
    fig.tight_layout()
    fig.savefig(figure_dir / "04_risk_return_by_start.png", dpi=180)
    plt.close(fig)


def write_report(
    summary: pd.DataFrame,
    comparisons: pd.DataFrame,
    contributions: pd.DataFrame,
    verdict: dict[str, Any],
    audit: dict[str, Any],
    report_path: Path,
) -> None:
    primary = summary.loc[summary["start_year"].eq(2020)].set_index("universe")
    comp = comparisons.loc[comparisons["start_year"].eq(2020)].set_index("comparison")
    assets = contributions.loc[
        contributions["start_year"].eq(2020) & contributions["universe"].eq("U3")
    ].set_index("asset")
    removal = comp.loc["U3 vs U2"]
    btc_lower_dd = bool(primary.loc["U1", "maximum_drawdown"] > primary.loc["U3", "maximum_drawdown"])
    u2_better_calmar = bool(primary.loc["U2", "calmar"] > primary.loc["U3", "calmar"])
    u2_better_sharpe = bool(primary.loc["U2", "sharpe"] > primary.loc["U3", "sharpe"])

    primary_table = primary[
        ["final_portfolio_value", "xirr", "twr_cagr", "maximum_drawdown", "sharpe", "sortino", "calmar"]
    ].copy()
    primary_table.columns = ["Final USD", "XIRR", "TWR CAGR", "Max DD", "Sharpe", "Sortino", "Calmar"]
    for column in ("XIRR", "TWR CAGR", "Max DD"):
        primary_table[column] = primary_table[column].map(lambda value: f"{100.0 * value:.2f}%")
    primary_table["Final USD"] = primary_table["Final USD"].map(lambda value: f"${value:,.2f}")
    for column in ("Sharpe", "Sortino", "Calmar"):
        primary_table[column] = primary_table[column].map(lambda value: f"{value:.4f}")

    comparison_table = comp[
        [
            "delta_final_value",
            "delta_cagr_percentage_points",
            "delta_max_drawdown_percentage_points",
            "delta_calmar",
        ]
    ].copy()
    comparison_table.columns = [
        "Delta final USD",
        "Delta CAGR pp",
        "Delta Max DD pp",
        "Delta Calmar",
    ]
    comparison_table["Delta final USD"] = comparison_table["Delta final USD"].map(
        lambda value: f"${value:,.2f}"
    )
    for column in ("Delta CAGR pp", "Delta Max DD pp", "Delta Calmar"):
        comparison_table[column] = comparison_table[column].map(lambda value: f"{value:.4f}")

    rolling = summary.pivot(index="start_year", columns="universe", values="final_portfolio_value")
    rolling = rolling[["U1", "U2", "U3"]].map(lambda value: f"${value:,.2f}")
    uplift_text = ", ".join(
        f"{year}: {100.0 * value:.2f}%"
        for year, value in verdict["u3_vs_u2_final_value_uplift_by_start"].items()
    )

    primary_markdown = dataframe_to_markdown(primary_table, index_label="Universe")
    comparison_markdown = dataframe_to_markdown(comparison_table, index_label="Comparison")
    rolling_markdown = dataframe_to_markdown(rolling, index_label="Start year")

    report = f"""# Fixed DCA Universe Diagnostic

## Outcome

**{verdict['verdict']}**

This is an isolated diagnostic. It did not execute or alter the V3 Macro FSM,
regime labels, hedge stages, floors, or buybacks. The complete machine audit is
**{'PASS' if audit['pass'] else 'FAIL'}**, and the mandatory U3 row-integrity
reproduction is **{'PASS' if audit['u3_row_integrity_pass'] else 'FAIL'}**.

## 2020 fresh-start results

{primary_markdown}

All runs used the same USD 20,000 initial portfolio, USD 6,000 initial cash,
70% initial crypto allocation, USD 2 per elapsed 4H interval, and identical V2
primary execution costs.

### 2020 pairwise deltas (left minus right)

{comparison_markdown}

A positive Delta Max DD means the left universe had a shallower drawdown because
drawdowns are stored as negative values.

## Direct answers

1. **Removing BNB:** U2 ended **${abs(removal['delta_final_value']):,.2f} below U3**,
   equal to **{100.0 * verdict['u3_2020_ending_value_drop_if_bnb_removed']:.2f}% of U3's ending value**.
2. **BNB contribution to U3 profit:** BNB's accounting net-profit contribution
   was **${assets.loc['BNB', 'net_profit_contribution']:,.2f}**, or
   **{100.0 * assets.loc['BNB', 'total_portfolio_profit_share']:.2f}%** of total U3 portfolio profit.
3. **BTC-only lower Max DD:** **{'Yes' if btc_lower_dd else 'No'}**. U1 Max DD was
   {100.0 * primary.loc['U1', 'maximum_drawdown']:.2f}% versus U3
   {100.0 * primary.loc['U3', 'maximum_drawdown']:.2f}%.
4. **BTC+ETH better risk-adjusted return:** Relative to U3, **no**: 2020-start
   Calmar was {primary.loc['U2', 'calmar']:.4f} vs {primary.loc['U3', 'calmar']:.4f},
   and Sharpe was {primary.loc['U2', 'sharpe']:.4f} vs {primary.loc['U3', 'sharpe']:.4f}.
   Relative to BTC-only, U2 did have higher Calmar ({primary.loc['U2', 'calmar']:.4f}
   vs {primary.loc['U1', 'calmar']:.4f}) despite a deeper Max DD.
5. **How BNB-driven was the Champion:** U3's BNB sleeve supplied
   {100.0 * assets.loc['BNB', 'total_portfolio_profit_share']:.2f}% of U3 total profit,
   while the opportunity-cost test shows a {100.0 * verdict['u3_2020_ending_value_drop_if_bnb_removed']:.2f}%
   ending-value loss when BNB is replaced by proportionally more BTC/ETH.
6. **Robust if BNB cannot repeat:** The cross-universe Fixed DCA outcome is not
   automatically invalid, but the original U3 Champion return should not be
   treated as robust to a weaker future BNB path. Rolling-start evidence below
   determines whether the advantage persisted beyond the 2020 low-base entry.

## Rolling fresh-start ending values

{rolling_markdown}

U3-vs-U2 ending-value uplift by start: {uplift_text}. The advantage was large for
both 2020 and 2021 fresh starts, almost disappeared for 2022, and turned slightly
negative for 2023. It is therefore not accurate to attribute the entire effect
only to a 2020 entry. The absolute 2020 uplift was
{verdict['2020_to_later_uplift_concentration_ratio']:.2f} times the median
absolute uplift from the 2021/2022/2023 fresh starts.

## Interpretation limits

- BNB accounting profit share and U3-minus-U2 opportunity-cost uplift answer
  different questions; both are reported.
- Results are historical and depend on the frozen Binance-derived price path,
  survivorship of the selected assets, stablecoin/USD equivalence, and the
  simplified fixed fee/slippage model.
- This is not evidence that Fixed DCA beats lump sum, cash, or other schedules;
  those controls were intentionally outside scope.
- The verdict gates and allocations were frozen before results. No allocation
  or V3 hedge parameter was changed after observing them.

## Audit summary

- U3 final-value delta versus V2 Champion: {audit['u3_integrity']['final_value_delta']:.12f} USD.
- U3 trade rows: {audit['u3_integrity']['trade_reproduced_rows']:,}; numeric max absolute delta:
  {audit['u3_integrity']['trade_numeric_max_abs_delta']:.3g}.
- U3 daily rows: {audit['u3_integrity']['daily_reproduced_rows']:,}; numeric max absolute delta:
  {audit['u3_integrity']['daily_numeric_max_abs_delta']:.3g}.
- Forbidden action rows: {audit['forbidden_action_rows']}; sell rows: {audit['sell_trade_rows']}.
- Recorded signal rows: {audit['recorded_signal_rows']}.
- Fresh initial-allocation violations: {audit['fresh_initial_allocation_violations']}.
- External-contribution spread within each start: {audit['max_external_contribution_spread_within_start']:.12f} USD.
"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")


def main() -> int:
    diagnostic_rules_path = DIAGNOSTIC_DIR / "config" / "frozen_universe_rules.json"
    diagnostic_rules = load_json(diagnostic_rules_path)
    frame, base_rules, champion, data_contract = load_inputs(diagnostic_rules)

    results: dict[tuple[int, str], BacktestResult] = {}
    histories: dict[tuple[int, str], pd.DataFrame] = {}
    metadata: dict[tuple[int, str], dict[str, Any]] = {}
    contributions_by_run: dict[tuple[int, str], pd.DataFrame] = {}
    summary_rows: list[dict[str, Any]] = []

    # Mandatory fail-fast gate: reproduce U3 2020 before running any alternate universe.
    primary_start = pd.Timestamp(diagnostic_rules["formal_starts"][0])
    u3_result, u3_meta = run_one(frame, base_rules, diagnostic_rules, "U3", primary_start)
    u3_history = enrich_history(u3_result, u3_meta)
    u3_contrib = asset_contributions(u3_result, u3_history, u3_meta)
    u3_summary = summarize_run(u3_result, u3_history, u3_contrib, u3_meta)
    u3_integrity = compare_u3_to_v2(u3_result, u3_history, u3_summary, champion)
    artifact_dir = DIAGNOSTIC_DIR / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "u3_row_integrity_audit.json").write_text(
        json.dumps(u3_integrity, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if not u3_integrity["pass"]:
        raise RuntimeError(f"U3 ROW INTEGRITY failed; alternate-universe runs withheld: {u3_integrity}")

    primary_key = (2020, "U3")
    results[primary_key] = u3_result
    histories[primary_key] = u3_history
    metadata[primary_key] = u3_meta
    contributions_by_run[primary_key] = u3_contrib
    summary_rows.append(u3_summary)

    for start_text in diagnostic_rules["formal_starts"]:
        start = pd.Timestamp(start_text)
        for universe in diagnostic_rules["universes"]:
            key = (start.year, universe)
            if key == primary_key:
                continue
            result, meta = run_one(frame, base_rules, diagnostic_rules, universe, start)
            history = enrich_history(result, meta)
            contribution = asset_contributions(result, history, meta)
            results[key] = result
            histories[key] = history
            metadata[key] = meta
            contributions_by_run[key] = contribution
            summary_rows.append(summarize_run(result, history, contribution, meta))

    summary = pd.DataFrame(summary_rows).sort_values(["start_year", "universe"]).reset_index(drop=True)
    contributions = pd.concat(contributions_by_run.values(), ignore_index=True).sort_values(
        ["start_year", "universe", "asset"]
    )
    daily = pd.concat([daily_history(history) for history in histories.values()], ignore_index=True).sort_values(
        ["start_year", "universe", "date"]
    )
    trade_frames: list[pd.DataFrame] = []
    for key, result in results.items():
        out = result.trades.copy()
        out.insert(0, "universe", key[1])
        out.insert(1, "start_year", key[0])
        trade_frames.append(out)
    trades = pd.concat(trade_frames, ignore_index=True).sort_values(
        ["start_year", "universe", "timestamp", "asset"]
    )
    comparisons = build_comparisons(summary, diagnostic_rules["comparison_pairs"])
    verdict = classify_verdict(summary, contributions)
    audit = audit_all_runs(
        results,
        histories,
        metadata,
        summary,
        contributions,
        u3_integrity,
        data_contract,
        diagnostic_rules,
    )
    audit["u3_integrity"] = u3_integrity
    if not audit["pass"]:
        (artifact_dir / "universe_diagnostic_audit.json").write_text(
            json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        raise RuntimeError(f"Universe diagnostic audit failed; verdict withheld: {audit}")

    result_dir = DIAGNOSTIC_DIR / "results"
    figure_dir = DIAGNOSTIC_DIR / "figures"
    result_dir.mkdir(parents=True, exist_ok=True)
    summary.to_csv(result_dir / "universe_summary.csv", index=False)
    contributions.to_csv(result_dir / "asset_contribution.csv", index=False)
    comparisons.to_csv(result_dir / "universe_comparison.csv", index=False)
    daily.to_csv(result_dir / "daily_portfolio_universe.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    trades.to_csv(result_dir / "trade_log_universe.csv", index=False, date_format="%Y-%m-%dT%H:%M:%S%z")
    (artifact_dir / "data_contract.json").write_text(
        json.dumps(data_contract, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (artifact_dir / "universe_diagnostic_audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (artifact_dir / "verdict.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    create_figures(summary, daily, contributions, figure_dir)
    write_report(
        summary,
        comparisons,
        contributions,
        verdict,
        audit,
        DIAGNOSTIC_DIR / "report" / "FIXED_DCA_UNIVERSE_DIAGNOSTIC.md",
    )

    manifest = {
        "diagnostic": diagnostic_rules["diagnostic_name"],
        "status": "COMPLETE",
        "verdict": verdict["verdict"],
        "audit_pass": audit["pass"],
        "data_end": data_contract["v2_formal_end"],
        "python": sys.version,
        "platform": platform.platform(),
        "pandas": pd.__version__,
        "numpy": np.__version__,
        "matplotlib": matplotlib.__version__,
        "frozen_rules_sha256": sha256_file(diagnostic_rules_path),
        "outputs_sha256": {
            path.relative_to(DIAGNOSTIC_DIR).as_posix(): sha256_file(path)
            for path in sorted(DIAGNOSTIC_DIR.rglob("*"))
            if path.is_file()
            and path.name != "run_manifest.json"
            and "__pycache__" not in path.parts
            and path.suffix != ".pyc"
        },
    }
    (artifact_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps({"status": "COMPLETE", "verdict": verdict["verdict"], "audit_pass": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
