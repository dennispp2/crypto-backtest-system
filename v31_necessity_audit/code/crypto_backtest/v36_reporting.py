from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#9C9C9C", "A": "#4C78A8", "B": "#E45756", "H": "#54A24B"}


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def _bottom_zoom(
    output: Path,
    daily_by_model: dict[str, pd.DataFrame],
    audit: pd.DataFrame,
    start: str,
    end: str,
    title: str,
) -> None:
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    fig, axes = plt.subplots(4, 1, figsize=(13, 11), sharex=True)
    for model in ("B", "H"):
        data = daily_by_model[model]
        zoom = data.loc[data["date"].between(start_ts, end_ts)]
        axes[0].plot(zoom["date"], zoom["BTC_close"], color=COLORS[model], lw=1.15, label=f"{model} BTC reference")
        axes[1].step(zoom["date"], 100 * zoom["crypto_exposure"], where="post", color=COLORS[model], lw=1.2, label=f"{model} exposure")
        axes[2].plot(zoom["date"], zoom["ahr999"], color=COLORS[model], lw=1.1, label=f"{model} AHR999")
        axes[3].plot(zoom["date"], zoom["portfolio_value"], color=COLORS[model], lw=1.2, label=f"{model} value")
    events = audit.loc[pd.to_datetime(audit["timestamp"], utc=True).between(start_ts, end_ts)]
    for model, marker in (("B", "o"), ("H", "^")):
        model_events = events.loc[events["model"].eq(model)]
        for side, edge in (("BUY", "#1B7F3A"), ("SELL", "#A5161A")):
            points = model_events.loc[model_events["side"].eq(side)]
            axes[0].scatter(
                points["timestamp"], points["btc_close"], s=45, marker=marker,
                facecolors="none", edgecolors=edge, label=f"{model} {side}", zorder=5,
            )
    axes[0].set_ylabel("BTC USD")
    axes[1].set_ylabel("Exposure %")
    axes[2].set_ylabel("AHR999")
    axes[2].axhline(0.35, color="black", ls="--", lw=0.8)
    axes[3].set_ylabel("Portfolio USD"); axes[3].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.23); ax.legend(fontsize=7, ncol=4)
    fig.suptitle(title); fig.tight_layout()
    _save(fig, output)


def create_v36_figures(
    output_dir: Path,
    daily_by_model: dict[str, pd.DataFrame],
    bottom_audit: pd.DataFrame,
    tactical_events: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    plt.style.use("default")

    fig, ax = plt.subplots(figsize=(13, 6))
    for model in ("H0", "A", "B", "H"):
        daily = daily_by_model[model]
        ax.plot(daily["date"], daily["portfolio_value"], color=COLORS[model], lw=1.25, label=model)
    ax.set(title="V3.6 Portfolio Equity: H0 / A / B / H", xlabel="UTC date", ylabel="Portfolio value (USD)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "01_equity_curve_h0_a_b_h_v3_6.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in ("H0", "A", "B", "H"):
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["unit_nav"], color=COLORS[model], lw=1.2, label=model)
    ax.set(title="V3.6 Time-weighted NAV (start = 100)", xlabel="UTC date", ylabel="TWR NAV")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "02_normalized_twr_h0_a_b_h_v3_6.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in ("H0", "A", "B", "H"):
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["drawdown"], color=COLORS[model], lw=1.2, label=model)
    ax.set(title="V3.6 Drawdown", xlabel="UTC date", ylabel="Drawdown (%)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "03_drawdown_h0_a_b_h_v3_6.png")

    _bottom_zoom(
        figure_dir / "04_2022_bottom_zoom_v3_6.png", daily_by_model, bottom_audit,
        "2022-06-01", "2022-07-31", "2022 bottom: BTC, exposure, tactical markers, AHR and value",
    )
    _bottom_zoom(
        figure_dir / "05_2026_bottom_zoom_v3_6.png", daily_by_model, bottom_audit,
        "2026-02-01", "2026-06-30", "2026 bottom: BTC, exposure, tactical markers, AHR and value",
    )

    monthly = tactical_events.copy()
    monthly["month"] = pd.to_datetime(monthly["timestamp"], utc=True).dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby(["month", "model"], as_index=False).size().rename(columns={"size": "events"})
    pivot = monthly.pivot(index="month", columns="model", values="events").fillna(0)
    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in ("B", "H"):
        values = pivot[model] if model in pivot else pd.Series(0.0, index=pivot.index)
        ax.plot(pivot.index, values, marker="o", ms=2.5, lw=1.0, color=COLORS[model], label=model)
    ax.set(title="Monthly tactical event frequency (true event timestamps)", xlabel="UTC month", ylabel="Events")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "06_monthly_tactical_event_frequency_b_vs_h_v3_6.png")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _md(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(no rows)"
    values = frame.copy()
    return "\n".join([
        "| " + " | ".join(values.columns.astype(str)) + " |",
        "| " + " | ".join(["---"] * len(values.columns)) + " |",
        *["| " + " | ".join(str(value) for value in row) + " |" for row in values.itertuples(index=False, name=None)],
    ])


def write_v36_report(
    output_dir: Path,
    summary: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    bottom_summary: pd.DataFrame,
    tactical_stats: pd.DataFrame,
    event_audit: pd.DataFrame,
    integrity: dict[str, Any],
    replay: dict[str, Any],
) -> None:
    perf = summary[[
        "model", "final_portfolio_value", "xirr", "twr_cagr", "maximum_drawdown",
        "sharpe", "sortino", "calmar", "tactical_turnover", "tactical_event_count",
    ]].copy()
    for column in ("xirr", "twr_cagr", "maximum_drawdown"):
        perf[column] = perf[column].map(_pct)
    perf["final_portfolio_value"] = perf["final_portfolio_value"].map(_money)
    for column in ("sharpe", "sortino", "calmar"):
        perf[column] = perf[column].map(lambda value: f"{value:.4f}")
    perf["tactical_turnover"] = perf["tactical_turnover"].map(lambda value: f"{value:.4f}x")
    indexed = summary.set_index("model")
    comp = comparison.iloc[0]
    bottom = bottom_summary.set_index(["period", "model"])
    event = event_audit.set_index(["event", "model"])
    tactical = tactical_stats.set_index("model")

    def event_count(period: str, model: str) -> int:
        return int(bottom.loc[(period, model), "bottom_tactical_event_count"])

    def event_dd(name: str, model: str) -> float:
        return float(event.loc[(name, model), "peak_to_trough_drawdown"])

    answers = [
        f"1. V3.1 Model B exact replay: **{'PASS' if replay['pass'] else 'FAIL'}**; final {_money(indexed.loc['B','final_portfolio_value'])}, tactical events {int(indexed.loc['B','tactical_event_count'])}.",
        f"2. V3.6 Model H final value: **{_money(indexed.loc['H','final_portfolio_value'])}** ({_money(comp['delta_final_value'])} versus B).",
        f"3. H TWR CAGR: **{_pct(indexed.loc['H','twr_cagr'])}**; delta versus B {comp['delta_cagr_percentage_points']:.2f} percentage points.",
        f"4. H maximum drawdown: **{_pct(indexed.loc['H','maximum_drawdown'])}**; delta versus B {comp['delta_max_drawdown_percentage_points']:.2f} percentage points.",
        f"5. H Calmar: **{indexed.loc['H','calmar']:.4f}**; delta {comp['delta_calmar']:.4f}.",
        f"6. 2022 bottom events B/H: **{event_count('BOTTOM_2022','B')} / {event_count('BOTTOM_2022','H')}**; reduction {_pct(comp['bottom_2022_event_reduction_fraction'])}.",
        f"7. 2026 bottom events B/H: **{event_count('BOTTOM_2026','B')} / {event_count('BOTTOM_2026','H')}**; reduction {_pct(comp['bottom_2026_event_reduction_fraction'])}.",
        f"8. Full-period 7-day opposite-side whipsaw-pair reduction: **{_pct(comp['whipsaw_pair_reduction_fraction'])}**.",
        f"9. Overall tactical turnover B/H: **{tactical.loc['B','tactical_turnover']:.4f}x / {tactical.loc['H','tactical_turnover']:.4f}x**; reduction {_pct(comp['overall_turnover_reduction_fraction'])}.",
        f"10. 2021-11 through 2022-06 drawdown B/H: **{_pct(event_dd('BEAR_2021NOV_2022JUN','B'))} / {_pct(event_dd('BEAR_2021NOV_2022JUN','H'))}**.",
        f"11. 2025 through cutoff drawdown B/H: **{_pct(event_dd('CORRECTION_2025_2026','B'))} / {_pct(event_dd('CORRECTION_2025_2026','H'))}**.",
        f"12. COVID drawdown B/H: **{_pct(event_dd('COVID_2020','B'))} / {_pct(event_dd('COVID_2020','H'))}**; the patch does not block the original risk sells.",
        f"13. 2021 May drawdown B/H: **{_pct(event_dd('MAY_2021','B'))} / {_pct(event_dd('MAY_2021','H'))}**.",
        f"14. Fixed-DCA row identity: **{'PASS' if integrity['checks']['fixed_dca_row_integrity'] else 'FAIL'}**.",
        f"15. Completed-candle/no-look-ahead audit: **{'PASS' if integrity['no_lookahead_pass'] else 'FAIL'}**.",
        f"16. Same-timestamp tactical buy and sell violations in H: **{integrity['same_timestamp_opposite_tactical_action_violations']}**.",
        f"17. V3.2-V3.5 strategy inheritance found in H engine: **{'NO' if integrity['checks']['v36_engine_has_no_v32_v35_inheritance'] else 'YES'}**.",
        f"18. The 30% drawdown threshold is **not** a V3.6 promotion gate; the frozen gates are reproduced below without alteration.",
        f"19. Final classification: **{verdict['final_verdict']}**.",
    ]
    report = f"""# BTC+ETH Macro Hedge V3.6

## Final verdict

**{verdict['final_verdict']}**

- `PROMOTION_GATE = {verdict['promotion_gate']}`
- `V3_1_REPLAY_INTEGRITY = {'PASS' if replay['pass'] else 'FAIL'}`
- `FIXED_DCA_ROW_INTEGRITY = {'PASS' if integrity['checks']['fixed_dca_row_integrity'] else 'FAIL'}`
- `NO_LOOK_AHEAD = {'PASS' if integrity['no_lookahead_pass'] else 'FAIL'}`
- `EXECUTION_INTEGRITY = {'PASS' if integrity['execution_integrity_pass'] else 'FAIL'}`
- `FSM_AUDIT = {'PASS' if integrity['checks']['fsm_legal'] else 'FAIL'}`

## Performance

{_md(perf)}

## Direct answers

{chr(10).join(answers)}

## Frozen promotion gates

```json
{json.dumps(verdict['checks'], indent=2)}
```

## B versus H comparison

{_md(comparison)}

## Bottom-event summary

{_md(bottom_summary)}

## Event drawdown audit

{_md(event_audit)}

## Interpretation and bias limits

- This is one realized crypto path, not an independent out-of-sample discovery. The patch was frozen before the formal run, but historical regime knowledge can still influence the research question.
"""
    report += """
- Model H differs from Model B in both the isolated buy-frequency guard and the explicitly requested DCA-first within-bar order. Because DCA trades are tiny, the row ledger is identical, but attribution should still acknowledge this execution-order difference.
- The requested 20-day-low field is used only to block/rearm buys. It never changes V3.1 macro classification, crash logic, risk sells or targets.
- Fees, slippage and minimum-notional assumptions are modeled constants. Liquidity, spread tails, taxes, custody risk and exchange failure are outside this backtest.
- Promotion means forward paper testing only, not permission to deploy live capital. No failed gate was repaired by changing a threshold after the run.
"""
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_6.md").write_text(report, encoding="utf-8")
    (output_dir / "FINAL_REPORT_V3_6.md").write_text(report, encoding="utf-8")


__all__ = ["create_v36_figures", "write_v36_report"]
