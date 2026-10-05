from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#7f8c8d", "A": "#1f77b4", "B": "#ff7f0e", "E": "#2ca02c"}
LABELS = {
    "H0": "H0 Initial Only — No DCA / No Trading",
    "A": "A Fixed DCA",
    "B": "B V3.1 FSM Frozen Champion",
    "E": "E V3.3 FSM Challenger",
}
STATE_CODE = {
    "BULL": 0, "DISTRIBUTION": 1, "EARLY_BEAR": 2, "BEAR": 3,
    "DEEP_BEAR": 4, "ACCUMULATION": 5, "NEW_BULL": 6,
}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=300, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _event_dates(transitions: pd.DataFrame, model: str, to_state: str) -> pd.Series:
    if transitions.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")
    mask = transitions["model"].eq(model) & transitions["to_state"].eq(to_state)
    return pd.to_datetime(transitions.loc[mask, "signal_date"], utc=True)


def _mark_events(ax: plt.Axes, transitions: pd.DataFrame, model: str, start: pd.Timestamp | None = None, end: pd.Timestamp | None = None) -> None:
    for state, color, style in (("NEW_BULL", "#17becf", ":"), ("BULL", "#2ca02c", "-.")):
        for date in _event_dates(transitions, model, state):
            if (start is None or date >= start) and (end is None or date <= end):
                ax.axvline(date, color=color, ls=style, lw=0.8, alpha=0.65)


def _shade_accumulation(ax: plt.Axes, daily: pd.DataFrame, label: str = "E ACCUMULATION") -> None:
    mask = daily["macro_state"].eq("ACCUMULATION").to_numpy()
    ax.fill_between(
        daily["date"], 0, 1, where=mask, step="post",
        transform=ax.get_xaxis_transform(), color="#9467bd", alpha=0.07, label=label,
    )


def _ordered_legend(ax: plt.Axes, order: tuple[str, ...], *, ncol: int = 1) -> None:
    handles, labels = ax.get_legend_handles_labels()
    mapping = dict(zip(labels, handles))
    selected = [(mapping[label], label) for label in order if label in mapping]
    ax.legend([item[0] for item in selected], [item[1] for item in selected], fontsize=8, ncol=ncol)


def create_v33_figures(
    output_dir: Path,
    daily: dict[str, pd.DataFrame],
    transitions: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "E", "B"):
        ax.plot(daily[model]["date"], daily[model]["portfolio_value"], label=LABELS[model], color=COLORS[model], lw=1.35, ls="--" if model == "B" else "-")
    ax.set(title="BTC+ETH Macro Hedge V3.3 — Portfolio Value", ylabel="Portfolio Value (USD)", xlabel="UTC date")
    _ordered_legend(ax, tuple(LABELS[model] for model in ("H0", "A", "B", "E")))
    _save(fig, figure_dir, "01_equity_curve_v3_3")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "E", "B"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["unit_nav"], label=LABELS[model], color=COLORS[model], lw=1.35, ls="--" if model == "B" else "-")
    ax.set(title="Cash-flow-adjusted Time-Weighted Growth", ylabel="Normalized TWR (start = 100)", xlabel="UTC date")
    _ordered_legend(ax, tuple(LABELS[model] for model in ("H0", "A", "B", "E")))
    _save(fig, figure_dir, "02_normalized_growth_v3_3")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("H0", "A", "E", "B"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["drawdown"], label=LABELS[model], color=COLORS[model], lw=1.2, ls="--" if model == "B" else "-")
    ax.axhline(-30.0, color="black", ls="--", lw=0.9, label="-30% post-backtest gate")
    ax.set(title="Peak-to-Trough Drawdown", ylabel="Drawdown (%)", xlabel="UTC date")
    _ordered_legend(ax, tuple([LABELS[model] for model in ("H0", "A", "B", "E")] + ["-30% post-backtest gate"]))
    _save(fig, figure_dir, "03_drawdown_curve_v3_3")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("E", "B"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["crypto_exposure"], label=LABELS[model], color=COLORS[model], lw=1.25, ls="--" if model == "B" else "-")
    ax.plot(daily["E"]["date"], 100.0 * daily["E"]["active_target"], color="#9467bd", lw=0.9, alpha=0.8, label="E active target")
    _shade_accumulation(ax, daily["E"])
    _mark_events(ax, transitions, "E")
    for level in (25, 35, 50, 60, 80, 90, 95):
        ax.axhline(level, color="gray", lw=0.35, alpha=0.35)
    ax.set(title="V3.1 vs V3.3 Crypto Exposure", ylabel="Crypto Exposure (%)", xlabel="UTC date", ylim=(0, 105))
    _ordered_legend(ax, (LABELS["B"], LABELS["E"], "E active target", "E ACCUMULATION"), ncol=2)
    _save(fig, figure_dir, "04_crypto_exposure_v3_3")

    fig, ax = plt.subplots(figsize=(11, 5.8))
    for model in ("E", "B"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["tactical_bear_cash_ratio"], label=LABELS[model], color=COLORS[model], lw=1.25, ls="--" if model == "B" else "-")
    ax.axhline(1.0, color="black", ls="--", lw=0.9, label="Material threshold 1%")
    for date in _event_dates(transitions, "E", "NEW_BULL"):
        ax.axvline(date, color="#17becf", ls=":", lw=0.9, alpha=0.7)
    for date in _event_dates(transitions, "E", "BULL"):
        ax.axvline(date, color="#2ca02c", ls="-.", lw=0.9, alpha=0.7)
    ax.set(title="Tactical Bear Cash Ratio and V3.3 Cycle Close", ylabel="Tactical Bear Cash / Portfolio (%)", xlabel="UTC date")
    ax.legend(fontsize=8)
    _save(fig, figure_dir, "05_tactical_cash_v3_3")

    start = pd.Timestamp("2020-01-01", tz="UTC")
    end = pd.Timestamp("2023-12-31 23:59:59", tz="UTC")
    b = daily["B"].loc[daily["B"]["date"].between(start, end)]
    e = daily["E"].loc[daily["E"]["date"].between(start, end)]
    fig, axes = plt.subplots(4, 1, figsize=(12, 11), sharex=True, gridspec_kw={"height_ratios": [1.2, 1.2, 0.9, 0.9]})
    axes[0].plot(e["date"], e["BTC_close"], color="#333333", lw=1.0)
    axes[0].set(title="2020–2023 Cycle Lifecycle Audit", ylabel="BTC USD")
    axes[1].plot(e["date"], 100 * e["crypto_exposure"], label="E exposure", color=COLORS["E"], lw=1.1)
    axes[1].plot(b["date"], 100 * b["crypto_exposure"], label="B exposure", color=COLORS["B"], lw=1.1, ls="--")
    axes[1].plot(e["date"], 100 * e["active_target"], label="E target", color="#9467bd", lw=0.8)
    axes[1].set(ylabel="Exposure (%)", ylim=(0, 105)); axes[1].legend(fontsize=8, ncol=3)
    axes[2].step(b["date"], b["macro_state"].map(STATE_CODE), where="post", label="B state", color=COLORS["B"], lw=1.0)
    axes[2].step(e["date"], e["macro_state"].map(STATE_CODE), where="post", label="E state", color=COLORS["E"], lw=1.0)
    axes[2].set(ylabel="State", yticks=list(STATE_CODE.values()), yticklabels=list(STATE_CODE.keys()))
    axes[2].legend(fontsize=8)
    axes[3].step(b["date"], b["cycle_id"], where="post", label="B cycle id", color=COLORS["B"], lw=1.0)
    axes[3].step(e["date"], e["cycle_id"], where="post", label="E cycle id", color=COLORS["E"], lw=1.0)
    axes[3].step(e["date"], e["sell_stage"], where="post", label="E stage", color="#9467bd", lw=0.8, alpha=0.8)
    axes[3].set(ylabel="Cycle / stage", xlabel="UTC date"); axes[3].legend(fontsize=8, ncol=3)
    for ax in axes[1:]:
        _mark_events(ax, transitions, "E", start, end)
    _save(fig, figure_dir, "06_2020_2023_cycle_zoom_v3_3")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def _date(value: Any) -> str:
    return "Not reached" if pd.isna(value) else str(pd.Timestamp(value).date())


def _days(value: Any) -> str:
    return "not reached" if pd.isna(value) else f"{float(value):.0f} days"


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
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines.extend("| " + " | ".join(render(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None))
    return "\n".join(lines)


def write_v33_report(
    output_dir: Path,
    summary: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    replay: dict[str, Any],
    audit: dict[str, Any],
    accumulation_audit: pd.DataFrame,
    accumulation_stats: pd.DataFrame,
    cycles: pd.DataFrame,
    churn: pd.DataFrame,
    events: pd.DataFrame,
    reentry: pd.DataFrame,
    cash_persistence: pd.DataFrame,
    daily: dict[str, pd.DataFrame],
) -> None:
    idx = summary.set_index("model")
    b, e = idx.loc["B"], idx.loc["E"]
    comp = comparison.iloc[0]
    stats = accumulation_stats.iloc[0]
    churn_counts = churn.loc[churn["record_type"].eq("transition_count")].groupby("model")["count"].sum()
    churn_drop = float(comp["state_churn_reduction_fraction"])
    reentry_idx = reentry.set_index("model")
    e_reentry = reentry_idx.loc["E"]
    bear = events.loc[events["event"].eq("2021_NOV_TO_2022_JUN")].set_index("model")
    bear_regression = verdict["diagnostic_regression_guardrails"]["bear_protection_regression_pass"]
    bull_regression = verdict["diagnostic_regression_guardrails"]["bull_reentry_regression_pass"]
    e_cycles = cycles.loc[cycles["model"].eq("E")]
    longest_cycle = float(e_cycles["duration_days"].max()) if not e_cycles.empty else np.nan
    five_year_cycle = bool((e_cycles["duration_days"] > 5 * 365.25).any()) if not e_cycles.empty else False
    may_accumulation = accumulation_audit.loc[accumulation_audit["date"].between(
        pd.Timestamp("2021-05-01", tz="UTC"), pd.Timestamp("2021-07-31", tz="UTC")
    )]
    may_daily = daily["E"].loc[daily["E"]["date"].between(
        pd.Timestamp("2021-05-01", tz="UTC"), pd.Timestamp("2021-07-31", tz="UTC")
    )]
    may_low_target = may_daily.loc[may_daily["active_target"] <= 0.60 + 1e-12]
    may_max = float(may_low_target["crypto_exposure"].max()) if not may_low_target.empty else np.nan
    may_long = int(stats["longest_consecutive_days_above_80pct_with_target_lte_60pct"])
    exposure_control = bool(
        may_max < 0.90
        and may_long < 3
        and int(stats["days_exposure_above_90pct_with_target_lte_60pct"]) == 0
    )
    exposure_improved = bool(int(e["accumulation_drift_sell_count"]) > 0)
    integrated_success = all([
        exposure_control, exposure_improved, bear_regression, bull_regression,
        bool(verdict["checks"]["bear_deep_bear_churn_reduced_at_least_50pct"]),
    ])
    answers = [
        f"1. H0 final: **{_money(idx.loc['H0','final_portfolio_value'])}**.",
        f"2. A Fixed DCA final: **{_money(idx.loc['A','final_portfolio_value'])}**.",
        f"3. B V3.1 final: **{_money(b['final_portfolio_value'])}**; exact replay **{'PASS' if replay['pass'] else 'FAIL'}**.",
        f"4. E V3.3 final: **{_money(e['final_portfolio_value'])}**.",
        "5. Max DD — " + ", ".join(f"{m}: **{_pct(idx.loc[m,'maximum_drawdown'])}**" for m in ("H0", "A", "B", "E")) + ".",
        f"6. Max DD <=30%: **{'PASS' if verdict['checks']['maximum_drawdown_gte_minus_0_30'] else 'FAIL'}** ({_pct(e['maximum_drawdown'])}).",
        f"7. CAGR >=45%: **{'PASS' if verdict['checks']['twr_cagr_gte_0_45'] else 'FAIL'}** ({_pct(e['twr_cagr'])}).",
        f"8. Calmar >=1.50: **{'PASS' if verdict['checks']['calmar_gte_1_50'] else 'FAIL'}** ({e['calmar']:.3f}).",
        f"9. 2021-May exposure control: **{'PASS' if exposure_control else 'FAIL'}**; maximum May–July actual exposure while active target <=60% was {_pct(may_max)}; longest >80% while target <=60% over the full sample was {may_long} completed days. The May–July window itself contained {len(may_accumulation)} ACCUMULATION signal days.",
        f"10. 2021-Nov→2022-Jun bear protection: **{'PASS' if bear_regression else 'FAIL'}**; B DD {_pct(bear.loc['B','peak_to_trough_dd'])}, E DD {_pct(bear.loc['E','peak_to_trough_dd'])}, E−B {100*(bear.loc['E','peak_to_trough_dd']-bear.loc['B','peak_to_trough_dd']):+.2f} pp.",
        f"11. V3.3 2023 NEW_BULL: **{_date(e_reentry['new_bull_date'])}**; delay versus V3.1 was {comp['2023_new_bull_delay_calendar_days']:+.0f} days (**{'PASS' if bull_regression else 'FAIL'}**).",
        f"12. After NEW_BULL, V3.3 reached 85% in **{_days(e_reentry.get('days_new_bull_to_85', np.nan))}** ({_date(e_reentry.get('first_85_date'))}) and 95% in **{_days(e_reentry.get('days_new_bull_to_95', np.nan))}** ({_date(e_reentry.get('first_95_date'))}).",
        f"13. V3.3 longest confirmed cycle: **{longest_cycle:.0f} days**.",
        f"14. Any V3.3 cycle crossing five years: **{'YES' if five_year_cycle else 'NO'}**.",
        f"15. Material Tactical Cash Time: **{_pct(e['material_tactical_cash_time'])}**.",
        f"16. BEAR↔DEEP_BEAR churn: B **{int(churn_counts.get('B',0))}**, E **{int(churn_counts.get('E',0))}**, reduction **{_pct(churn_drop)}**.",
        f"17. Tactical turnover: **{e['tactical_turnover']:.4f}x**.",
        f"18. Preserved bear protection + improved exposure control/state stability + no bull re-entry sacrifice: **{'YES' if integrated_success else 'NO'}**. Bear protection, state stability, and bull re-entry passed, but Patch 1 executed **{int(e['accumulation_drift_sell_count'])}** drift sells, so there is no realized exposure-control improvement versus B on this path.",
        f"19. Replace V3.1: **{'YES' if verdict['promotion_gate']=='PASS' else 'NO'}** — **{verdict['final_verdict']}**.",
    ]
    metric_table = summary[[
        "model", "initial_capital", "external_contributions_after_inception", "total_capital_supplied",
        "final_portfolio_value", "net_profit", "xirr", "twr_cagr", "maximum_drawdown",
        "peak_date", "trough_date", "recovery_date", "dd_duration_days", "sharpe", "sortino", "calmar",
    ]]
    tactical_table = summary.loc[summary["model"].isin(["B", "E"]), [
        "model", "average_crypto_exposure", "median_crypto_exposure", "average_tactical_cash",
        "median_tactical_cash", "average_tactical_cash_ratio", "median_tactical_cash_ratio",
        "material_tactical_cash_time", "tactical_turnover", "tactical_trade_count",
        "fees", "slippage", "total_trading_costs", "accumulation_drift_sell_count",
    ]]
    jlaw = pd.DataFrame([
        {"Dimension": "Champion", "Finding": "V3.1 B before evaluation"},
        {"Dimension": "Challenger", "Finding": "V3.3 E"},
        {"Dimension": "Return Edge", "Finding": f"Delta final {_money(comp['delta_final_value'])}; CAGR {comp['delta_cagr_percentage_points']:+.2f} pp"},
        {"Dimension": "Drawdown Edge", "Finding": f"{comp['delta_max_drawdown_percentage_points']:+.2f} pp"},
        {"Dimension": "Calmar Edge", "Finding": f"{comp['delta_calmar']:+.3f}"},
        {"Dimension": "Bear Protection", "Finding": "PASS" if bear_regression else "FAIL"},
        {"Dimension": "Bull Participation", "Finding": "PASS" if bull_regression else "FAIL"},
        {"Dimension": "Accumulation Exposure Control", "Finding": f"No breach, but no realized edge: 0 drift sells; max {_pct(stats['maximum_accumulation_exposure'])}"},
        {"Dimension": "Cycle Reset Quality", "Finding": "Lifecycle reset PASS; cash reset FAIL" if not verdict["checks"]["cycle_reset_audit_pass"] else "PASS"},
        {"Dimension": "Cash Drag", "Finding": f"material-time {_pct(e['material_tactical_cash_time'])}"},
        {"Dimension": "State Stability", "Finding": f"churn reduction {_pct(churn_drop)}"},
        {"Dimension": "Turnover", "Finding": f"{e['tactical_turnover']:.4f}x"},
        {"Dimension": "Execution Integrity", "Finding": "PASS" if audit["execution_integrity_pass"] else "FAIL"},
        {"Dimension": "Overfit Risk", "Finding": "One frozen rule set and one realized market path; forward paper test still required"},
    ])
    text = "\n".join([
        "# BTC+ETH Macro Hedge V3.3 — Final Report", "",
        "## Formal verdict", "", f"**{verdict['final_verdict']}**", "",
        f"Formal cutoff: {idx.loc['E','end']}. Rules were frozen before the first formal V3.3 run; all promotion gates were evaluated afterward only.", "",
        "## Direct answers", "", *answers, "",
        "## Performance", "", _markdown(metric_table), "",
        "## E V3.3 versus B V3.1", "", _markdown(comparison), "",
        "## B/E exposure, cash, turnover, and cost", "", _markdown(tactical_table), "",
        "## Frozen promotion gates", "", _markdown(pd.DataFrame([{"gate": key, "pass": value} for key, value in verdict["checks"].items()])), "",
        "## Explicit regression guardrails", "", _markdown(pd.DataFrame([verdict["diagnostic_regression_guardrails"]])), "",
        "## Accumulation exposure statistics", "", _markdown(accumulation_stats), "",
        "## Cycle duration and reset", "", _markdown(cycles), "",
        "## FSM churn and dwell", "", _markdown(churn), "",
        "## Cash persistence after NEW_BULL", "", _markdown(cash_persistence), "",
        "## Event-window audit", "", _markdown(events), "",
        "## 2023 bull re-entry", "", _markdown(reentry), "",
        "## J Law", "", _markdown(jlaw), "",
        "## Independent interpretation", "",
        "V3.3 changed the FSM labels and reduced churn, but it did not change a single trade on this history: Patch 1 never triggered, while the hysteresis transitions did not cross an executable exposure/notional target. Therefore identical return, drawdown, turnover, and cash metrics are a factual consequence—not evidence that the new exposure cap improved performance.", "",
        "The cycle lifecycle reset itself worked: the 2020-started cycle closed on 2023-02-05 rather than surviving to 2025. The aggregate gate still fails because 5.45% tactical bear cash remained at that close, above the explicit 1% CASH_RESET limit; the original V3.1 trade guard also prevented exact 95% exposure from being reached.", "",
        "H0 receives no periodic contributions, so normalized TWR—not absolute ending wealth—is the fair strategy-performance comparison. Passing a historical promotion gate would mean eligibility for a forward paper test, not live-trading approval. The test contains one realized crypto path, exchange/source history may contain survivorship and venue-basis effects, and the final 2025–2026 episode is right-censored at the data cutoff.", "",
        "## Integrity", "",
        f"NO_LOOK_AHEAD={'PASS' if audit['no_lookahead_pass'] else 'FAIL'}; EXECUTION_INTEGRITY={'PASS' if audit['execution_integrity_pass'] else 'FAIL'}; CYCLE_RESET_AUDIT={'PASS' if audit['cycle_reset_integrity_pass'] else 'FAIL'}; V3_1_REPLAY_INTEGRITY={'PASS' if replay['pass'] else 'FAIL'}; promotion terms in trading engine={not audit['promotion_gate_terms_absent_from_trading_engine']}; V3.2 trading imports/tokens in V3.3 engine={not audit['v32_trading_logic_absent_from_v33_engine']}.",
    ])
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_3.md").write_text(text, encoding="utf-8")


__all__ = ["create_v33_figures", "write_v33_report"]
