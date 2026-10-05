from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


CLASS_COLORS = {
    "RETURN_ESSENTIAL": "#1b9e77",
    "RISK_ESSENTIAL": "#377eb8",
    "REDUNDANT": "#7570b3",
    "HARMFUL": "#d95f02",
    "MIXED_UNCERTAIN": "#666666",
}
CLASS_MARKERS = {
    "RETURN_ESSENTIAL": "^",
    "RISK_ESSENTIAL": "s",
    "REDUNDANT": "o",
    "HARMFUL": "X",
    "MIXED_UNCERTAIN": "D",
}


def _save(fig: plt.Figure, figure_dir: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(figure_dir / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(figure_dir / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _daily_baseline(history: pd.DataFrame) -> pd.DataFrame:
    work = history.copy()
    work["date"] = pd.to_datetime(work["timestamp"], utc=True).dt.floor("D")
    return work.groupby("date", as_index=False).last()


def _necessity_map(
    daily: pd.DataFrame,
    events: pd.DataFrame,
    figure_dir: Path,
    stem: str,
    title: str,
    start: str | None = None,
    end: str | None = None,
) -> None:
    segment = daily.copy()
    selected = events.copy()
    if start is not None:
        start_ts = pd.Timestamp(start, tz="UTC")
        segment = segment.loc[segment["date"] >= start_ts]
        selected = selected.loc[selected["timestamp"] >= start_ts]
    if end is not None:
        end_ts = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
        segment = segment.loc[segment["date"] <= end_ts]
        selected = selected.loc[selected["timestamp"] <= end_ts]
    fig, axes = plt.subplots(2, 1, figsize=(14, 8), sharex=True, gridspec_kw={"height_ratios": [2, 1]})
    axes[0].plot(segment["date"], segment["BTC_close"], color="#222222", lw=1.4, label="BTC close")
    price = segment.set_index("date")["BTC_close"]
    for label, group in selected.groupby("classification"):
        event_days = group["timestamp"].dt.floor("D")
        y = price.reindex(event_days, method="nearest").to_numpy()
        axes[0].scatter(
            event_days,
            y,
            label=label,
            color=CLASS_COLORS.get(label, "black"),
            marker=CLASS_MARKERS.get(label, "o"),
            s=42,
            alpha=0.85,
            zorder=4,
        )
    axes[0].set_ylabel("BTC USD")
    axes[0].legend(ncol=3, fontsize=8)
    axes[0].set_title(title)
    axes[1].plot(segment["date"], 100 * segment["crypto_exposure"], color="#2ca02c", lw=1.3)
    axes[1].set_ylabel("V3.1 exposure %")
    axes[1].set_xlabel("UTC date")
    axes[1].grid(alpha=0.25)
    axes[0].grid(alpha=0.25)
    _save(fig, figure_dir, stem)


def _equity_examples(
    baseline_daily: pd.DataFrame,
    selected: pd.DataFrame,
    cache: dict[int, pd.DataFrame],
    id_column: str,
    figure_dir: Path,
    stem: str,
    title: str,
) -> None:
    fig, ax = plt.subplots(figsize=(13, 6))
    base = baseline_daily.set_index("date")["portfolio_value"]
    ax.plot(base.index, base, color="black", lw=2.0, label="V3.1 baseline")
    for row in selected.itertuples(index=False):
        item_id = int(getattr(row, id_column))
        curve = cache.get(item_id)
        if curve is None:
            continue
        series = curve.set_index("date")["portfolio_value"]
        ax.plot(series.index, series, lw=1.0, alpha=0.8, label=f"delete {id_column}={item_id}")
    ax.set_title(title)
    ax.set_xlabel("UTC date")
    ax.set_ylabel("Portfolio value USD")
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8, ncol=2)
    _save(fig, figure_dir, stem)


def create_necessity_figures(
    output_dir: Path,
    baseline_history: pd.DataFrame,
    event_results: pd.DataFrame,
    cluster_results: pd.DataFrame,
    signal_summary: pd.DataFrame,
    event_daily_cache: dict[int, pd.DataFrame],
    cluster_daily_cache: dict[int, pd.DataFrame],
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    daily = _daily_baseline(baseline_history)
    _necessity_map(
        daily, event_results, figure_dir, "01_2022_trade_necessity_map",
        "2022 V3.1 tactical-event necessity map", "2022-06-01", "2022-12-31",
    )
    _necessity_map(
        daily, event_results, figure_dir, "02_2026_trade_necessity_map",
        "2026 V3.1 tactical-event necessity map", "2026-02-01", "2026-06-30",
    )
    _necessity_map(
        daily, event_results, figure_dir, "03_full_trade_necessity_map",
        "Full-history V3.1 tactical-event necessity map",
    )

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(event_results["final_wealth_contribution"], bins=28, color="#4c78a8", alpha=0.85)
    ax.axvline(0, color="black", ls="--", lw=1)
    ax.set_title("Distribution of 106 LOEO final-wealth contributions")
    ax.set_xlabel("Baseline final value - counterfactual final value (USD)")
    ax.set_ylabel("Event count")
    _save(fig, figure_dir, "04_event_contribution_distribution")

    fig, ax = plt.subplots(figsize=(9, 6))
    for label, group in event_results.groupby("classification"):
        ax.scatter(
            group["event_turnover_fraction"], group["final_wealth_contribution"],
            color=CLASS_COLORS.get(label, "black"), marker=CLASS_MARKERS.get(label, "o"),
            alpha=0.8, label=label,
        )
    ax.axhline(0, color="black", ls="--", lw=1)
    ax.set_xlabel("Baseline event gross notional / average portfolio value")
    ax.set_ylabel("Final wealth contribution USD")
    ax.set_title("Turnover versus economic contribution")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    _save(fig, figure_dir, "05_turnover_vs_contribution")

    fig, ax = plt.subplots(figsize=(9, 6))
    for label, group in event_results.groupby("classification"):
        ax.scatter(
            group["final_wealth_contribution"], group["dd_protection_contribution_pp"],
            color=CLASS_COLORS.get(label, "black"), marker=CLASS_MARKERS.get(label, "o"),
            alpha=0.8, label=label,
        )
    ax.axhline(0, color="black", ls="--", lw=1)
    ax.axvline(0, color="black", ls="--", lw=1)
    ax.set_xlabel("Final wealth contribution USD")
    ax.set_ylabel("Overall DD protection contribution pp")
    ax.set_title("Risk versus return contribution")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25)
    _save(fig, figure_dir, "06_risk_return_contribution")

    ordered = signal_summary.sort_values("mean_final_contribution")
    x = np.arange(len(ordered))
    fig, ax = plt.subplots(figsize=(11, 6))
    ax.bar(x - 0.2, ordered["mean_final_contribution"], width=0.4, label="Mean")
    ax.bar(x + 0.2, ordered["median_final_contribution"], width=0.4, label="Median")
    ax.axhline(0, color="black", ls="--", lw=1)
    ax.set_xticks(x, ordered["signal_type"], rotation=30, ha="right")
    ax.set_ylabel("Final wealth contribution USD")
    ax.set_title("Contribution by frozen V3.1 signal type")
    ax.legend()
    _save(fig, figure_dir, "07_signal_type_contribution")

    top_return = event_results.loc[
        event_results["classification"].eq("RETURN_ESSENTIAL")
    ].nlargest(5, "final_wealth_contribution")
    top_harmful = event_results.loc[
        event_results["classification"].eq("HARMFUL")
    ].nsmallest(5, "final_wealth_contribution")
    redundant = cluster_results.loc[cluster_results["classification"].eq("REDUNDANT")].copy()
    if len(redundant) < 5:
        redundant = cluster_results.assign(
            _distance=cluster_results["final_wealth_contribution"].abs()
        ).nsmallest(5, "_distance")
    else:
        redundant = redundant.nlargest(5, "turnover_saved")
    _equity_examples(daily, top_return, event_daily_cache, "tactical_event_id", figure_dir,
                     "08_counterfactual_equity_top_return", "Top five return-essential LOEO examples")
    _equity_examples(daily, top_harmful, event_daily_cache, "tactical_event_id", figure_dir,
                     "09_counterfactual_equity_top_harmful", "Top five historically harmful LOEO examples")
    _equity_examples(daily, redundant, cluster_daily_cache, "cluster_id", figure_dir,
                     "10_counterfactual_equity_redundant_clusters", "Five low-contribution cluster counterfactuals")


def _md(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(no rows)"
    return "\n".join([
        "| " + " | ".join(frame.columns.astype(str)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
        *["| " + " | ".join(str(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None)],
    ])


def write_necessity_report(
    output_dir: Path,
    baseline_replay: pd.DataFrame,
    event_results: pd.DataFrame,
    cluster_results: pd.DataFrame,
    signal_summary: pd.DataFrame,
    whipsaw: pd.DataFrame,
    interaction_summary: dict[str, Any],
    basket_redundant: pd.DataFrame,
    basket_harmful: pd.DataFrame,
    direct_answers: list[str],
    j_law: dict[str, Any],
    integrity: dict[str, Any],
) -> None:
    top_return = event_results.nlargest(10, "final_wealth_contribution")[[
        "tactical_event_id", "timestamp", "action", "signal_type", "final_wealth_contribution",
        "dd_protection_contribution_pp", "classification", "robust_classification"
    ]]
    top_harmful = event_results.nsmallest(10, "final_wealth_contribution")[[
        "tactical_event_id", "timestamp", "action", "signal_type", "final_wealth_contribution",
        "dd_protection_contribution_pp", "classification", "robust_classification"
    ]]
    class_counts = event_results["classification"].value_counts().rename_axis("classification").reset_index(name="events")
    sensitivity_counts = pd.concat([
        event_results[column].value_counts().rename_axis("classification").reset_index(name="events").assign(
            sensitivity=column.removeprefix("classification_").upper()
        )
        for column in ["classification_loose", "classification_base", "classification_strict"]
    ], ignore_index=True)[["sensitivity", "classification", "events"]]
    robust_counts = event_results.loc[event_results["robust_classification"].astype(bool), "classification"].value_counts().rename_axis(
        "classification"
    ).reset_index(name="robust_events")
    window_rows = []
    for window, start, end in [
        ("BOTTOM_2022", "2022-06-01", "2022-12-31"),
        ("BOTTOM_2026", "2026-02-01", "2026-06-30"),
    ]:
        lo = pd.Timestamp(start, tz="UTC")
        hi = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        subset = event_results.loc[(event_results["timestamp"] >= lo) & (event_results["timestamp"] < hi)]
        counts = subset["classification"].value_counts()
        window_rows.append({
            "window": window, "events": len(subset),
            "RETURN_ESSENTIAL": int(counts.get("RETURN_ESSENTIAL", 0)),
            "RISK_ESSENTIAL": int(counts.get("RISK_ESSENTIAL", 0)),
            "REDUNDANT": int(counts.get("REDUNDANT", 0)),
            "HARMFUL": int(counts.get("HARMFUL", 0)),
            "MIXED_UNCERTAIN": int(counts.get("MIXED_UNCERTAIN", 0)),
            "positive_raw_contribution": int(subset["final_wealth_contribution"].gt(0).sum()),
        })
    window_summary = pd.DataFrame(window_rows)
    ahr = event_results.loc[event_results["signal_type"].eq("AHR_VALUE_BUY")]
    ahr_summary = pd.DataFrame([{
        "events": len(ahr),
        "positive_raw": int(ahr["final_wealth_contribution"].gt(0).sum()),
        "negative_raw": int(ahr["final_wealth_contribution"].lt(0).sum()),
        "median_final_contribution": float(ahr["final_wealth_contribution"].median()),
        "mean_final_contribution": float(ahr["final_wealth_contribution"].mean()),
        "median_btc_forward_30d": float(ahr["ex_post_btc_forward_return_30d"].median()),
        "median_btc_forward_60d": float(ahr["ex_post_btc_forward_return_60d"].median()),
        "median_overall_dd_protection_pp": float(ahr["dd_protection_contribution_pp"].median()),
        "forward_data_status": "EX_POST_DIAGNOSTIC_ONLY",
    }])
    ahr_environment = ahr.groupby("ahr_environment", as_index=False).agg(
        events=("tactical_event_id", "size"),
        positive_fraction=("final_wealth_contribution", lambda x: float((x > 0).mean())),
        median_final_contribution=("final_wealth_contribution", "median"),
        mean_final_contribution=("final_wealth_contribution", "mean"),
        median_btc_forward_3d=("ex_post_btc_forward_return_3d", "median"),
        median_btc_forward_30d=("ex_post_btc_forward_return_30d", "median"),
    )
    report = f"""# BTC+ETH V3.1 Tactical Event / Round-Trip Necessity Audit

## Research-only verdict

**{j_law['Final Verdict']}**

- `BASELINE_INTEGRITY = {'PASS' if integrity['pass'] else 'FAIL'}`
- `V31_BASELINE_REPLAY = {'PASS' if integrity['baseline_replay_pass'] else 'FAIL'}`
- `FIXED_DCA_ROW_INTEGRITY = {'PASS' if integrity['fixed_dca_all_counterfactuals_pass'] else 'FAIL'}`
- `FROZEN_SHADOW_HISTORY = {'PASS' if integrity['frozen_shadow_all_counterfactuals_pass'] else 'FAIL'}`
- `NO_LOOK_AHEAD = {'PASS' if integrity['no_lookahead_pass'] else 'FAIL'}`
- This is diagnostic attribution only. It is not V3.9 and no trading rule was changed.

## Baseline replay

{_md(baseline_replay)}

## Event classification counts

{_md(class_counts)}

The formal verdict uses the pre-frozen **Base** labels. Sensitivity disagreement is material and must not be hidden:

{_md(sensitivity_counts)}

Robust classifications (same label under Loose/Base/Strict):

{_md(robust_counts)}

## 2022 and 2026 audit windows

{_md(window_summary)}

## AHR999 overall attribution

{_md(ahr_summary)}

Environment slices (hypothesis generation only):

{_md(ahr_environment)}

## Cross-period structural reading

- AHR attribution is heavy-tailed: its median and mean point in different directions. Therefore neither "AHR always has alpha" nor "AHR is useless" is supported.
- The short-whipsaw groups retain slightly more than half positive raw contributions. Short spacing alone is not a sufficient historical discriminator.
- Risk-sell effects are dispersed: some events protect local/overall drawdown while several improve ending wealth when deleted. Signal name alone is not enough.
- The largest pair interaction is reported as a fraction of baseline wealth. This path dependence is why isolated rankings must not become a deletion rule.
- Environment cell sizes are shown explicitly. Small cells are weak hypothesis evidence, not a basis for a new threshold.

## Direct answers

{chr(10).join(direct_answers)}

## Signal-type contribution

{_md(signal_summary)}

## Whipsaw contribution

{_md(whipsaw)}

## Top 10 return contributors

{_md(top_return)}

## Top 10 historically harmful events

{_md(top_harmful)}

## Robust Redundant basket (hindsight upper bound)

{_md(basket_redundant)}

## Robust Harmful basket (severe hindsight upper bound)

{_md(basket_harmful)}

## J Law Diagnostic Verdict

```json
{json.dumps(j_law, indent=2, ensure_ascii=False)}
```

- The letter verdict is a reporting-gate result, not proof of a causal trading rule. Read its `Verdict Trigger` together with the robust fractions.

## Interaction and non-additivity

- LOEO contributions are non-additive. They cannot be summed to obtain strategy return.
- Pairwise audit: {json.dumps(interaction_summary, ensure_ascii=False)}
- Cluster deletion and pair deletion alter later order notionals, costs and compounding even though the Shadow FSM remains frozen.

## Interpretation limits

- Classification is a historical diagnostic label. Loose/Base/Strict thresholds were frozen before counterfactual execution and are never used by V3.1.
- Robust Redundant and Robust Harmful baskets are `EX_POST UPPER-BOUND DIAGNOSTIC`; their apparent improvement is hindsight-biased and is not implementable evidence.
- Forward 3/7/14/30/60/90-day BTC/ETH outcomes were attached only after simulations completed and never entered the execution engine.
- Only one realized 2020–2026 market path is observed. Path dependence, sequential research after V3.7/V3.8, selection bias and multiple comparisons limit external validity.
- Fees and frozen slippage are modeled; taxes, capacity, exchange failure and time-varying spread are not.
- No V3.1 rule, threshold, cooldown or live decision was modified. No V3.9 was created.
"""
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V31_NECESSITY_AUDIT.md").write_text(report, encoding="utf-8")
    (output_dir / "FINAL_REPORT_V31_NECESSITY_AUDIT.md").write_text(report, encoding="utf-8")


__all__ = ["create_necessity_figures", "write_necessity_report"]
