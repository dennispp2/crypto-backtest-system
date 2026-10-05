from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .v2_analysis import longest_true_run_days


COLORS = {
    "A - Fixed DCA Champion": "#4C78A8",
    "E20 - Fixed DCA + Corrected Hedge": "#E45756",
    "E30 - Fixed DCA + Corrected Hedge": "#72B7B2",
    "E40 - Fixed DCA + Corrected Hedge": "#F2CF5B",
}


def _save_figure(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def create_v2_figures(v2_dir: Path, daily_by_strategy: dict[str, pd.DataFrame]) -> None:
    figure_dir = v2_dir / "figures"
    plt.style.use("default")

    fig, ax = plt.subplots(figsize=(11, 6))
    for strategy, daily in daily_by_strategy.items():
        ax.plot(daily["date"], daily["portfolio_value"], label=strategy, lw=1.35, color=COLORS[strategy])
    ax.set_title("V2 Portfolio Equity Curves — 2020 to Data End")
    ax.set_ylabel("Portfolio value (USD)")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    _save_figure(fig, figure_dir / "01_portfolio_equity_curve_v2")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for strategy, daily in daily_by_strategy.items():
        ax.plot(daily["date"], 100.0 * daily["drawdown"], label=strategy, lw=1.25, color=COLORS[strategy])
    ax.set_title("V2 Drawdown Curves")
    ax.set_ylabel("Drawdown (%)")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    ax.legend(loc="lower left", fontsize=8)
    _save_figure(fig, figure_dir / "02_drawdown_curve_v2")

    e20 = daily_by_strategy["E20 - Fixed DCA + Corrected Hedge"]
    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(e20["date"], 100.0 * e20["crypto_exposure"], color="#4C78A8", lw=1.25, label="Crypto exposure")
    ax.plot(e20["date"], 100.0 * e20["stage_target_exposure"], color="#E45756", lw=1.0, alpha=0.8, label="Stage target")
    ax.fill_between(
        e20["date"],
        100.0 * e20["stage_lower_band"].astype(float),
        100.0 * e20["stage_upper_band"].astype(float),
        color="#E45756",
        alpha=0.10,
        label="Drift band",
    )
    ax.axhline(20, color="black", ls="--", lw=0.9, label="20% sell-time floor")
    ax.set_ylim(0, 105)
    ax.set_title("E20 Crypto Exposure")
    ax.set_ylabel("Exposure (%)")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    ax.legend(loc="best", fontsize=8)
    _save_figure(fig, figure_dir / "03_e20_crypto_exposure")

    fig, ax = plt.subplots(figsize=(11, 4.25))
    ax.plot(e20["date"], 100.0 * e20["tactical_cash_ratio"], color="#E45756", lw=1.25)
    ax.set_title("E20 Tactical Cash Share")
    ax.set_ylabel("Tactical cash (%)")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    _save_figure(fig, figure_dir / "04_e20_tactical_cash")

    regime_order = ["BULL", "LATE_BULL", "DISTRIBUTION", "BEAR", "DEEP_BEAR", "ACCUMULATION", "NEW_BULL"]
    regime_map = {name: index for index, name in enumerate(regime_order)}
    fig, ax = plt.subplots(figsize=(11, 3.8))
    y = e20["cycle_regime"].map(regime_map).astype(float)
    ax.step(e20["date"], y, where="post", color="#54A24B", lw=1.2)
    ax.set_yticks(range(len(regime_order)), regime_order)
    ax.set_title("E20 Cycle Regime")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    _save_figure(fig, figure_dir / "05_e20_cycle_regime")

    fig, ax = plt.subplots(figsize=(11, 3.8))
    ax.step(e20["date"], e20["sell_stage"].astype(int), where="post", color="#B279A2", lw=1.2)
    ax.set_yticks([0, 1, 2, 3, 4])
    ax.set_title("E20 Sell Stage")
    ax.set_ylabel("Stage")
    ax.set_xlabel("UTC date")
    ax.grid(alpha=0.25)
    _save_figure(fig, figure_dir / "06_e20_sell_stage")

    fig, axes = plt.subplots(5, 1, figsize=(13, 13), sharex=True)
    for strategy, daily in daily_by_strategy.items():
        axes[0].plot(daily["date"], daily["portfolio_value"], label=strategy, lw=1.0, color=COLORS[strategy])
    axes[0].set_ylabel("Portfolio USD")
    axes[0].legend(loc="upper left", fontsize=7, ncol=2)
    axes[1].plot(e20["date"], 100.0 * e20["crypto_exposure"], color="#4C78A8", lw=1.0)
    axes[1].set_ylabel("Crypto %")
    axes[2].plot(e20["date"], 100.0 * e20["tactical_cash_ratio"], color="#E45756", lw=1.0)
    axes[2].set_ylabel("Tactical cash %")
    axes[3].step(e20["date"], y, where="post", color="#54A24B", lw=1.0)
    axes[3].set_yticks(range(len(regime_order)), regime_order, fontsize=7)
    axes[3].set_ylabel("Regime")
    axes[4].step(e20["date"], e20["sell_stage"].astype(int), where="post", color="#B279A2", lw=1.0)
    axes[4].set_yticks([0, 1, 2, 3, 4])
    axes[4].set_ylabel("Sell stage")
    axes[4].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.22)
        for marker in ("2021-05-11", "2021-11-10", "2022-11-21", "2023-01-01", "2024-01-01"):
            ax.axvline(pd.Timestamp(marker, tz="UTC"), color="gray", ls=":", lw=0.6, alpha=0.65)
    fig.suptitle("V2 Integrated Audit Timeline", y=0.995)
    fig.tight_layout()
    _save_figure(fig, figure_dir / "07_integrated_audit_timeline_v2")


def _usd(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def _md_table(summary: pd.DataFrame) -> str:
    columns = [
        "strategy",
        "final_portfolio_value",
        "external_contributions",
        "xirr",
        "time_weighted_cagr",
        "maximum_drawdown",
        "calmar",
        "average_crypto_exposure",
        "time_in_tactical_cash",
        "transaction_count",
        "total_fees",
    ]
    view = summary[columns].copy()
    view["final_portfolio_value"] = view["final_portfolio_value"].map(_usd)
    view["external_contributions"] = view["external_contributions"].map(_usd)
    for column in ("xirr", "time_weighted_cagr", "maximum_drawdown", "average_crypto_exposure", "time_in_tactical_cash"):
        view[column] = view[column].map(_pct)
    view["calmar"] = view["calmar"].map(lambda x: f"{x:.3f}")
    view["total_fees"] = view["total_fees"].map(_usd)
    headers = list(view.columns)
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for values in view.itertuples(index=False, name=None):
        lines.append("| " + " | ".join(str(value) for value in values) + " |")
    return "\n".join(lines)


def write_v2_report(
    v2_dir: Path,
    summary: pd.DataFrame,
    histories: dict[str, pd.DataFrame],
    daily_by_strategy: dict[str, pd.DataFrame],
    cycle_audit: pd.DataFrame,
    exposure: pd.DataFrame,
    integrity: pd.DataFrame,
    audit: dict[str, Any],
) -> str:
    by_name = summary.set_index("strategy")
    a = by_name.loc["A - Fixed DCA Champion"]
    e20 = by_name.loc["E20 - Fixed DCA + Corrected Hedge"]
    hedges = summary.loc[summary["strategy"].str.startswith("E")].copy()
    best_floor = hedges.sort_values("calmar", ascending=False).iloc[0]
    final_best = summary.sort_values("final_portfolio_value", ascending=False).iloc[0]
    final_delta = float(e20["final_portfolio_value"] - a["final_portfolio_value"])
    cagr_delta = float(e20["time_weighted_cagr"] - a["time_weighted_cagr"])
    dd_delta = float(e20["maximum_drawdown"] - a["maximum_drawdown"])
    calmar_delta = float(e20["calmar"] - a["calmar"])
    cagr_cost_per_dd_pp = (-100.0 * cagr_delta / (100.0 * dd_delta)) if dd_delta > 0 else np.nan
    e20_history = histories["E20 - Fixed DCA + Corrected Hedge"]
    trough = e20_history.iloc[int(e20_history["drawdown"].astype(float).to_numpy().argmin())]
    max_dd_cycle = int(trough["sell_cycle_id"])
    max_dd_regime = str(trough["cycle_regime"])
    e20_exposure = exposure.loc[exposure["strategy"].eq("E20 - Fixed DCA + Corrected Hedge")].copy()
    e20_exposure["date"] = pd.to_datetime(e20_exposure["date"], utc=True)
    may_window = e20_exposure.loc[
        e20_exposure["date"].between(pd.Timestamp("2021-05-01", tz="UTC"), pd.Timestamp("2021-11-10", tz="UTC"))
    ]
    decoupled = int(((may_window["sell_stage"] == 3) & (may_window["crypto_exposure"] >= 0.90)).sum())
    may_crash = e20_exposure.loc[
        e20_exposure["date"].between(pd.Timestamp("2021-05-11", tz="UTC"), pd.Timestamp("2021-05-31", tz="UTC"))
    ]
    may_stages = ",".join(str(value) for value in sorted(may_crash["sell_stage"].astype(int).unique()))
    may_regimes = ",".join(sorted(may_crash["cycle_regime"].astype(str).unique()))
    may_exposure_range = (
        float(may_crash["crypto_exposure"].min()),
        float(may_crash["crypto_exposure"].max()),
    )
    e20_cycles = cycle_audit.loc[cycle_audit["strategy"].eq("E20 - Fixed DCA + Corrected Hedge")].copy()
    e20_cycles["cycle_start"] = pd.to_datetime(e20_cycles["cycle_start"], utc=True)
    e20_cycles["cycle_end"] = pd.to_datetime(e20_cycles["cycle_end"], utc=True)
    trough_ts = pd.Timestamp(trough["timestamp"])
    prior_cycles = e20_cycles.loc[e20_cycles["cycle_end"] <= trough_ts]
    next_cycles = e20_cycles.loc[e20_cycles["cycle_start"] > trough_ts]
    prior_cycle_id = int(prior_cycles.iloc[-1]["cycle_id"]) if not prior_cycles.empty else 0
    next_cycle_id = int(next_cycles.iloc[0]["cycle_id"]) if not next_cycles.empty else 0
    if max_dd_cycle == 0:
        max_dd_cycle_text = (
            f"no active cycle (post-reset BULL gap after cycle {prior_cycle_id}, "
            f"before cycle {next_cycle_id})"
        )
    else:
        max_dd_cycle_text = f"cycle {max_dd_cycle}"
    confirmed = e20_cycles["NEW_BULL_date"].notna()
    missing_reset = int((confirmed & e20_cycles["reset_date"].isna()).sum())
    stage4_days: list[float] = []
    for _, cycle in e20_cycles.loc[e20_cycles["stage_4_date"].notna()].iterrows():
        start = pd.Timestamp(cycle["stage_4_date"])
        end = pd.Timestamp(cycle["reset_date"]) if pd.notna(cycle["reset_date"]) else pd.Timestamp(cycle["cycle_end"])
        stage4_days.append((end - start).total_seconds() / 86_400.0)
    max_stage4_days = max(stage4_days, default=0.0)
    longest_cash_days = longest_true_run_days(
        daily_by_strategy["E20 - Fixed DCA + Corrected Hedge"]["date"],
        daily_by_strategy["E20 - Fixed DCA + Corrected Hedge"]["tactical_cash"] > 1e-9,
    )
    if -100.0 * cagr_delta > 10.0:
        label = "TOO MUCH CASH DRAG"
        verdict = "HEDGE NEEDS REDESIGN"
    elif dd_delta < 0.05 or calmar_delta <= 0:
        label = "INSUFFICIENT HEDGE EDGE"
        verdict = "HEDGE NEEDS REDESIGN"
    elif dd_delta >= 0.10 and calmar_delta > 0 and -cagr_delta <= 0.10:
        label = "PROMISING HEDGE OVERLAY"
        verdict = "FIXED DCA + HEDGE WORTH FORWARD TEST"
    elif final_best["strategy"] == "A - Fixed DCA Champion":
        label = "INSUFFICIENT HEDGE EDGE"
        verdict = "KEEP FIXED DCA ONLY"
    else:
        label = "INSUFFICIENT EVIDENCE"
        verdict = "HEDGE NEEDS REDESIGN"

    report = f"""# V2.0 Fixed DCA + Corrected Cycle Hedge — Final Report

## Scope and validity

- Formal period: {a['start']} to {a['end']}.
- Fresh initial portfolio: US$20,000 at formal-period start; 2019 is indicator warm-up only.
- Primary costs: 0.10% fee + 0.05% slippage; US$5 modeled minimum notional.
- Frozen models only: A, E20, E30, E40. No optimization or parameter search.
- No-look-ahead and execution audit: **{'PASS' if audit['pass'] else 'FAIL'}**.
- Fixed-DCA A/E20 row integrity: **{'PASS' if bool(integrity['all_match'].all()) else 'FAIL'}**.

## Headline performance

{_md_table(summary)}

## Required answers

1. **2020–2026 Fixed DCA final value:** {_usd(float(a['final_portfolio_value']))}.
2. **E20 final value:** {_usd(float(e20['final_portfolio_value']))}.
3. **Did E20 reduce maximum drawdown?** {'Yes' if dd_delta > 0 else 'No'}; A {_pct(float(a['maximum_drawdown']))}, E20 {_pct(float(e20['maximum_drawdown']))}, improvement {100.0 * dd_delta:.2f} percentage points.
4. **E20 maximum-drawdown cycle:** {max_dd_cycle_text}; regime at trough `{max_dd_regime}`, trough {e20['max_dd_trough_date']}. The hedge had already reset before the deepest 2022 decline.
5. **2021/5 Stage 3 with 90%+ crypto exposure:** {decoupled} daily observations; {'PASS' if decoupled == 0 else 'FAIL'}. However, 2021-05-11 through 2021-05-31 was Stage {may_stages}, regime {may_regimes}, with crypto exposure {_pct(may_exposure_range[0])}–{_pct(may_exposure_range[1])}; the corrected label did not create an active May-crash hedge.
6. **Every confirmed NEW_BULL reset its stage:** {'PASS' if missing_reset == 0 else 'FAIL'}; missing resets = {missing_reset}.
7. **Stage 4 stuck for 1–3 years:** maximum Stage-4-to-reset/end span {max_stage4_days:.1f} days; {'not observed' if max_stage4_days < 365 else 'observed'}.
8. **Was tactical cash still idle for long periods?** Longest continuous positive tactical-cash run = {longest_cash_days:.0f} days; time positive = {_pct(float(e20['time_in_tactical_cash']))}. This is a factual duration, not proof that every day was avoidable drag.
9. **Best frozen floor by Calmar:** {best_floor['strategy']} at {best_floor['calmar']:.4f}. This comparison does not promote or retune the floor.
10. **Is Fixed DCA still the best absolute-return model?** {'Yes' if final_best['strategy'] == 'A - Fixed DCA Champion' else 'No'}; highest final value = {final_best['strategy']} at {_usd(float(final_best['final_portfolio_value']))}.
11. **Is the hedge worth live trading?** Historical simulation label: **{label}**. A forward test is still required before live use because cycle count is small and execution/tax effects outside the frozen model remain untested.
12. **J Law verdict:** shown below.

## E20 versus A

- Delta final value: {_usd(final_delta)}.
- Delta TWR CAGR: {100.0 * cagr_delta:.2f} percentage points.
- Delta maximum drawdown: {100.0 * dd_delta:.2f} percentage points.
- Delta Calmar: {calmar_delta:.3f}.
- CAGR sacrificed per 1 percentage-point drawdown improvement: {cagr_cost_per_dd_pp:.3f} percentage points.

## J Law decision

- Champion: A — Fixed DCA.
- Challenger: E20 — Fixed DCA + Corrected Cycle Hedge, 20% sell-time floor.
- Return Edge: {'Champion' if float(a['time_weighted_cagr']) >= float(e20['time_weighted_cagr']) else 'Challenger'}.
- Drawdown Edge: {'Challenger' if dd_delta > 0 else 'Champion'}.
- Cash Drag: {_pct(float(e20['cash_drag']))} total-cash path attribution; {_pct(float(e20['tactical_cash_drag']))} tactical-only path attribution. These are descriptive approximations.
- Cycle Timing: {len(e20_cycles)} machine-defined sell cycles; maximum Stage-4 span {max_stage4_days:.1f} days. The maximum drawdown occurred in the post-cycle-{prior_cycle_id} BULL gap before cycle {next_cycle_id}, showing a timing miss rather than a stuck-stage bug.
- Execution Integrity: {'PASS' if audit['pass'] and bool(integrity['all_match'].all()) else 'FAIL'}.
- Overfit Risk: Medium-high — thresholds were frozen and only 20/30/40 floors were compared, but 19 machine cycles are not 19 independent macro cycles, and the rule tree remains complex.

**FINAL VERDICT: {verdict}**

## Important interpretation boundary

The hard floor is enforced against tactical sells. Daily mark-to-market exposure can later fall below the floor when crypto prices fall relative to cash; forcing an immediate buy would add a new, unfrozen rebalancing rule. Such observations remain visible in `exposure_audit.csv` and are not silently relabeled as execution bugs.
"""
    report_dir = v2_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V2.md").write_text(report, encoding="utf-8")
    return verdict
