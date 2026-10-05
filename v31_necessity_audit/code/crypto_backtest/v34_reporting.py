from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#6b7280", "A": "#2563eb", "B": "#dc2626", "F": "#059669"}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=320, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _event_dates(signals: pd.DataFrame, token: str) -> pd.Series:
    if signals.empty:
        return pd.Series(dtype="datetime64[ns, UTC]")
    return pd.to_datetime(
        signals.loc[signals["actions"].str.contains(token, regex=False, na=False), "signal_date"],
        utc=True,
    )


def create_v34_figures(
    output_dir: Path,
    daily_by_model: dict[str, pd.DataFrame],
    result_b: Any,
    result_f: Any,
) -> None:
    figure_dir = output_dir / "figures"

    fig, ax = plt.subplots(figsize=(11, 6))
    for model in ("H0", "A", "B", "F"):
        d = daily_by_model[model]
        ax.plot(d["date"], d["portfolio_value"], label=model, color=COLORS[model], lw=1.5)
    ax.set(title="V3.4 absolute portfolio value", ylabel="USD", xlabel="UTC date")
    ax.grid(alpha=0.2)
    ax.legend(ncol=4)
    _save(fig, figure_dir, "01_equity_curve_v3_4")

    fig, ax = plt.subplots(figsize=(11, 6))
    for model in ("H0", "A", "B", "F"):
        d = daily_by_model[model]
        ax.plot(d["date"], 100.0 * d["unit_nav"], label=model, color=COLORS[model], lw=1.5)
    ax.set(title="Cash-flow-adjusted time-weighted growth (start = 100)", ylabel="TWR index", xlabel="UTC date")
    ax.grid(alpha=0.2)
    ax.legend(ncol=4)
    _save(fig, figure_dir, "02_normalized_growth_v3_4")

    fig, ax = plt.subplots(figsize=(11, 6))
    for model in ("H0", "A", "B", "F"):
        d = daily_by_model[model]
        trough = d.loc[d["drawdown"].idxmin()]
        prefix = d.loc[d["date"] <= trough["date"]]
        peak = prefix.loc[prefix["unit_nav"].idxmax()]
        ax.plot(d["date"], 100.0 * d["drawdown"], label=f"{model}: {100*trough['drawdown']:.2f}%", color=COLORS[model])
        ax.scatter([peak["date"], trough["date"]], [100 * peak["drawdown"], 100 * trough["drawdown"]], color=COLORS[model], s=18)
        ax.annotate(f"{model} peak\n{pd.Timestamp(peak['date']).date()}", (peak["date"], 100 * peak["drawdown"]), fontsize=7)
        ax.annotate(f"{model} trough\n{pd.Timestamp(trough['date']).date()}", (trough["date"], 100 * trough["drawdown"]), fontsize=7)
    ax.set(title="Drawdown paths with peak and trough", ylabel="Drawdown (%)", xlabel="UTC date")
    ax.grid(alpha=0.2)
    ax.legend(ncol=2)
    _save(fig, figure_dir, "03_drawdown_v3_4")

    fig, ax = plt.subplots(figsize=(12, 6))
    for model in ("B", "F"):
        d = daily_by_model[model]
        ax.plot(d["date"], 100.0 * d["crypto_exposure"], label=f"{model} exposure", color=COLORS[model])
    markers = {
        "CRASH_L3:": ("Crash L3", "#7c3aed", "v"),
        "MACRO_BEAR_INVALIDATED_TARGET_70": ("Bear invalidated", "#f59e0b", "s"),
        "NEW_BULL_CONFIRMED": ("NEW_BULL", "#0ea5e9", "^"),
        "CYCLE_RESET": ("Cycle close", "#111827", "o"),
    }
    for token, (label, color, marker) in markers.items():
        for date in _event_dates(result_f.signals, token):
            ax.axvline(date, color=color, ls="--", alpha=0.45)
            ax.scatter(date, 98, color=color, marker=marker, s=35, label=label)
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys(), ncol=3)
    ax.set(title="Crypto exposure and V3.4 patch events", ylabel="Crypto exposure (%)", xlabel="UTC date", ylim=(0, 102))
    ax.grid(alpha=0.2)
    _save(fig, figure_dir, "04_crypto_exposure_v3_4")

    fig, axes = plt.subplots(2, 2, figsize=(13, 8), sharex="row")
    for row_idx, (title, start, end) in enumerate([
        ("2020 COVID", "2020-02-15", "2020-04-30"),
        ("2021 May crash", "2021-05-01", "2021-07-31"),
    ]):
        start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
        f = daily_by_model["F"].loc[daily_by_model["F"]["date"].between(start_ts, end_ts)]
        b = daily_by_model["B"].loc[daily_by_model["B"]["date"].between(start_ts, end_ts)]
        axes[row_idx, 0].plot(f["date"], f["BTC_close"], color="#111827", label="BTC")
        axes[row_idx, 0].set_title(f"{title}: BTC and crash levels")
        for token, color, label in [
            ("CRASH_L1:", "#f59e0b", "L1"), ("CRASH_L2:", "#dc2626", "L2"), ("CRASH_L3:", "#7c3aed", "L3")
        ]:
            for date in _event_dates(result_f.signals, token):
                if start_ts <= date <= end_ts:
                    axes[row_idx, 0].axvline(date, color=color, ls="--", label=label)
        axes[row_idx, 1].plot(b["date"], 100 * b["crypto_exposure"], color=COLORS["B"], label="B exposure")
        axes[row_idx, 1].plot(f["date"], 100 * f["crypto_exposure"], color=COLORS["F"], label="F exposure")
        axes[row_idx, 1].plot(b["date"], 100 * b["drawdown"], color=COLORS["B"], ls=":", alpha=0.8, label="B DD")
        axes[row_idx, 1].plot(f["date"], 100 * f["drawdown"], color=COLORS["F"], ls=":", alpha=0.8, label="F DD")
        axes[row_idx, 1].set_title(f"{title}: exposure and portfolio DD")
        for col in (0, 1):
            axes[row_idx, col].grid(alpha=0.2)
            handles, labels = axes[row_idx, col].get_legend_handles_labels()
            unique = dict(zip(labels, handles))
            axes[row_idx, col].legend(unique.values(), unique.keys(), fontsize=8)
    _save(fig, figure_dir, "05_crash_zoom_v3_4")

    start, end = pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-10-31", tz="UTC")
    b = daily_by_model["B"].loc[daily_by_model["B"]["date"].between(start, end)]
    f = daily_by_model["F"].loc[daily_by_model["F"]["date"].between(start, end)]
    state_codes = {state: i for i, state in enumerate(["BULL", "DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION", "NEW_BULL"])}
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), sharex=True)
    axes[0].plot(f["date"], f["BTC_close"], color="#111827", label="BTC")
    axes[0].plot(f["date"], f["sma50"], color="#2563eb", label="SMA50")
    axes[0].plot(f["date"], f["sma200"], color="#dc2626", label="SMA200")
    axes[0].legend(ncol=3); axes[0].set_ylabel("BTC USD"); axes[0].grid(alpha=0.2)
    axes[1].plot(b["date"], 100 * b["crypto_exposure"], color=COLORS["B"], label="B exposure")
    axes[1].plot(f["date"], 100 * f["crypto_exposure"], color=COLORS["F"], label="F exposure")
    axes[1].legend(); axes[1].set_ylabel("Exposure (%)"); axes[1].grid(alpha=0.2)
    axes[2].step(b["date"], b["macro_state"].map(state_codes), color=COLORS["B"], where="post", label="B state")
    axes[2].step(f["date"], f["macro_state"].map(state_codes), color=COLORS["F"], where="post", label="F state")
    axes[2].set_yticks(list(state_codes.values()), list(state_codes.keys()), fontsize=8)
    axes[2].legend(); axes[2].grid(alpha=0.2)
    event_specs = [
        ("MACRO_BULL_REQUALIFICATION_CANDIDATE", "#f59e0b"),
        ("MACRO_BEAR_INVALIDATED_TARGET_70", "#7c3aed"),
        ("NEW_BULL_CONFIRMED", "#0ea5e9"),
        ("CYCLE_RESET", "#111827"),
    ]
    for token, color in event_specs:
        for date in _event_dates(result_f.signals, token):
            if start <= date <= end:
                for ax in axes:
                    ax.axvline(date, color=color, ls="--", alpha=0.45)
    axes[0].set_title("2023-2025 Macro Bull Requalification audit")
    _save(fig, figure_dir, "06_bull_requalification_v3_4")

    new_bulls = pd.to_datetime(
        result_f.transitions.loc[result_f.transitions["to_state"].eq("NEW_BULL"), "signal_date"], utc=True
    )
    if not new_bulls.empty:
        center = new_bulls.iloc[-1]
        start, end = center - pd.Timedelta(days=20), center + pd.Timedelta(days=45)
    else:
        start, end = f["date"].min(), f["date"].max()
    zoom = daily_by_model["F"].loc[daily_by_model["F"]["date"].between(start, end)]
    fig, ax = plt.subplots(figsize=(12, 6))
    ax.plot(zoom["date"], 100 * zoom["crypto_exposure"], color=COLORS["F"], label="Crypto exposure")
    ax.plot(zoom["date"], 100 * zoom["tactical_bear_cash_ratio"], color="#7c3aed", label="Tactical bear cash ratio")
    for token, color, label in [
        ("NEW_BULL_CONFIRMED", "#0ea5e9", "NEW_BULL"),
        ("FINAL_CASH_SWEEP", "#f59e0b", "Final sweep"),
        ("CYCLE_RESET", "#111827", "BULL / cycle close"),
    ]:
        for date in _event_dates(result_f.signals, token):
            if start <= date <= end:
                ax.axvline(date, color=color, ls="--", label=label)
    handles, labels = ax.get_legend_handles_labels()
    unique = dict(zip(labels, handles))
    ax.legend(unique.values(), unique.keys())
    ax.set(title="NEW_BULL redeploy and Final Cash Sweep", ylabel="Percent of portfolio", xlabel="UTC date")
    ax.grid(alpha=0.2)
    _save(fig, figure_dir, "07_new_bull_cash_sweep_v3_4")


def _money(value: Any) -> str:
    return "—" if pd.isna(value) else f"US${float(value):,.2f}"


def _pct(value: Any) -> str:
    return "—" if pd.isna(value) else f"{100 * float(value):.2f}%"


def _markdown(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No rows."
    printable = frame.copy()
    columns = [str(column) for column in printable.columns]
    values = [[str(value) for value in row] for row in printable.itertuples(index=False, name=None)]
    widths = [len(column) for column in columns]
    for row in values:
        widths = [max(width, len(value)) for width, value in zip(widths, row)]
    header = "| " + " | ".join(column.ljust(width) for column, width in zip(columns, widths)) + " |"
    rule = "| " + " | ".join("-" * width for width in widths) + " |"
    body = [
        "| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |"
        for row in values
    ]
    return "\n".join([header, rule, *body])


def write_v34_report(
    output_dir: Path,
    summary: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    events: pd.DataFrame,
    crash_audit: pd.DataFrame,
    crash_false: pd.DataFrame,
    requal: pd.DataFrame,
    cycles: pd.DataFrame,
    cash_reset: pd.DataFrame,
    churn: pd.DataFrame,
    participation: pd.DataFrame,
    no_lookahead: dict[str, Any],
) -> None:
    index = summary.set_index("model")
    comp = comparison.iloc[0]
    counts = churn.loc[churn["record_type"].eq("transition_count")].groupby("model")["count"].sum()
    f_part = participation.loc[participation["model"].eq("F")]
    bull_f = events.loc[events["event"].eq("2023_TO_2025_BULL") & events["model"].eq("F")].iloc[0]
    bull_b = events.loc[events["event"].eq("2023_TO_2025_BULL") & events["model"].eq("B")].iloc[0]
    max_f = index.loc["F"]
    event_pivot = events.pivot(index="event", columns="model", values="peak_to_trough_dd")
    longest_f = cycles.loc[cycles["model"].eq("F"), "duration_days"].max()
    missed_f = cycles.loc[cycles["model"].eq("F"), "missed_macro_bull"].fillna(False).astype(bool).any()
    completed_cash = cash_reset.loc[cash_reset["status"].eq("COMPLETED_NEW_BULL")]
    cash_pass = bool(not completed_cash.empty and completed_cash["cash_reset_audit"].eq("PASS").all())
    f_part_first = f_part.iloc[0] if not f_part.empty else pd.Series(dtype=object)
    simultaneous = all([
        comp["delta_covid_dd_percentage_points"] > 0,
        comp["delta_may_dd_percentage_points"] > 0,
        verdict["checks"]["normal_bear_regression_lte_2pp"],
        comp["delta_2023_2025_average_exposure_percentage_points"] > 0,
        cash_pass,
    ])
    lines = [
        "# BTC+ETH Macro Hedge V3.4 FINAL — Formal Backtest Report",
        "",
        f"**Final Verdict: {verdict['final_verdict']}**",
        "",
        "This was one frozen-parameter run. No result-aware threshold search was performed, and promotion gates were evaluated only after simulation.",
        "",
        "## Headline performance",
        "",
        _markdown(summary),
        "",
        "## Direct answers",
        "",
        f"1. H0 final: {_money(index.loc['H0', 'final_portfolio_value'])}.",
        f"2. A Fixed DCA final: {_money(index.loc['A', 'final_portfolio_value'])}.",
        f"3. B V3.1 final: {_money(index.loc['B', 'final_portfolio_value'])}.",
        f"4. F V3.4 final: {_money(index.loc['F', 'final_portfolio_value'])}.",
        "5. Max DD — " + ", ".join(f"{m}: {_pct(index.loc[m, 'maximum_drawdown'])}" for m in ("H0", "A", "B", "F")) + ".",
        f"6. V3.4 within 30%: {'YES' if verdict['checks']['maximum_drawdown_gte_minus_0_30'] else 'NO'}.",
        f"7. V3.4 maximum drawdown: {pd.Timestamp(max_f['peak_date']).date()} to {pd.Timestamp(max_f['trough_date']).date()}, {_pct(max_f['maximum_drawdown'])}.",
        f"8. COVID DD — B: {_pct(event_pivot.loc['2020_COVID','B'])}; F: {_pct(event_pivot.loc['2020_COVID','F'])}.",
        f"9. 2021 May DD — B: {_pct(event_pivot.loc['2021_MAY','B'])}; F: {_pct(event_pivot.loc['2021_MAY','F'])}.",
        f"10. 2021-Nov to 2022-Jun F DD: {_pct(event_pivot.loc['2021_NOV_TO_2022_JUN','F'])}; normal-bear gate {'PASS' if verdict['checks']['normal_bear_regression_lte_2pp'] else 'FAIL'}.",
        f"11. Crash L3 triggers: {len(crash_audit)}.",
        f"12. Crash false positives: {int(crash_false.get('potential_crash_false_positive', pd.Series(dtype=bool)).sum())}.",
        f"13. Macro Bull Requalifications: {int(index.loc['F','macro_bull_requalification_count'])}.",
        f"14. 2023-2025 F average exposure: {_pct(bull_f['average_crypto_exposure'])}.",
        f"15. Exposure improvement vs B: {100*(bull_f['average_crypto_exposure']-bull_b['average_crypto_exposure']):.2f} percentage points.",
        f"16. First F NEW_BULL: days to 85/90/95 = {f_part_first.get('days_to_85', np.nan)} / {f_part_first.get('days_to_90', np.nan)} / {f_part_first.get('days_to_95', np.nan)}.",
        f"17. Longest F cycle: {longest_f:.0f} days.",
        f"18. Missed multi-year macro bull remains: {'YES' if missed_f else 'NO'}.",
        f"19. Final Cash Sweep cash reset <=1%: {'YES' if cash_pass else 'NO'}.",
        f"20. F material tactical cash time: {_pct(index.loc['F','material_tactical_cash_time'])}.",
        f"21. State churn: B {int(counts.get('B',0))}, F {int(counts.get('F',0))}, reduction {100*comp['state_churn_reduction_fraction']:.2f}%.",
        f"22. F tactical turnover: {index.loc['F','tactical_turnover']:.4f}x.",
        f"23. CAGR >=45%: {'YES' if verdict['checks']['twr_cagr_gte_0_45'] else 'NO'} ({_pct(index.loc['F','twr_cagr'])}).",
        f"24. Calmar >=1.5: {'YES' if verdict['checks']['calmar_gte_1_50'] else 'NO'} ({index.loc['F','calmar']:.3f}).",
        f"25. Crash protection + normal-bear preservation + bull participation + cash reset all achieved: {'YES' if simultaneous else 'NO'}.",
        f"26. Replace V3.1 for forward paper test: {'YES' if verdict['final_verdict'].startswith('A.') else 'NO'}.",
        "",
        "## F vs B deltas",
        "",
        _markdown(comparison),
        "",
        "## Promotion gates",
        "",
        _markdown(pd.DataFrame([{"gate": key, "pass": value} for key, value in verdict["checks"].items()])),
        "",
        "## Crash L3 audit",
        "",
        _markdown(crash_audit),
        "",
        "## Macro Bull Requalification audit",
        "",
        _markdown(requal),
        "",
        "## Bull participation",
        "",
        _markdown(participation),
        "",
        "## Cash reset",
        "",
        _markdown(cash_reset),
        "",
        "## Integrity",
        "",
        f"- NO_LOOK_AHEAD: {'PASS' if no_lookahead['no_lookahead_pass'] else 'FAIL'}",
        f"- EXECUTION_INTEGRITY: {'PASS' if no_lookahead['execution_integrity_pass'] else 'FAIL'}",
        f"- CASH_RESET_AUDIT: {'PASS' if no_lookahead['cash_reset_integrity_pass'] else 'FAIL'}",
        "",
        "## J Law decision matrix",
        "",
        f"- Champion: V3.1 B before evaluation; challenger: V3.4 F.",
        f"- Return Edge: delta final {_money(comp['delta_final_value'])}; delta CAGR {comp['delta_cagr_percentage_points']:.2f} pp.",
        f"- Drawdown Edge: delta Max DD {comp['delta_max_drawdown_percentage_points']:.2f} pp.",
        f"- COVID Protection: {comp['delta_covid_dd_percentage_points']:.2f} pp.",
        f"- May Crash Protection: {comp['delta_may_dd_percentage_points']:.2f} pp.",
        f"- Normal Bear Protection: {'PASS' if verdict['checks']['normal_bear_regression_lte_2pp'] else 'FAIL'}.",
        f"- Bull Requalification Quality: {len(requal)} candidate episode(s), {int(index.loc['F','macro_bull_requalification_count'])} confirmed.",
        f"- Bull Participation: {'PASS' if verdict['checks']['bull_participation_pass'] else 'FAIL'}.",
        f"- Cash Reset Quality: {'PASS' if cash_pass else 'FAIL'}.",
        f"- Cycle Duration Quality: longest {longest_f:.0f} days; missed macro bull {'YES' if missed_f else 'NO'}.",
        f"- State Stability: {'PASS' if verdict['checks']['state_churn_reduced_at_least_50pct'] else 'FAIL'}.",
        f"- Turnover: {'PASS' if verdict['checks']['tactical_turnover_lte_9_8361'] else 'FAIL'}.",
        f"- Execution Integrity: {'PASS' if no_lookahead['execution_integrity_pass'] else 'FAIL'}.",
        "- Overfit Risk: rules were frozen before the single formal run; nevertheless all thresholds remain historical hypotheses requiring forward validation.",
        f"- Final Verdict: {verdict['final_verdict']}",
    ]
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_4.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["create_v34_figures", "write_v34_report"]
