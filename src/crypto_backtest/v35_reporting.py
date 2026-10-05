from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#6b7280", "A": "#2563eb", "B": "#dc2626", "F": "#059669", "G": "#7c3aed"}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=320, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def create_v35_figures(
    output_dir: Path,
    daily_by_model: dict[str, pd.DataFrame],
    bottom_audit: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    fig, ax = plt.subplots(figsize=(12, 6))
    for model in ("H0", "A", "B", "F", "G"):
        daily = daily_by_model[model]
        ax.plot(daily["date"], daily["portfolio_value"], label=model, color=COLORS[model], lw=1.4)
    ax.set(title="V3.5 Patch D absolute portfolio value", ylabel="USD", xlabel="UTC date")
    ax.grid(alpha=0.2)
    ax.legend(ncol=5)
    _save(fig, figure_dir, "01_equity_curve_v3_5")

    windows = [
        ("2022 bottom audit", pd.Timestamp("2022-05-01", tz="UTC"), pd.Timestamp("2022-08-31", tz="UTC")),
        ("2026 bottom audit", pd.Timestamp("2026-01-01", tz="UTC"), pd.Timestamp("2026-07-31", tz="UTC")),
    ]
    fig, axes = plt.subplots(2, 3, figsize=(18, 10), sharex="row")
    for row_index, (title, start, end) in enumerate(windows):
        b = daily_by_model["B"].loc[daily_by_model["B"]["date"].between(start, end)]
        g = daily_by_model["G"].loc[daily_by_model["G"]["date"].between(start, end)]
        price_ax, value_ax, ahr_ax = axes[row_index]
        price_ax.plot(g["date"], g["BTC_close"], color="#111827", lw=1.2, label="BTC")
        scoped = bottom_audit.loc[
            bottom_audit["model"].isin(["B", "G"])
            & pd.to_datetime(bottom_audit["signal_date"], utc=True).between(start, end)
        ]
        for model, marker_shift in (("B", 1.02), ("G", 0.98)):
            for side, marker in (("BUY", "^"), ("SELL", "v")):
                events = scoped.loc[scoped["model"].eq(model) & scoped["side"].eq(side)]
                if not events.empty:
                    price_ax.scatter(
                        events["signal_date"], events["btc_close"].astype(float) * marker_shift,
                        marker=marker, s=45, color=COLORS[model], edgecolor="white", linewidth=0.4,
                        label=f"{model} {side}", zorder=3,
                    )
        price_ax.set_title(f"{title}: BTC and bottom tactical actions")
        price_ax.set_ylabel("BTC USD")
        price_ax.legend(fontsize=8, ncol=3)

        value_ax.plot(b["date"], b["portfolio_value"], color=COLORS["B"], label="B value")
        value_ax.plot(g["date"], g["portfolio_value"], color=COLORS["G"], label="G value")
        exposure_ax = value_ax.twinx()
        exposure_ax.plot(b["date"], 100 * b["crypto_exposure"], color=COLORS["B"], ls=":", alpha=0.75, label="B exposure")
        exposure_ax.plot(g["date"], 100 * g["crypto_exposure"], color=COLORS["G"], ls=":", alpha=0.75, label="G exposure")
        handles1, labels1 = value_ax.get_legend_handles_labels()
        handles2, labels2 = exposure_ax.get_legend_handles_labels()
        value_ax.legend(handles1 + handles2, labels1 + labels2, fontsize=8, ncol=2)
        value_ax.set_title(f"{title}: portfolio value and exposure")
        value_ax.set_ylabel("Portfolio USD")
        exposure_ax.set_ylabel("Exposure (%)")

        ahr_ax.plot(g["date"], g["ahr999"], color="#f59e0b", label="AHR999")
        ahr_ax.axhline(0.35, color="#dc2626", ls="--", lw=1.0, label="Value base 0.35")
        ahr_ax.axhline(0.30, color="#7c3aed", ls=":", lw=1.0, label="Deep value 0.30")
        ahr_ax.set_title(f"{title}: AHR999")
        ahr_ax.set_ylabel("AHR999")
        ahr_ax.legend(fontsize=8)
        for ax in (price_ax, value_ax, ahr_ax, exposure_ax):
            ax.grid(alpha=0.18)
    _save(fig, figure_dir, "08_bottom_whipsaw_zoom_v3_5")


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
    body = ["| " + " | ".join(value.ljust(width) for value, width in zip(row, widths)) + " |" for row in values]
    return "\n".join([header, rule, *body])


def _pct(value: Any) -> str:
    return "—" if pd.isna(value) else f"{100 * float(value):.2f}%"


def _money(value: Any) -> str:
    return "—" if pd.isna(value) else f"US${float(value):,.2f}"


def write_v35_report(
    output_dir: Path,
    summary: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    bottom_summary: pd.DataFrame,
    bottom_audit: pd.DataFrame,
    events: pd.DataFrame,
    no_lookahead: dict[str, Any],
    v34_replay: dict[str, Any],
) -> None:
    index = summary.set_index("model")
    comp = comparison.iloc[0]
    bottom = bottom_summary.loc[bottom_summary["period"].eq("FULL")].set_index("model")
    lines = [
        "# BTC+ETH Macro Hedge V3.5 — Patch D Formal Backtest",
        "",
        f"**Final Verdict: {verdict['final_verdict']}**",
        "",
        "Patch D was isolated as V3.5 Model G because V3.4 had already been frozen and formally executed. V3.4 Model F was replayed unchanged; no thresholds were searched after results were observed.",
        "",
        "## Headline performance",
        "",
        _markdown(summary),
        "",
        "## Patch D direct answers",
        "",
        f"- G final value: {_money(index.loc['G', 'final_portfolio_value'])}; B final value: {_money(index.loc['B', 'final_portfolio_value'])}.",
        f"- G CAGR / Max DD / Calmar: {_pct(index.loc['G','twr_cagr'])} / {_pct(index.loc['G','maximum_drawdown'])} / {index.loc['G','calmar']:.3f}.",
        f"- Bottom tactical events: B {int(bottom.loc['B','bottom_tactical_event_count'])}, G {int(bottom.loc['G','bottom_tactical_event_count'])}.",
        f"- Whipsaw pairs: B {int(bottom.loc['B','whipsaw_pair_count'])}, G {int(bottom.loc['G','whipsaw_pair_count'])}; reduction {_pct(comp['bottom_whipsaw_pair_reduction_fraction'])}.",
        f"- 2022 bottom trade reduction: {_pct(comp['bottom_2022_trade_count_reduction_fraction'])}.",
        f"- 2026 bottom trade reduction: {_pct(comp['bottom_2026_trade_count_reduction_fraction'])}.",
        f"- Overall tactical turnover: B {index.loc['B','tactical_turnover']:.4f}x, G {index.loc['G','tactical_turnover']:.4f}x.",
        f"- V3.4 frozen replay: {'PASS' if v34_replay['pass'] else 'FAIL'}.",
        "",
        "## G vs B comparison",
        "",
        _markdown(comparison),
        "",
        "## Patch D evaluation gates",
        "",
        _markdown(pd.DataFrame([{"gate": key, "pass": value} for key, value in verdict["patch_d_checks"].items()])),
        "",
        "## V3.4 inherited promotion gates",
        "",
        _markdown(pd.DataFrame([{"gate": key, "pass": value} for key, value in verdict["v3_4_core_checks"].items()])),
        "",
        "## Bottom whipsaw summary",
        "",
        _markdown(bottom_summary),
        "",
        "## Event drawdown audit",
        "",
        _markdown(events),
        "",
        "## Integrity",
        "",
        f"- NO_LOOK_AHEAD: {'PASS' if no_lookahead['no_lookahead_pass'] else 'FAIL'}",
        f"- EXECUTION_INTEGRITY: {'PASS' if no_lookahead['execution_integrity_pass'] else 'FAIL'}",
        f"- PATCH_D_COOLDOWN_VIOLATIONS: {no_lookahead['patch_d_cooldown_violations']}",
        f"- PATCH_D_MULTI_RUNG_VIOLATIONS: {no_lookahead['patch_d_multi_rung_violations']}",
        "",
        "The complete event-level records are in `bottom_whipsaw_audit_v3_5.csv`.",
    ]
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_5.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


__all__ = ["create_v35_figures", "write_v35_report"]
