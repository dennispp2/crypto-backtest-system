from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#7f8c8d", "A": "#1f77b4", "B": "#ff7f0e", "D": "#2ca02c"}
LABELS = {
    "H0": "H0 Initial Only — No DCA / No Trading",
    "A": "A Fixed DCA",
    "B": "B V3.1 FSM",
    "D": "D V3.2 FSM",
}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def create_v32_figures(
    output_dir: Path, daily: dict[str, pd.DataFrame],
    signals: dict[str, pd.DataFrame], cycles: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "B", "D"):
        ax.plot(daily[model]["date"], daily[model]["portfolio_value"], label=LABELS[model], color=COLORS[model], lw=1.4)
    ax.set(title="BTC+ETH V3.2 — Portfolio Value", ylabel="Portfolio Value (USD)", xlabel="UTC date")
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "01_equity_curve_v3_2")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "B", "D"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["unit_nav"], label=LABELS[model], color=COLORS[model], lw=1.4)
    ax.set(title="Cash-flow-adjusted Time-Weighted Growth", ylabel="Normalized TWR (start = 100)", xlabel="UTC date")
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "02_normalized_growth_v3_2")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "B", "D"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["drawdown"], label=LABELS[model], color=COLORS[model], lw=1.2)
    ax.axhline(-30.0, color="black", ls="--", lw=0.9, label="-30% evaluation gate")
    ax.set(title="Peak-to-Trough Drawdown", ylabel="Drawdown (%)", xlabel="UTC date")
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "03_drawdown_curve_v3_2")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("B", "D"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["crypto_exposure"], label=LABELS[model], color=COLORS[model], lw=1.3)
    for level in (25, 35, 50, 60, 85, 95):
        ax.axhline(level, color="gray", lw=0.4, alpha=0.45)
    ax.set(title="V3.1 vs V3.2 Crypto Exposure", ylabel="Crypto Exposure (%)", xlabel="UTC date", ylim=(0, 105))
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "04_crypto_exposure_v3_2")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("B", "D"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["tactical_cash_ratio"], label=LABELS[model], color=COLORS[model], lw=1.3)
    ax.axhline(1.0, color="black", ls="--", lw=0.9, label="Material threshold 1%")
    ax.set(title="Tactical Bear Cash Ratio", ylabel="Tactical Cash / Portfolio (%)", xlabel="UTC date")
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "05_tactical_cash_v3_2")

    start, end = pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2022-12-31 23:59:59", tz="UTC")
    b = daily["B"].loc[daily["B"]["date"].between(start, end)]
    d = daily["D"].loc[daily["D"]["date"].between(start, end)]
    fig, axes = plt.subplots(3, 1, figsize=(11, 8.5), sharex=True)
    axes[0].plot(d["date"], d["BTC_close"], color="#333333", lw=1.1)
    axes[0].set_ylabel("BTC USD")
    axes[0].set_title("2021–2022 Bear-market Zoom")
    axes[1].plot(b["date"], 100*b["crypto_exposure"], label="B exposure", color=COLORS["B"])
    axes[1].plot(d["date"], 100*d["crypto_exposure"], label="D exposure", color=COLORS["D"])
    axes[1].set_ylabel("Exposure (%)"); axes[1].legend(fontsize=8)
    axes[2].step(b["date"], b["sell_stage"], where="post", label="B stage", color=COLORS["B"])
    axes[2].step(d["date"], d["sell_stage"], where="post", label="D stage", color=COLORS["D"])
    axes[2].set(ylabel="Stage", xlabel="UTC date", yticks=[0, 1, 2, 3, 4]); axes[2].legend(fontsize=8)
    _save(fig, figure_dir, "06_2021_2022_zoom_v3_2")

    start, end = pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-12-31 23:59:59", tz="UTC")
    b = daily["B"].loc[daily["B"]["date"].between(start, end)]
    d = daily["D"].loc[daily["D"]["date"].between(start, end)]
    fig, axes = plt.subplots(3, 1, figsize=(11, 9), sharex=True)
    axes[0].plot(d["date"], d["BTC_close"], color="#333333", lw=1.0)
    axes[0].set(title="2023–2025 Bull Re-entry", ylabel="BTC USD")
    axes[1].plot(b["date"], b["portfolio_value"], label="B portfolio", color=COLORS["B"])
    axes[1].plot(d["date"], d["portfolio_value"], label="D portfolio", color=COLORS["D"])
    axes[1].set_ylabel("Portfolio USD"); axes[1].legend(fontsize=8)
    axes[2].plot(b["date"], 100*b["crypto_exposure"], label="B exposure", color=COLORS["B"])
    axes[2].plot(d["date"], 100*d["crypto_exposure"], label="D exposure", color=COLORS["D"])
    d_signals = signals["D"]
    recovery_dates = pd.to_datetime(
        d_signals.loc[d_signals["actions"].str.contains("BULL_RECOVERY_GATE", na=False), "signal_date"], utc=True
    )
    new_bull_dates = pd.to_datetime(
        d_signals.loc[d_signals["actions"].str.contains("V32_NEW_BULL_CONFIRMED", na=False), "signal_date"], utc=True
    )
    for date in recovery_dates:
        if start <= date <= end:
            axes[2].axvline(date, color="#9467bd", ls="--", lw=1.0, label="BULL_RECOVERY_GATE")
    for date in new_bull_dates:
        if start <= date <= end:
            axes[2].axvline(date, color="#17becf", ls=":", lw=1.2, label="NEW_BULL")
    handles, labels = axes[2].get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    axes[2].legend(unique.values(), unique.keys(), fontsize=8)
    axes[2].set(ylabel="Exposure (%)", xlabel="UTC date", ylim=(0, 105))
    _save(fig, figure_dir, "07_2023_2025_bull_reentry_v3_2")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def _date(value: Any) -> str:
    return "Not recovered" if pd.isna(value) else str(pd.Timestamp(value).date())


def _markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    def render(value: Any) -> str:
        if pd.isna(value):
            return ""
        if isinstance(value, (float, np.floating)):
            return f"{float(value):.6g}"
        return str(value).replace("|", "\\|").replace("\n", " ")

    headers = [str(column) for column in frame.columns]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(render(value) for value in row) + " |"
        for row in frame.itertuples(index=False, name=None)
    )
    return "\n".join(lines)


def write_v32_report(
    output_dir: Path, summary: pd.DataFrame, comparison: pd.DataFrame,
    verdict: dict[str, Any], replay: dict[str, Any], audit: dict[str, Any],
    events: pd.DataFrame, churn: pd.DataFrame, cycles: pd.DataFrame,
    reentry: pd.DataFrame,
) -> None:
    idx = summary.set_index("model")
    b, d = idx.loc["B"], idx.loc["D"]
    comp = comparison.iloc[0]
    stage_b = cycles.loc[(cycles["model"] == "B") & pd.to_datetime(cycles["start"], utc=True).between(
        pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC")
    ), "stage4_date"]
    stage_d = cycles.loc[(cycles["model"] == "D") & pd.to_datetime(cycles["start"], utc=True).between(
        pd.Timestamp("2020-01-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC")
    ), "stage4_date"]
    b_stage4 = pd.to_datetime(stage_b, utc=True, errors="coerce").dropna().max() if not stage_b.empty else pd.NaT
    d_stage4 = pd.to_datetime(stage_d, utc=True, errors="coerce").dropna().max() if not stage_d.empty else pd.NaT
    event_name = "2021_NOV_TO_2022_JUN"
    bear = events.loc[events["event"].eq(event_name)].set_index("model")
    d_2022_min = float(events.loc[
        events["event"].eq("2021_NOV_TO_2022_JUN") & events["model"].eq("D"), "minimum_crypto_exposure"
    ].iloc[0])
    churn_counts = churn.loc[churn["record_type"].eq("transition_count")].groupby("model")["count"].sum()
    churn_drop = 1.0 - float(churn_counts.get("D", 0)) / float(churn_counts.get("B", 1))
    d_reentry = reentry.loc[reentry["model"].eq("D")].copy()
    reentry_text = "No V3.2 NEW_BULL event."
    if not d_reentry.empty:
        latest = d_reentry.iloc[-1]
        def days_text(value: Any) -> str:
            return "not reached" if pd.isna(value) else f"{float(value):.1f} days"
        reentry_text = (
            f"60%: {days_text(latest['days_recovery_to_60'])}; "
            f"85%: {days_text(latest['days_recovery_to_85'])}; "
            f"95%: {days_text(latest['days_recovery_to_95'])}."
        )
    b_post_2023 = reentry.loc[
        reentry["model"].eq("B") & (pd.to_datetime(reentry["new_bull_date"], utc=True) >= pd.Timestamp("2023-01-01", tz="UTC"))
    ]
    d_post_2023 = reentry.loc[
        reentry["model"].eq("D") & (pd.to_datetime(reentry["new_bull_date"], utc=True) >= pd.Timestamp("2023-01-01", tz="UTC"))
    ]
    faster_reentry = bool(
        not b_post_2023.empty and not d_post_2023.empty
        and pd.Timestamp(d_post_2023.iloc[0]["new_bull_date"]) < pd.Timestamp(b_post_2023.iloc[0]["new_bull_date"])
    )
    d_cycle_duration = 0.0
    d_confirmed = cycles.loc[(cycles["model"] == "D") & cycles["confirmed"].astype(bool)].copy()
    if not d_confirmed.empty:
        d_cycle_duration = float((
            pd.to_datetime(d_confirmed["end"], utc=True) - pd.to_datetime(d_confirmed["start"], utc=True)
        ).dt.total_seconds().div(86400.0).max())
    answers = [
        f"1. H0 final value: **{_money(idx.loc['H0','final_portfolio_value'])}**.",
        f"2. A Fixed DCA final value: **{_money(idx.loc['A','final_portfolio_value'])}**.",
        f"3. B V3.1 final value: **{_money(b['final_portfolio_value'])}**; frozen replay integrity **{'PASS' if replay['pass'] else 'FAIL'}**.",
        f"4. D V3.2 final value: **{_money(d['final_portfolio_value'])}**.",
        "5. Max DD — " + ", ".join(f"{m}: **{_pct(idx.loc[m,'maximum_drawdown'])}**" for m in ("H0","A","B","D")) + ".",
        f"6. V3.2 Max DD >= -30%: **{'PASS' if verdict['checks']['maximum_drawdown_gte_minus_0_30'] else 'FAIL'}** ({_pct(d['maximum_drawdown'])}).",
        f"7. V3.2 CAGR >=45%: **{'PASS' if verdict['checks']['twr_cagr_gte_0_45'] else 'FAIL'}** ({_pct(d['twr_cagr'])}).",
        f"8. V3.2 Calmar >=1.50: **{'PASS' if verdict['checks']['calmar_gte_1_50'] else 'FAIL'}** ({d['calmar']:.3f}).",
        f"9. After 2021/11, Stage4 was not meaningfully earlier: **NO**—both governing cycles had already recorded Stage4 (B: **{_date(b_stage4)}**, D: **{_date(d_stage4)}**), but D had subsequently bought back above its 25% Stage4 target.",
        f"10. 2021-Nov→2022-Jun event DD change D vs B: **{100*(float(bear.loc['D','event_drawdown'])-float(bear.loc['B','event_drawdown'])):+.2f} pp**; this is a **deterioration**, not an improvement. D minimum exposure was {_pct(d_2022_min)}.",
        f"11. 2023–2025 V3.2 recovered exposure faster than V3.1: **{'YES' if faster_reentry else 'NO'}**. B confirmed NEW_BULL in 2023, while D did not trigger Bull Recovery until 2025. D's eventual event: {reentry_text}",
        f"12. V3.2 average exposure in BULL/NEW_BULL states: **{_pct(d['fsm_bull_average_crypto_exposure'])}**; fixed 2023–2025 window: **{_pct(d['calendar_2023_2025_average_crypto_exposure'])}**.",
        f"13. Material Tactical Cash Time change: **{comp['delta_material_tactical_cash_time_percentage_points']:+.2f} pp** (B {_pct(b['material_tactical_cash_time'])} → D {_pct(d['material_tactical_cash_time'])}).",
        f"14. BEAR↔DEEP_BEAR churn: B **{int(churn_counts.get('B',0))}**, D **{int(churn_counts.get('D',0))}**, reduction **{_pct(churn_drop)}**.",
        f"15. V3.2 tactical turnover: **{d['tactical_turnover']:.4f}x**.",
        f"16. Less bear loss plus stronger bull holding: **{'YES' if d['maximum_drawdown'] > b['maximum_drawdown'] and d['calendar_2023_2025_average_crypto_exposure'] > b['calendar_2023_2025_average_crypto_exposure'] else 'NO'}**.",
        f"17. Replace V3.1 in forward paper test: **{'YES' if verdict['promotion_gate']=='PASS' else 'NO'}**.",
        f"18. J Law Final Verdict: **{verdict['final_verdict']}**.",
    ]
    metric_table = summary[[
        "model", "initial_capital", "external_contributions_after_inception", "total_capital_supplied",
        "final_portfolio_value", "net_profit", "xirr", "twr_cagr", "maximum_drawdown",
        "peak_date", "trough_date", "recovery_date", "sharpe", "sortino", "calmar",
    ]].copy()
    tactical_table = summary.loc[summary["model"].isin(["B", "D"]), [
        "model", "average_crypto_exposure", "median_crypto_exposure",
        "average_tactical_cash", "median_tactical_cash", "average_tactical_cash_ratio",
        "median_tactical_cash_ratio", "material_tactical_cash_time", "tactical_turnover",
        "tactical_trade_count", "tactical_event_count", "fees", "slippage", "total_trading_costs",
    ]].copy()
    jlaw = pd.DataFrame([
        {"Dimension": "Champion", "Finding": "V3.1 B before evaluation"},
        {"Dimension": "Challenger", "Finding": "V3.2 D"},
        {"Dimension": "Return Edge", "Finding": f"Delta final {_money(comp['delta_final_value'])}; delta CAGR {comp['delta_cagr_percentage_points']:+.2f} pp"},
        {"Dimension": "Drawdown Edge", "Finding": f"{comp['delta_max_drawdown_percentage_points']:+.2f} pp"},
        {"Dimension": "Calmar Edge", "Finding": f"{comp['delta_calmar']:+.3f}"},
        {"Dimension": "Bear Protection", "Finding": _pct(d["maximum_drawdown"])},
        {"Dimension": "Bull Participation", "Finding": _pct(d["fsm_bull_average_crypto_exposure"])},
        {"Dimension": "Cash Drag", "Finding": f"material-time delta {comp['delta_material_tactical_cash_time_percentage_points']:+.2f} pp"},
        {"Dimension": "State Stability", "Finding": f"churn reduction {_pct(churn_drop)}"},
        {"Dimension": "Turnover", "Finding": f"{d['tactical_turnover']:.4f}x"},
        {"Dimension": "Execution Integrity", "Finding": "PASS" if audit["pass"] else "FAIL"},
        {"Dimension": "Overfit Risk", "Finding": "One frozen specification; single historical path remains a limitation"},
    ])
    text = "\n".join([
        "# BTC+ETH Macro Hedge V3.2 — Final Report", "",
        "## Formal result", "",
        f"**{verdict['final_verdict']}**", "",
        f"Formal cutoff: {idx.loc['D','end']}. Rules were frozen before the V3.2 formal run; promotion thresholds were evaluated only afterward.", "",
        "## Direct answers", "", *answers, "",
        "## Performance table", "", _markdown(metric_table), "",
        "## D versus B", "", _markdown(comparison), "",
        "## B/D exposure, cash, turnover and costs", "", _markdown(tactical_table), "",
        "## Frozen promotion gates", "",
        _markdown(pd.DataFrame([{"gate": key, "pass": value} for key, value in verdict["checks"].items()])), "",
        "## Material diagnostics", "",
        f"- V3.2's longest confirmed macro cycle lasted **{d_cycle_duration:.0f} days**. The 2020 cycle did not close until the 2025 recovery, which fails the design intent that an old cycle must not remain open for years after a genuine bull market.",
        f"- Material tactical-cash time increased from **{_pct(b['material_tactical_cash_time'])}** to **{_pct(d['material_tactical_cash_time'])}**; the cash-drag problem was not solved.",
        "- Stage number is historical cycle progress, not current target exposure. During ACCUMULATION, D may retain Stage 4 while its active target is 35%, 50%, or 60%; the zoom must be read together with the exposure line.", "",
        "## Stability events", "", _markdown(events), "",
        "## FSM churn and dwell", "", _markdown(churn), "",
        "## Bull re-entry", "", _markdown(reentry), "",
        "## Cycle audit", "", _markdown(cycles), "",
        "## J Law", "", _markdown(jlaw), "",
        "## Independent interpretation", "",
        "Promotion means eligibility for forward paper testing, not live-trading approval. H0 has no periodic contributions, so normalized TWR—not absolute ending wealth—is the fair strategy-performance comparison. The sample contains only one realized crypto history, and the 2025–2026 event window is right-censored at the data cutoff.", "",
        "## Integrity", "",
        f"NO_LOOK_AHEAD={'PASS' if audit['pass'] else 'FAIL'}; V3_1_ROW_INTEGRITY={'PASS' if replay['pass'] else 'FAIL'}; promotion rules present in trading engine={not audit['promotion_gate_terms_absent_from_trading_engine']}.",
    ])
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_2.md").write_text(text, encoding="utf-8")
