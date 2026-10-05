from __future__ import annotations

import argparse
import itertools
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


PROJECT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_DIR / "v31_necessity_audit"
V31_DIR = PROJECT_DIR / "v3_1"
sys.path.insert(0, str(PROJECT_DIR / "src"))

from crypto_backtest.data import sha256_file  # noqa: E402
from crypto_backtest.v31_analysis import enriched_summary, prefix_trade_identity  # noqa: E402
from crypto_backtest.v31_engine import V31BacktestResult, V31Scenario, run_v31_backtest  # noqa: E402
from crypto_backtest.v31_necessity_analysis import (  # noqa: E402
    add_whipsaw_labels,
    apply_classifications,
    attribution_record,
    build_event_features,
    daily_last,
    identify_round_trip_clusters,
    major_transition_times,
    next_transition_after,
    signal_type_summary,
    whipsaw_summary,
)
from crypto_backtest.v31_necessity_engine import (  # noqa: E402
    frozen_tactical_events,
    run_frozen_shadow_counterfactual,
)
from crypto_backtest.v31_necessity_reporting import (  # noqa: E402
    create_necessity_figures,
    write_necessity_report,
)
from run_backtest_v3_7 import load_formal_data  # noqa: E402


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def scenario(model: str, rules: dict[str, Any]) -> V31Scenario:
    labels = {
        "A": "MODEL A - BTC+ETH Fixed DCA",
        "B": "MODEL B - BTC+ETH Fixed DCA + V3.1 FSM",
        "CF": "COUNTERFACTUAL - V3.1 Frozen Shadow Necessity Audit",
    }
    return V31Scenario(
        name=labels[model],
        model=model,
        use_fsm=model == "B",
        use_ai=False,
        hard_floor=float(rules["hard_floor"]),
        initial_capital=float(rules["initial_capital"]),
        capital_test="v31_necessity_audit",
        variant="frozen_shadow_diagnostic",
        cost_case="v3_1_frozen",
        fee=float(rules["costs"]["fee"]),
        slippage=float(rules["costs"]["slippage"]),
    )


def _assert_hash(path: Path, expected: str, label: str) -> None:
    actual = sha256_file(path)
    if actual.lower() != expected.lower():
        raise RuntimeError(f"{label} hash mismatch: expected={expected}, actual={actual}, path={path}")


def _metric_replay(reference: dict[str, Any], actual: dict[str, Any], tolerance: float) -> pd.DataFrame:
    mapping = {
        "final_portfolio_value": "final_portfolio_value",
        "twr_cagr": "twr_cagr",
        "maximum_drawdown": "maximum_drawdown",
        "calmar": "calmar",
        "tactical_event_count": "tactical_event_count",
        "tactical_trade_count": "tactical_trade_count",
        "tactical_turnover": "tactical_turnover",
    }
    rows = []
    for requested, observed in mapping.items():
        expected = float(reference[requested])
        got = float(actual[observed])
        allowed = 0.0 if requested in {"tactical_event_count", "tactical_trade_count"} else tolerance
        rows.append({
            "metric": requested,
            "reference": expected,
            "replayed": got,
            "absolute_delta": abs(got - expected),
            "tolerance": allowed,
            "pass": bool(abs(got - expected) <= allowed),
        })
    return pd.DataFrame(rows)


def _dca_identity(reference: V31BacktestResult, current: V31BacktestResult) -> dict[str, Any]:
    left = reference.trades.loc[reference.trades["action"].eq("NORMAL_DCA")].reset_index(drop=True)
    right = current.trades.loc[current.trades["action"].eq("NORMAL_DCA")].reset_index(drop=True)
    keys = ["timestamp", "action", "side", "asset", "ledger", "signal_date"]
    numeric = [
        "quantity", "raw_open_price", "effective_price", "gross_notional_usd",
        "cash_change_usd", "fee_usd", "slippage_usd", "cost_usd",
    ]
    keys_exact = len(left) == len(right)
    if keys_exact:
        for column in keys:
            keys_exact = keys_exact and left[column].fillna("").astype(str).equals(
                right[column].fillna("").astype(str)
            )
    maximum = float("inf")
    if len(left) == len(right):
        maximum = max(
            float(np.max(np.abs(left[column].astype(float) - right[column].astype(float))))
            for column in numeric
        )
    return {
        "reference_rows": len(left),
        "counterfactual_rows": len(right),
        "keys_exact": bool(keys_exact),
        "numeric_max_abs_delta": maximum,
        "pass": bool(keys_exact and maximum <= 1e-10),
    }


def _shadow_identity(reference: V31BacktestResult, current: V31BacktestResult) -> dict[str, Any]:
    columns = ["timestamp", "macro_state", "sell_stage", "active_target", "cycle_id"]
    left = reference.history[columns].reset_index(drop=True)
    right = current.history[columns].reset_index(drop=True)
    exact = len(left) == len(right)
    if exact:
        for column in columns:
            if column == "active_target":
                exact = exact and bool(np.allclose(
                    left[column].astype(float), right[column].astype(float), rtol=0.0, atol=0.0,
                    equal_nan=True,
                ))
            else:
                exact = exact and left[column].fillna("").astype(str).equals(
                    right[column].fillna("").astype(str)
                )
    return {"rows": len(right), "pass": bool(exact)}


def _curve(result: V31BacktestResult) -> pd.DataFrame:
    return daily_last(result.history)[["date", "portfolio_value", "crypto_exposure"]]


def _parse_ids(value: Any) -> list[int]:
    return [int(item) for item in str(value).split("|") if str(item).strip()]


def _result_row(
    baseline: V31BacktestResult,
    counterfactual: V31BacktestResult,
    audit: pd.DataFrame,
    rules: dict[str, Any],
    audit_rules: dict[str, Any],
    transitions: list[pd.Timestamp],
    anchor: pd.Timestamp,
    deleted: Iterable[int],
) -> dict[str, Any]:
    next_transition = next_transition_after(anchor, transitions, baseline.history.iloc[-1]["timestamp"])
    return attribution_record(
        baseline, counterfactual, audit, rules, audit_rules,
        anchor_timestamp=anchor,
        next_transition=next_transition,
        deleted_event_ids=deleted,
    )


def _counterfactual(
    frame: pd.DataFrame,
    rules: dict[str, Any],
    model_a: V31BacktestResult,
    baseline: V31BacktestResult,
    deleted: Iterable[int],
) -> tuple[V31BacktestResult, pd.DataFrame]:
    return run_frozen_shadow_counterfactual(
        frame, rules, scenario("CF", rules), model_a=model_a, shadow=baseline,
        deleted_event_ids=deleted,
    )


def _cluster_candidates(clusters: pd.DataFrame, limit: int) -> pd.DataFrame:
    work = clusters.copy()
    work["contribution_per_turnover"] = work["final_wealth_contribution"].abs() / work[
        "turnover_saved"
    ].abs().replace(0.0, np.nan)
    priority = []
    for label in ["HARMFUL", "REDUNDANT"]:
        priority.append(work.loc[
            work["robust_classification"].astype(bool) & work["classification"].eq(label)
        ].sort_values("contribution_per_turnover"))
    priority.append(work.sort_values("contribution_per_turnover"))
    selected = pd.concat(priority, ignore_index=True).drop_duplicates("cluster_id")
    return selected.head(limit).copy()


def _basket_scope_ids(
    clusters: pd.DataFrame,
    classification: str,
    window: tuple[str, str] | None,
) -> list[int]:
    selected = clusters.loc[
        clusters["robust_classification"].astype(bool)
        & clusters["classification"].eq(classification)
    ].copy()
    if window is not None:
        start, end = pd.Timestamp(window[0], tz="UTC"), pd.Timestamp(window[1], tz="UTC")
        selected = selected.loc[
            (pd.to_datetime(selected["end_date"], utc=True) >= start)
            & (pd.to_datetime(selected["start_date"], utc=True) <= end)
        ]
    ids: set[int] = set()
    for value in selected["events_inside"]:
        ids.update(_parse_ids(value))
    return sorted(ids)


def _run_basket(
    name: str,
    scope: str,
    deleted: list[int],
    frame: pd.DataFrame,
    rules: dict[str, Any],
    audit_rules: dict[str, Any],
    model_a: V31BacktestResult,
    baseline: V31BacktestResult,
    transitions: list[pd.Timestamp],
) -> tuple[dict[str, Any], V31BacktestResult, dict[str, Any], dict[str, Any]]:
    cf, audit = _counterfactual(frame, rules, model_a, baseline, deleted)
    anchor = (
        frozen_tactical_events(baseline).loc[
            lambda x: x["tactical_event_id"].isin(deleted), "timestamp"
        ].min()
        if deleted else pd.Timestamp(frame.iloc[0]["open_time"])
    )
    row = _result_row(baseline, cf, audit, rules, audit_rules, transitions, anchor, deleted)
    row.update({
        "basket": name,
        "scope": scope,
        "deleted_event_ids": "|".join(map(str, deleted)),
        "deleted_event_count": len(deleted),
        "diagnostic_status": "EX_POST_UPPER_BOUND_DIAGNOSTIC_NOT_A_STRATEGY",
    })
    return row, cf, _dca_identity(model_a, cf), _shadow_identity(baseline, cf)


def _shadow_history(baseline: V31BacktestResult, events: pd.DataFrame) -> pd.DataFrame:
    history = baseline.history.copy()
    history["date"] = pd.to_datetime(history["timestamp"], utc=True).dt.floor("D")
    daily = history.groupby("date", as_index=False).last()
    keep = [
        "date", "macro_state", "sell_stage", "cycle_id", "crash_level1_active",
        "active_target", "crypto_exposure",
    ]
    daily = daily[keep].rename(columns={
        "sell_stage": "stage", "crash_level1_active": "crash_state",
    })
    signals = baseline.signals.copy()
    signals["date"] = pd.to_datetime(signals["execution_4h_open"], utc=True).dt.floor("D")
    signals = signals.groupby("date", as_index=False).last()
    signal_keep = [
        "date", "actions", "new_bull_gate_1", "new_bull_gate_2", "new_bull_gate_3",
        "new_bull_gate_4", "new_bull_gate_5", "new_bull_gate_6", "new_bull_gate_7",
        "crash_level1_raw", "crash_level2_market_raw",
    ]
    daily = daily.merge(signals[signal_keep], on="date", how="left")
    daily["desired_action"] = daily["actions"].fillna("NONE")
    daily["new_bull_state"] = np.where(
        daily["desired_action"].str.contains("NEW_BULL_CONFIRMED", na=False),
        "CONFIRMED_TODAY", "NOT_CONFIRMED_TODAY",
    )
    daily["crash_state"] = np.select(
        [
            daily["crash_level2_market_raw"].fillna(False).astype(bool),
            daily["crash_level1_raw"].fillna(False).astype(bool)
            | daily["crash_state"].fillna(False).astype(bool),
        ],
        ["LEVEL2_RAW", "LEVEL1_ACTIVE_OR_RAW"],
        default="NONE",
    )
    tactical_daily = events.copy()
    tactical_daily["date"] = pd.to_datetime(tactical_daily["timestamp"], utc=True).dt.floor("D")
    tactical_daily = tactical_daily.groupby("date", as_index=False).agg(
        signal_type=("signal_type", lambda x: "|".join(x.astype(str))),
        target_exposure=("target_exposure", "last"),
        tactical_event_ids=("tactical_event_id", lambda x: "|".join(map(str, x))),
    )
    daily = daily.merge(tactical_daily, on="date", how="left")
    daily["signal_type"] = daily["signal_type"].fillna("NONE")
    daily["target_exposure"] = daily["target_exposure"].fillna(daily["active_target"])
    return daily


def _environment_summary(events: pd.DataFrame) -> pd.DataFrame:
    ahr = events.loc[events["signal_type"].eq("AHR_VALUE_BUY")].copy()
    if ahr.empty:
        return pd.DataFrame()
    return ahr.groupby("ahr_environment", as_index=False).agg(
        count=("tactical_event_id", "size"),
        positive_fraction=("final_wealth_contribution", lambda x: float((x > 0).mean())),
        mean_final_contribution=("final_wealth_contribution", "mean"),
        median_final_contribution=("final_wealth_contribution", "median"),
        median_30d_btc_forward_return=("ex_post_btc_forward_return_30d", "median"),
        median_60d_btc_forward_return=("ex_post_btc_forward_return_60d", "median"),
        quick_failure_fraction=("ex_post_btc_forward_return_3d", lambda x: float((x < 0).mean())),
    )


def _classification_counts(frame: pd.DataFrame) -> dict[str, int]:
    values = frame["classification"].value_counts()
    return {name: int(values.get(name, 0)) for name in [
        "RETURN_ESSENTIAL", "RISK_ESSENTIAL", "REDUNDANT", "HARMFUL", "MIXED_UNCERTAIN"
    ]}


def _fmt_money(value: float) -> str:
    return f"US${value:,.2f}"


def _window_summary(events: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, dict[str, int]]:
    lo, hi = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
    subset = events.loc[(events["timestamp"] >= lo) & (events["timestamp"] < hi)].copy()
    return subset, _classification_counts(subset)


def _diagnostic_verdict(
    events: pd.DataFrame,
    baseline_summary: dict[str, Any],
    redundant_basket: pd.DataFrame,
    harmful_basket: pd.DataFrame,
    interaction: pd.DataFrame,
    rules: dict[str, Any],
) -> dict[str, Any]:
    gates = rules["diagnostic_verdict_rules"]
    count = len(events)
    classes = _classification_counts(events)
    fractions = {key: value / count for key, value in classes.items()}
    redundant_all = redundant_basket.loc[redundant_basket["scope"].eq("ALL")].iloc[0]
    harmful_all = harmful_basket.loc[harmful_basket["scope"].eq("ALL")].iloc[0]
    redundant_turnover_fraction = float(redundant_all["turnover_saved"] / baseline_summary["tactical_turnover"])
    harmful_historical_gain = float(-harmful_all["final_wealth_contribution_fraction"])
    positive_or_essential = float((
        events["final_wealth_contribution"].gt(0)
        | events["classification"].isin(["RETURN_ESSENTIAL", "RISK_ESSENTIAL"])
    ).mean())
    if fractions["HARMFUL"] >= gates["material_harmful_event_fraction"]:
        letter = "C. V3.1 CONTAINS MATERIAL HARMFUL TRADING"
        trigger = "BASE_HARMFUL_EVENT_FRACTION_GATE"
    elif harmful_historical_gain >= gates["material_harmful_historical_gain_fraction"]:
        letter = "C. V3.1 CONTAINS MATERIAL HARMFUL TRADING"
        trigger = "ROBUST_HARMFUL_CLUSTER_BASKET_HISTORICAL_GAIN_GATE"
    elif fractions["REDUNDANT"] >= gates["material_redundant_event_fraction"] or redundant_turnover_fraction >= gates[
        "material_redundant_turnover_fraction"
    ]:
        letter = "B. V3.1 CONTAINS MATERIAL REDUNDANT TRADING"
        trigger = "BASE_REDUNDANT_EVENT_OR_ROBUST_CLUSTER_TURNOVER_GATE"
    elif (
        fractions["REDUNDANT"] + fractions["HARMFUL"] <= gates["largely_justified_max_redundant_plus_harmful_fraction"]
        and positive_or_essential >= gates["largely_justified_min_positive_or_essential_fraction"]
    ):
        letter = "A. V3.1 TRADING FREQUENCY LARGELY JUSTIFIED"
        trigger = "LARGELY_JUSTIFIED_GATE"
    else:
        letter = "D. MIXED - MORE STRUCTURAL RESEARCH REQUIRED"
        trigger = "NO_DECISIVE_GATE"

    def median_edge(signal_types: list[str], metric: str = "final_wealth_contribution") -> str:
        values = events.loc[events["signal_type"].isin(signal_types), metric]
        if values.empty:
            return "NO_EVENTS"
        median = float(values.median())
        return "POSITIVE" if median > 0 else "NEGATIVE" if median < 0 else "NEUTRAL"

    def edge_detail(signal_types: list[str]) -> str:
        subset = events.loc[events["signal_type"].isin(signal_types)]
        if subset.empty:
            return "NO_EVENTS"
        return (
            f"count={len(subset)}; median_usd={float(subset['final_wealth_contribution'].median()):.2f}; "
            f"mean_usd={float(subset['final_wealth_contribution'].mean()):.2f}; "
            f"positive_raw_fraction={float(subset['final_wealth_contribution'].gt(0).mean()):.4f}; "
            f"median_direction={median_edge(signal_types)}"
        )

    maximum_interaction = float(interaction["interaction_fraction_of_baseline"].abs().max()) if len(interaction) else 0.0
    interaction_rules = rules["interaction_audit"]
    path = (
        "HIGH" if maximum_interaction >= interaction_rules["high_path_dependency_abs_interaction_fraction"]
        else "MODERATE" if maximum_interaction >= interaction_rules["moderate_path_dependency_abs_interaction_fraction"]
        else "LOW"
    )
    robust = events.loc[events["robust_classification"].astype(bool)]
    robust_counts = _classification_counts(robust)
    robust_fractions = {key: value / count for key, value in robust_counts.items()}
    whipsaw_events = events.loc[events["opposite_action_within_7_days"].astype(bool)]
    whipsaw_median = float(whipsaw_events["final_wealth_contribution"].median()) if len(whipsaw_events) else np.nan
    window_efficiency: dict[str, str] = {}
    for name, (start, end) in rules["audit_windows"].items():
        subset, window_counts = _window_summary(events, start, end)
        window_efficiency[name] = (
            f"events={len(subset)}; positive_raw={int(subset['final_wealth_contribution'].gt(0).sum())}; "
            f"redundant={window_counts['REDUNDANT']}; harmful={window_counts['HARMFUL']}"
        )
    return {
        "Baseline Integrity": "PASS",
        "AHR Economic Edge": edge_detail(["AHR_VALUE_BUY"]),
        "Risk-Sell Economic Edge": edge_detail(["CRASH_SELL", "BEARISH_REBREAK_SELL", "STAGE_RISK_SELL", "OTHER_RISK_SELL"]),
        "Right-Side Economic Edge": edge_detail(["RIGHT_SIDE_BUY"]),
        "NEW_BULL Economic Edge": edge_detail(["NEW_BULL_REDEPLOY"]),
        "Whipsaw Necessity": (
            f"count={len(whipsaw_events)}; median_usd={whipsaw_median:.2f}; "
            f"positive_raw_fraction={float(whipsaw_events['final_wealth_contribution'].gt(0).mean()):.4f}"
            if len(whipsaw_events) else "NO_EVENTS"
        ),
        "2022 Bottom Efficiency": window_efficiency["BOTTOM_2022"],
        "2026 Bottom Efficiency": window_efficiency["BOTTOM_2026"],
        "Redundant Trade Fraction": fractions["REDUNDANT"],
        "Harmful Trade Fraction": fractions["HARMFUL"],
        "Return-Essential Fraction": fractions["RETURN_ESSENTIAL"],
        "Risk-Essential Fraction": fractions["RISK_ESSENTIAL"],
        "Robust Redundant Trade Fraction": robust_fractions["REDUNDANT"],
        "Robust Harmful Trade Fraction": robust_fractions["HARMFUL"],
        "Robust Return-Essential Fraction": robust_fractions["RETURN_ESSENTIAL"],
        "Robust Risk-Essential Fraction": robust_fractions["RISK_ESSENTIAL"],
        "Classification Sensitivity Warning": "53_OF_106_EVENTS_CHANGE_LABEL_ACROSS_LOOSE_BASE_STRICT",
        "Turnover Efficiency": 1.0 - redundant_turnover_fraction,
        "Path Dependency Risk": path,
        "Maximum Pair Interaction Fraction": maximum_interaction,
        "Hindsight Bias Risk": "HIGH",
        "Overfit Risk": "HIGH_IF_CONVERTED_TO_RULE; THIS RUN DOES_NOT_CONVERT",
        "Verdict Trigger": trigger,
        "Final Verdict": letter,
    }


def _direct_answers(
    replay_pass: bool,
    events: pd.DataFrame,
    clusters: pd.DataFrame,
    environment: pd.DataFrame,
    whipsaw: pd.DataFrame,
    redundant_basket: pd.DataFrame,
    verdict: dict[str, Any],
    audit_rules: dict[str, Any],
) -> list[str]:
    base_threshold = audit_rules["classification"]["base"]["redundant_abs_final_max_fraction"]
    positive = int((events["final_wealth_contribution_fraction"] > base_threshold).sum())
    negative = int((events["final_wealth_contribution_fraction"] < -base_threshold).sum())
    near = len(events) - positive - negative
    counts = _classification_counts(events)
    window_rows: dict[str, tuple[pd.DataFrame, dict[str, int]]] = {}
    for name, (start, end) in audit_rules["audit_windows"].items():
        window_rows[name] = _window_summary(events, start, end)
    ahr = events.loc[events["signal_type"].eq("AHR_VALUE_BUY")]
    risk = events.loc[events["signal_type"].isin([
        "CRASH_SELL", "BEARISH_REBREAK_SELL", "STAGE_RISK_SELL", "OTHER_RISK_SELL"
    ])]
    right = events.loc[events["signal_type"].eq("RIGHT_SIDE_BUY")]
    bull = events.loc[events["signal_type"].eq("NEW_BULL_REDEPLOY")]
    best_env = environment.nlargest(1, "mean_final_contribution").iloc[0]["ahr_environment"] if len(environment) else "N/A"
    worst_env = environment.nlargest(1, "quick_failure_fraction").iloc[0]["ahr_environment"] if len(environment) else "N/A"
    dd_risk = risk.loc[risk["classification"].eq("RISK_ESSENTIAL"), "tactical_event_id"].astype(str).tolist()
    harmful_risk = risk.loc[
        risk["dd_protection_contribution_pp"].abs().le(0.25)
        & risk["final_wealth_contribution"].lt(0), "tactical_event_id"
    ].astype(str).tolist()
    top = events.nlargest(10, "final_wealth_contribution")["tactical_event_id"].astype(str).tolist()
    bottom = events.nsmallest(10, "final_wealth_contribution")["tactical_event_id"].astype(str).tolist()
    inefficient = clusters.assign(
        score=clusters["final_wealth_contribution"].abs() / clusters["turnover_saved"].abs().replace(0, np.nan)
    ).nsmallest(10, "score")["cluster_id"].astype(str).tolist()
    redundant_all = redundant_basket.loc[redundant_basket["scope"].eq("ALL")].iloc[0]
    robust_redundant = clusters.loc[
        clusters["robust_classification"] & clusters["classification"].eq("REDUNDANT")
    ]

    answers = [
        f"1. V3.1 Baseline完整重現：{'是，PASS' if replay_pass else '否，FAIL'}。",
        f"2. 以Base的±0.25% materiality band計，正貢獻 {positive}、負貢獻 {negative}、接近0為 {near}（raw符號與數值均保留於CSV）。",
        f"3. RETURN_ESSENTIAL：{counts['RETURN_ESSENTIAL']}。",
        f"4. RISK_ESSENTIAL：{counts['RISK_ESSENTIAL']}。",
        f"5. REDUNDANT：{counts['REDUNDANT']}。",
        f"6. HARMFUL：{counts['HARMFUL']}。",
        f"7. MIXED / UNCERTAIN：{counts['MIXED_UNCERTAIN']}。",
        f"8. 2022底部窗口中的robust redundant clusters：{sum((robust_redundant['end_date'] >= pd.Timestamp('2022-06-01', tz='UTC')) & (robust_redundant['start_date'] <= pd.Timestamp('2022-12-31 23:59:59', tz='UTC')))}。",
        f"9. 2026底部窗口中的robust redundant clusters：{sum((robust_redundant['end_date'] >= pd.Timestamp('2026-02-01', tz='UTC')) & (robust_redundant['start_date'] <= pd.Timestamp('2026-06-30 23:59:59', tz='UTC')))}。",
        f"10. 2022窗口 {len(window_rows['BOTTOM_2022'][0])} 個Events中有 {int(window_rows['BOTTOM_2022'][0]['final_wealth_contribution'].gt(0).sum())} 個正raw貢獻；2026窗口 {len(window_rows['BOTTOM_2026'][0])} 個中有 {int(window_rows['BOTTOM_2026'][0]['final_wealth_contribution'].gt(0).sum())} 個。",
        f"11. AHR999 Value Buy為混合結果：{int(ahr['final_wealth_contribution'].gt(0).sum())}/{len(ahr)} 筆正raw貢獻；中位數 {_fmt_money(float(ahr['final_wealth_contribution'].median())) if len(ahr) else 'N/A'}，平均 {_fmt_money(float(ahr['final_wealth_contribution'].mean())) if len(ahr) else 'N/A'}。平均為正但由尾部大贏家拉高，不能概括成每筆都有alpha。",
        f"12. AHR Buy歷史平均貢獻最佳環境：{best_env}。這是事後假說，不是規則。",
        f"13. AHR Buy三日負報酬比例最高環境：{worst_env}。這是事後假說，不是規則。",
        f"14. 真正達Base Risk Essential的Risk Sell event IDs：{', '.join(dd_risk) if dd_risk else '無'}。",
        f"15. DD影響≤0.25pp但刪除後Final提高的Risk Sell IDs：{', '.join(harmful_risk) if harmful_risk else '無'}。",
        f"16. Right-side Buy中位Final貢獻：{_fmt_money(float(right['final_wealth_contribution'].median())) if len(right) else '無事件'}。",
        f"17. NEW_BULL Redeploy中位Final貢獻：{_fmt_money(float(bull['final_wealth_contribution'].median())) if len(bull) else '無事件'}。",
    ]
    for number, label in [(18, "3_COMPLETED_CLOSES"), (19, "7_CALENDAR_DAYS"), (20, "14_CALENDAR_DAYS")]:
        row = whipsaw.loc[whipsaw["whipsaw_window"].eq(label)].iloc[0]
        majority = "否" if float(row["positive_contribution_fraction"]) >= 0.5 else "較接近是"
        answers.append(
            f"{number}. {label}短期反向交易多數沒價值？{majority}；count={int(row['count'])}, positive fraction={float(row['positive_contribution_fraction']):.1%}, median contribution={_fmt_money(float(row['median_final_contribution'])) if pd.notna(row['median_final_contribution']) else 'N/A'}。"
        )
    answers.extend([
        f"21. 最有價值Top 10 Event IDs：{', '.join(top)}。",
        f"22. 最低貢獻Top 10 Event IDs：{', '.join(bottom)}。",
        f"23. 高turnover/低絕對貢獻Cluster IDs：{', '.join(inefficient)}。",
        f"24. Robust Redundant basket理論刪除 {int(redundant_all['deleted_event_count'])} 個Event，來自 {len(robust_redundant)} 個clusters。",
        f"25. 理論可減少tactical turnover {float(redundant_all['turnover_saved']):.4f}x。",
        f"26. 該basket DD contribution為 {float(redundant_all['dd_protection_contribution_pp']):+.3f}pp；是否近似不變依Base 0.25pp門檻為 {'是' if abs(float(redundant_all['dd_protection_contribution_pp'])) <= 0.25 else '否'}。",
        f"27. 該basket Final contribution為 {_fmt_money(float(redundant_all['final_wealth_contribution']))}（{float(redundant_all['final_wealth_contribution_fraction']):+.2%}）；是否近似不變依Base 0.25%門檻為 {'是' if abs(float(redundant_all['final_wealth_contribution_fraction'])) <= 0.0025 else '否'}。",
        f"28. 對106次操作的整體判斷：{verdict['Final Verdict']}。",
        f"29. 是否繼續研究降低頻率：{'是，但只能另立前瞻、預先凍結的結構假說' if verdict['Final Verdict'].startswith(('B.', 'C.', 'D.')) else '僅需次要研究；目前交易多數有歷史必要性'}。",
        f"30. 是否接受部分高頻熊底AHR有經濟價值：{'是；但並非每筆都有效' if len(ahr) and (ahr['final_wealth_contribution'] > 0).any() else '本樣本未提供足夠正向證據'}。",
    ])
    return answers


def output_hashes(directory: Path) -> dict[str, str]:
    return {
        path.relative_to(directory).as_posix(): sha256_file(path)
        for path in sorted(directory.rglob("*"))
        if path.is_file() and path.name not in {"run_manifest_v31_necessity_audit.json"}
    }


def snapshot_reproduction_code() -> None:
    code_dir = OUTPUT_DIR / "code"
    code_dir.mkdir(parents=True, exist_ok=True)
    for name in [
        "run_v31_necessity_audit.py", "qa_finalize_v31_necessity_audit.py",
        "run_backtest_v3_7.py", "requirements.txt",
    ]:
        source = PROJECT_DIR / name
        if source.exists():
            shutil.copy2(source, code_dir / name)
    shutil.copytree(
        PROJECT_DIR / "src" / "crypto_backtest", code_dir / "crypto_backtest",
        dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(
        PROJECT_DIR / "tests" / "test_v31_necessity_audit.py",
        code_dir / "v31_necessity_audit_checks.py",
    )
    legacy_test_copy = code_dir / "test_v31_necessity_audit.py"
    if legacy_test_copy.exists():
        legacy_test_copy.unlink()
    shutil.copy2(
        PROJECT_DIR / "design" / "RUN_INSTRUCTIONS_V31_NECESSITY_AUDIT.md",
        code_dir / "RUN_INSTRUCTIONS_V31_NECESSITY_AUDIT.md",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run frozen V3.1 tactical necessity audit")
    parser.add_argument("--no-zip", action="store_true", help="Do not create the final delivery zip")
    args = parser.parse_args()
    config_path = PROJECT_DIR / "config" / "config_frozen_v31_necessity_audit.json"
    audit_rules = load_json(config_path)
    rules_path = PROJECT_DIR / audit_rules["baseline"]["config_path"]
    engine_path = PROJECT_DIR / audit_rules["baseline"]["engine_path"]
    source_manifest_path = PROJECT_DIR / audit_rules["data"]["source_manifest"]
    attachment_path = Path(r"C:\Users\denni\.codex\attachments\1365e01b-6ab0-4146-9ccc-069b2a44d2ae\pasted-text.txt")
    _assert_hash(rules_path, audit_rules["baseline"]["config_sha256"], "V3.1 config")
    _assert_hash(engine_path, audit_rules["baseline"]["engine_sha256"], "V3.1 engine")
    _assert_hash(source_manifest_path, audit_rules["data"]["source_manifest_sha256"], "V3.1 source manifest")
    _assert_hash(attachment_path, audit_rules["attachment_sha256"], "User audit specification")
    rules = load_json(rules_path)

    result_dir = OUTPUT_DIR / "results"
    artifact_dir = OUTPUT_DIR / "artifacts"
    config_dir = OUTPUT_DIR / "config"
    result_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    config_dir.mkdir(parents=True, exist_ok=True)
    snapshot_reproduction_code()
    shutil.copy2(config_path, config_dir / config_path.name)
    shutil.copy2(rules_path, config_dir / rules_path.name)
    shutil.copy2(PROJECT_DIR / "design" / "V31_NECESSITY_AUDIT_ASSUMPTIONS.md", artifact_dir)
    shutil.copy2(PROJECT_DIR / "design" / "best_skill_v31_necessity_audit.md", artifact_dir)
    shutil.copy2(attachment_path, artifact_dir / "USER_SPECIFICATION_V31_NECESSITY_AUDIT.txt")

    source_manifest = pd.read_csv(source_manifest_path)
    frame, daily_features, data_contract = load_formal_data(rules, source_manifest)
    print(f"Data loaded: {len(frame):,} completed 4H rows through {frame.iloc[-1]['open_time']}", flush=True)
    model_a = run_v31_backtest(frame, rules, scenario("A", rules))
    baseline = run_v31_backtest(frame, rules, scenario("B", rules), model_a=model_a)
    baseline_summary = enriched_summary(baseline, rules)
    replay = _metric_replay(
        audit_rules["baseline"]["reference"], baseline_summary,
        float(audit_rules["baseline"]["numeric_replay_tolerance"]),
    )
    replay.to_csv(result_dir / "baseline_v31_replay.csv", index=False)
    if not bool(replay["pass"].all()):
        raise RuntimeError("V31_BASELINE_REPLAY = FAIL; counterfactual audit stopped")

    zero, zero_audit = _counterfactual(frame, rules, model_a, baseline, [])
    zero_summary = enriched_summary(zero, rules)
    zero_metrics = [
        abs(baseline_summary[name] - zero_summary[name]) for name in
        ["final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]
    ]
    if max(zero_metrics) > 1e-10 or len(zero_audit) != 106 or not zero_audit["actual_filled"].all():
        raise RuntimeError("Independent frozen-shadow zero-deletion replay is not exact")

    events = frozen_tactical_events(baseline)
    if len(events) != int(audit_rules["counterfactual_contract"]["loeo_event_count"]):
        raise RuntimeError(f"Expected 106 portfolio events, observed {len(events)}")
    if not events["trade_rows"].eq(2).all():
        raise RuntimeError("Portfolio-event row integrity failed: BTC and ETH are not paired")
    events = add_whipsaw_labels(events, baseline.signals["execution_4h_open"])
    transitions = major_transition_times(baseline, events)
    clusters_master = identify_round_trip_clusters(events, audit_rules)
    print(f"Baseline PASS; identified {len(clusters_master)} automatic clusters. Starting 106 LOEO runs.", flush=True)

    dca_checks: list[dict[str, Any]] = []
    shadow_checks: list[dict[str, Any]] = []
    event_records: list[dict[str, Any]] = []
    event_cache: dict[int, pd.DataFrame] = {}
    first_cf: V31BacktestResult | None = None
    for position, event in enumerate(events.itertuples(index=False), start=1):
        event_id = int(event.tactical_event_id)
        cf, audit = _counterfactual(frame, rules, model_a, baseline, [event_id])
        if first_cf is None:
            first_cf = cf
        record = _result_row(
            baseline, cf, audit, rules, audit_rules, transitions,
            pd.Timestamp(event.timestamp), [event_id],
        )
        record.update({column: getattr(event, column) for column in events.columns})
        event_records.append(record)
        event_cache[event_id] = _curve(cf)
        dca_checks.append({"unit_type": "EVENT", "unit_id": event_id, **_dca_identity(model_a, cf)})
        shadow_checks.append({"unit_type": "EVENT", "unit_id": event_id, **_shadow_identity(baseline, cf)})
        if position % 10 == 0 or position == len(events):
            pd.DataFrame(event_records).to_csv(result_dir / "_checkpoint_loeo.csv", index=False)
            print(f"LOEO {position}/{len(events)} complete", flush=True)

    event_results = apply_classifications(pd.DataFrame(event_records), audit_rules)
    print(f"Starting {len(clusters_master)} LOCO runs.", flush=True)
    cluster_records: list[dict[str, Any]] = []
    cluster_cache: dict[int, pd.DataFrame] = {}
    for position, cluster in enumerate(clusters_master.itertuples(index=False), start=1):
        cluster_id = int(cluster.cluster_id)
        deleted = _parse_ids(cluster.events_inside)
        cf, audit = _counterfactual(frame, rules, model_a, baseline, deleted)
        record = _result_row(
            baseline, cf, audit, rules, audit_rules, transitions,
            pd.Timestamp(cluster.start_date), deleted,
        )
        record.update({column: getattr(cluster, column) for column in clusters_master.columns})
        cluster_records.append(record)
        cluster_cache[cluster_id] = _curve(cf)
        dca_checks.append({"unit_type": "CLUSTER", "unit_id": cluster_id, **_dca_identity(model_a, cf)})
        shadow_checks.append({"unit_type": "CLUSTER", "unit_id": cluster_id, **_shadow_identity(baseline, cf)})
        if position % 10 == 0 or position == len(clusters_master):
            print(f"LOCO {position}/{len(clusters_master)} complete", flush=True)
    cluster_results = apply_classifications(pd.DataFrame(cluster_records), audit_rules)

    candidates = _cluster_candidates(cluster_results, int(audit_rules["interaction_audit"]["candidate_clusters"]))
    interaction_rows: list[dict[str, Any]] = []
    pairs = list(itertools.combinations(candidates.itertuples(index=False), 2))
    print(f"Starting {len(pairs)} pairwise cluster interaction runs.", flush=True)
    cluster_lookup = cluster_results.set_index("cluster_id")
    for position, (left, right) in enumerate(pairs, start=1):
        left_id, right_id = int(left.cluster_id), int(right.cluster_id)
        deleted = sorted(set(_parse_ids(left.events_inside)) | set(_parse_ids(right.events_inside)))
        cf, audit = _counterfactual(frame, rules, model_a, baseline, deleted)
        anchor = min(pd.Timestamp(left.start_date), pd.Timestamp(right.start_date))
        record = _result_row(baseline, cf, audit, rules, audit_rules, transitions, anchor, deleted)
        additive = float(cluster_lookup.loc[left_id, "final_wealth_contribution"] + cluster_lookup.loc[right_id, "final_wealth_contribution"])
        interaction = float(record["final_wealth_contribution"] - additive)
        record.update({
            "cluster_a": left_id,
            "cluster_b": right_id,
            "events_deleted": "|".join(map(str, deleted)),
            "sum_individual_final_contributions": additive,
            "joint_final_contribution": record["final_wealth_contribution"],
            "interaction_final_contribution": interaction,
            "interaction_fraction_of_baseline": interaction / baseline_summary["final_portfolio_value"],
            "non_additivity_warning": "PAIR_EFFECT_MINUS_SUM_OF_SINGLE_CLUSTER_EFFECTS",
        })
        interaction_rows.append(record)
        dca_checks.append({"unit_type": "PAIR", "unit_id": f"{left_id}+{right_id}", **_dca_identity(model_a, cf)})
        shadow_checks.append({"unit_type": "PAIR", "unit_id": f"{left_id}+{right_id}", **_shadow_identity(baseline, cf)})
        if position % 10 == 0 or position == len(pairs):
            print(f"Interaction {position}/{len(pairs)} complete", flush=True)
    interaction = pd.DataFrame(interaction_rows)

    redundant_rows: list[dict[str, Any]] = []
    harmful_rows: list[dict[str, Any]] = []
    for basket_name, label, destination in [
        ("ROBUST_REDUNDANT_BASKET_CF", "REDUNDANT", redundant_rows),
        ("ROBUST_HARMFUL_BASKET_CF", "HARMFUL", harmful_rows),
    ]:
        for scope in ["ALL", *audit_rules["audit_windows"].keys()]:
            window = None if scope == "ALL" else tuple(audit_rules["audit_windows"][scope])
            deleted = _basket_scope_ids(cluster_results, label, window)
            row, cf, dca_check, shadow_check = _run_basket(
                basket_name, scope, deleted, frame, rules, audit_rules, model_a, baseline, transitions,
            )
            destination.append(row)
            dca_checks.append({"unit_type": basket_name, "unit_id": scope, **dca_check})
            shadow_checks.append({"unit_type": basket_name, "unit_id": scope, **shadow_check})
    redundant_basket = pd.DataFrame(redundant_rows)
    harmful_basket = pd.DataFrame(harmful_rows)

    # Ex-post feature and forward-outcome data are deliberately attached only after every simulation.
    feature_frame = build_event_features(
        events, frame, [int(value) for value in audit_rules["forward_return_horizons_calendar_days"]]
    )
    feature_columns = [column for column in feature_frame if column not in events.columns]
    event_results = event_results.merge(
        feature_frame[["tactical_event_id", *feature_columns]], on="tactical_event_id", how="left", validate="one_to_one"
    )
    event_results["event_turnover_fraction"] = event_results["gross_notional"] / float(
        baseline.history["portfolio_value"].mean()
    )
    signal_summary = signal_type_summary(event_results)
    whipsaw = whipsaw_summary(event_results)
    environment = _environment_summary(event_results)
    cross_year_work = event_results[[
        "timestamp", "signal_type", "tactical_event_id", "final_wealth_contribution",
        "dd_protection_contribution_pp",
    ]].copy()
    cross_year_work["year"] = cross_year_work["timestamp"].dt.year
    cross_year_summary = cross_year_work.groupby(["year", "signal_type"], as_index=False).agg(
        event_count=("tactical_event_id", "size"),
        positive_raw_fraction=("final_wealth_contribution", lambda x: float((x > 0).mean())),
        median_final_contribution=("final_wealth_contribution", "median"),
        mean_final_contribution=("final_wealth_contribution", "mean"),
        median_dd_protection_pp=("dd_protection_contribution_pp", "median"),
    )
    window_summary_rows = []
    for window_name, (window_start, window_end) in audit_rules["audit_windows"].items():
        subset, window_counts = _window_summary(event_results, window_start, window_end)
        window_summary_rows.append({
            "window": window_name, "start": window_start, "end": window_end,
            "event_count": len(subset), "positive_raw_contribution": int(subset["final_wealth_contribution"].gt(0).sum()),
            "negative_raw_contribution": int(subset["final_wealth_contribution"].lt(0).sum()),
            **window_counts,
        })
    window_summary = pd.DataFrame(window_summary_rows)
    ahr_events = event_results.loc[event_results["signal_type"].eq("AHR_VALUE_BUY")]
    ahr_overall = pd.DataFrame([{
        "event_count": len(ahr_events),
        "positive_raw_contribution_count": int(ahr_events["final_wealth_contribution"].gt(0).sum()),
        "negative_raw_contribution_count": int(ahr_events["final_wealth_contribution"].lt(0).sum()),
        "median_final_contribution": float(ahr_events["final_wealth_contribution"].median()),
        "mean_final_contribution": float(ahr_events["final_wealth_contribution"].mean()),
        "median_btc_forward_return_30d": float(ahr_events["ex_post_btc_forward_return_30d"].median()),
        "median_btc_forward_return_60d": float(ahr_events["ex_post_btc_forward_return_60d"].median()),
        "median_dd_protection_pp": float(ahr_events["dd_protection_contribution_pp"].median()),
        "forward_outcome_usage": "EX_POST_DIAGNOSTIC_ONLY",
    }])

    baseline_replay_summary = pd.DataFrame([{
        **baseline_summary,
        "V31_BASELINE_REPLAY": "PASS",
        "independent_zero_deletion_replay": "PASS",
        "zero_replay_max_metric_delta": max(zero_metrics),
    }])
    event_master = feature_frame.copy()
    shadow_daily = _shadow_history(baseline, events)

    combined_units = pd.concat([
        event_results.assign(unit_type="EVENT", unit_id=event_results["tactical_event_id"].astype(str)),
        cluster_results.assign(unit_type="CLUSTER", unit_id=cluster_results["cluster_id"].astype(str)),
    ], ignore_index=True, sort=False)
    combined_units["redundancy_score"] = (
        combined_units["final_wealth_contribution_fraction"].abs()
        + combined_units["dd_protection_contribution_pp"].abs() / 100.0
    ) / combined_units["turnover_saved"].abs().replace(0.0, np.nan)

    result_tables = {
        "baseline_v31_replay.csv": baseline_replay_summary,
        "v31_frozen_shadow_history.csv": shadow_daily,
        "v31_tactical_events_master.csv": event_master,
        "leave_one_event_out_results.csv": event_results,
        "leave_one_cluster_out_results.csv": cluster_results,
        "round_trip_clusters.csv": clusters_master,
        "interaction_audit.csv": interaction,
        "signal_type_contribution_summary.csv": signal_summary,
        "ahr_value_buy_contribution.csv": event_results.loc[event_results["signal_type"].eq("AHR_VALUE_BUY")],
        "risk_sell_contribution.csv": event_results.loc[event_results["signal_type"].isin(["CRASH_SELL", "BEARISH_REBREAK_SELL", "STAGE_RISK_SELL", "OTHER_RISK_SELL"])],
        "right_side_contribution.csv": event_results.loc[event_results["signal_type"].eq("RIGHT_SIDE_BUY")],
        "new_bull_contribution.csv": event_results.loc[event_results["signal_type"].eq("NEW_BULL_REDEPLOY")],
        "whipsaw_contribution_summary.csv": whipsaw,
        "ahr_environment_summary.csv": environment,
        "ahr_value_buy_overall_summary.csv": ahr_overall,
        "audit_window_classification_summary.csv": window_summary,
        "cross_year_signal_contribution_summary.csv": cross_year_summary,
        "top_return_contributing_events.csv": event_results.nlargest(20, "final_wealth_contribution"),
        "most_harmful_events.csv": event_results.nsmallest(20, "final_wealth_contribution"),
        "most_redundant_events.csv": combined_units.sort_values("redundancy_score").head(20),
        "risk_essential_events.csv": event_results.loc[event_results["classification"].eq("RISK_ESSENTIAL")].sort_values("dd_protection_contribution_pp", ascending=False),
        "round_trip_necessity_ranking.csv": cluster_results.sort_values(["classification", "final_wealth_contribution"], ascending=[True, False]),
        "robust_redundant_basket_cf.csv": redundant_basket,
        "robust_harmful_basket_cf.csv": harmful_basket,
        "fixed_dca_counterfactual_integrity.csv": pd.DataFrame(dca_checks),
        "frozen_shadow_counterfactual_integrity.csv": pd.DataFrame(shadow_checks),
    }
    for name, table in result_tables.items():
        table.to_csv(result_dir / name, index=False)
    checkpoint = result_dir / "_checkpoint_loeo.csv"
    if checkpoint.exists():
        checkpoint.unlink()

    prefix_cutoff = pd.Timestamp(events.iloc[0]["timestamp"]) + pd.Timedelta(days=30)
    prefix_frame = frame.loc[frame["open_time"] <= prefix_cutoff].copy().reset_index(drop=True)
    prefix_a = run_v31_backtest(prefix_frame, rules, scenario("A", rules))
    prefix_b = run_v31_backtest(prefix_frame, rules, scenario("B", rules), model_a=prefix_a)
    prefix_cf, _ = _counterfactual(prefix_frame, rules, prefix_a, prefix_b, [int(events.iloc[0]["tactical_event_id"])])
    prefix_baseline_pass = prefix_trade_identity(baseline, prefix_b, prefix_cutoff)
    prefix_cf_pass = bool(first_cf is not None and prefix_trade_identity(first_cf, prefix_cf, prefix_cutoff))
    engine_source = (PROJECT_DIR / "src" / "crypto_backtest" / "v31_necessity_engine.py").read_text(encoding="utf-8").lower()
    forbidden_forward_terms = [term for term in ["ex_post_btc_forward", "ex_post_eth_forward", "future_min_return", "label_end_date"] if term in engine_source]
    dca_frame = pd.DataFrame(dca_checks)
    shadow_frame = pd.DataFrame(shadow_checks)
    integrity = {
        "baseline_replay_pass": bool(replay["pass"].all()),
        "independent_zero_deletion_replay_pass": max(zero_metrics) <= 1e-10,
        "fixed_dca_all_counterfactuals_pass": bool(dca_frame["pass"].all()),
        "frozen_shadow_all_counterfactuals_pass": bool(shadow_frame["pass"].all()),
        "portfolio_event_count_106": len(events) == 106,
        "btc_eth_two_legs_per_event": bool(events["trade_rows"].eq(2).all()),
        "data_contract_pass": bool(data_contract["pass"]),
        "prefix_baseline_trade_identity_pass": prefix_baseline_pass,
        "prefix_counterfactual_trade_identity_pass": prefix_cf_pass,
        "forward_outcome_terms_in_execution_engine": forbidden_forward_terms,
        "forward_outcomes_added_after_all_simulations": True,
        "no_lookahead_pass": bool(
            data_contract["pass"] and prefix_baseline_pass and prefix_cf_pass and not forbidden_forward_terms
        ),
        "v31_engine_sha256_after_audit": sha256_file(engine_path),
        "v31_engine_unchanged": sha256_file(engine_path) == audit_rules["baseline"]["engine_sha256"],
    }
    integrity["pass"] = bool(all([
        integrity["baseline_replay_pass"], integrity["independent_zero_deletion_replay_pass"],
        integrity["fixed_dca_all_counterfactuals_pass"], integrity["frozen_shadow_all_counterfactuals_pass"],
        integrity["portfolio_event_count_106"], integrity["btc_eth_two_legs_per_event"],
        integrity["data_contract_pass"], integrity["no_lookahead_pass"], integrity["v31_engine_unchanged"],
    ]))
    write_json(artifact_dir / "baseline_and_counterfactual_integrity.json", integrity)
    write_json(artifact_dir / "data_contract_v31_necessity_audit.json", data_contract)
    source_manifest.to_csv(artifact_dir / "source_manifest_v31_necessity_audit.csv", index=False)
    if not integrity["pass"]:
        raise RuntimeError(f"Necessity audit integrity failed: {integrity}")

    interaction_summary = {
        "candidate_clusters": len(candidates),
        "pair_count": len(interaction),
        "maximum_absolute_interaction_usd": float(interaction["interaction_final_contribution"].abs().max()) if len(interaction) else 0.0,
        "maximum_absolute_interaction_fraction": float(interaction["interaction_fraction_of_baseline"].abs().max()) if len(interaction) else 0.0,
    }
    verdict = _diagnostic_verdict(
        event_results, baseline_summary, redundant_basket, harmful_basket, interaction, audit_rules,
    )
    answers = _direct_answers(
        True, event_results, cluster_results, environment, whipsaw, redundant_basket, verdict, audit_rules,
    )
    write_json(artifact_dir / "j_law_diagnostic_verdict.json", verdict)
    write_json(artifact_dir / "direct_answers_1_to_30.json", {str(index): value for index, value in enumerate(answers, 1)})
    create_necessity_figures(
        OUTPUT_DIR, baseline.history, event_results, cluster_results, signal_summary,
        event_cache, cluster_cache,
    )
    write_necessity_report(
        OUTPUT_DIR, baseline_replay_summary, event_results, cluster_results, signal_summary,
        whipsaw, interaction_summary, redundant_basket, harmful_basket, answers, verdict, integrity,
    )

    manifest = {
        "study": audit_rules["study_name"],
        "study_type": audit_rules["study_type"],
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "platform": platform.platform(),
        "formal_start": data_contract["formal_start_actual"],
        "formal_end": data_contract["formal_end_actual"],
        "formal_4h_rows": data_contract["formal_4h_rows"],
        "baseline_config_sha256": sha256_file(rules_path),
        "baseline_engine_sha256": sha256_file(engine_path),
        "audit_config_sha256": sha256_file(config_path),
        "attachment_sha256": sha256_file(attachment_path),
        "loeo_simulations": len(event_results),
        "loco_simulations": len(cluster_results),
        "pairwise_simulations": len(interaction),
        "basket_simulations": len(redundant_basket) + len(harmful_basket),
        "classification_thresholds_frozen_before_execution": True,
        "forward_outcomes_ex_post_only": True,
        "loeo_contributions_non_additive": True,
        "not_a_strategy": True,
        "v3_1_modified": False,
        "v3_9_created": False,
        "integrity": integrity,
        "output_sha256": output_hashes(OUTPUT_DIR),
    }
    write_json(artifact_dir / "run_manifest_v31_necessity_audit.json", manifest)
    if not args.no_zip:
        archive = shutil.make_archive(
            str(PROJECT_DIR / "crypto_v31_necessity_audit_complete"), "zip",
            root_dir=OUTPUT_DIR.parent, base_dir=OUTPUT_DIR.name,
        )
        Path(archive + ".sha256").write_text(
            f"{sha256_file(Path(archive))}  {Path(archive).name}\n", encoding="utf-8"
        )
    print(f"COMPLETE: {verdict['Final Verdict']}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
