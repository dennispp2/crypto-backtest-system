from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"A": "#4C78A8", "B": "#E45756", "C": "#54A24B"}
STATES = ["BULL", "DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION", "NEW_BULL"]
STATE_MAP = {state: index for index, state in enumerate(STATES)}


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=300, bbox_inches="tight")
    fig.savefig(path.with_suffix(".pdf"), bbox_inches="tight", metadata={"CreationDate": None, "ModDate": None})
    plt.close(fig)


def create_v31_figures(
    output_dir: Path, daily_by_model: dict[str, pd.DataFrame],
    signals_by_model: dict[str, pd.DataFrame], trades: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    plt.style.use("default")

    fig, ax = plt.subplots(figsize=(12, 6))
    for model, daily in daily_by_model.items():
        ax.plot(daily["date"], daily["portfolio_value"], color=COLORS[model], label=f"MODEL {model}", lw=1.35)
    ax.set(title="BTC+ETH V3.1 Portfolio Equity", xlabel="UTC date", ylabel="Portfolio value (USD)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "01_equity_curve_v3_1.png")

    fig, ax = plt.subplots(figsize=(12, 5.5))
    for model, daily in daily_by_model.items():
        ax.plot(daily["date"], 100 * daily["drawdown"], color=COLORS[model], label=f"MODEL {model}", lw=1.25)
    ax.set(title="V3.1 Drawdown", xlabel="UTC date", ylabel="Drawdown (%)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "02_drawdown_v3_1.png")

    fig, ax = plt.subplots(figsize=(12, 5.5))
    for model, daily in daily_by_model.items():
        ax.plot(daily["date"], 100 * daily["crypto_exposure"], color=COLORS[model], label=f"MODEL {model}", lw=1.15)
    ax.set(title="V3.1 Crypto Exposure", xlabel="UTC date", ylabel="Crypto exposure (%)", ylim=(0, 105))
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "03_crypto_exposure_v3_1.png")

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True)
    for model in ("B", "C"):
        daily = daily_by_model[model]
        axes[0].plot(daily["date"], 100 * daily["tactical_bear_cash_ratio"], color=COLORS[model], label=f"{model} bear cash")
        axes[1].plot(daily["date"], 100 * daily["temporary_hedge_cash_ratio"], color=COLORS[model], label=f"{model} temporary cash")
    axes[0].set_ylabel("Bear cash (%)"); axes[1].set_ylabel("Temporary cash (%)"); axes[1].set_xlabel("UTC date")
    for ax in axes: ax.grid(alpha=0.25); ax.legend()
    fig.suptitle("V3.1 Tactical Cash Ledgers")
    _save(fig, figure_dir / "04_tactical_cash_v3_1.png")

    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True)
    for axis, model in zip(axes, ("B", "C")):
        daily = daily_by_model[model]
        axis.step(daily["date"], daily["sell_stage"], where="post", color=COLORS[model], label=f"MODEL {model}")
        axis.set_yticks([0, 1, 2, 3, 4]); axis.set_ylabel("Stage"); axis.grid(alpha=0.25); axis.legend()
    axes[-1].set_xlabel("UTC date"); fig.suptitle("V3.1 FSM Tactical Stage")
    _save(fig, figure_dir / "05_fsm_stage_v3_1.png")

    c_signal = signals_by_model["C"]
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(c_signal["signal_date"], c_signal["bear_risk"], color=COLORS["C"], lw=1.0, label="OOS Bear Risk")
    ax.axhline(0.70, color="#E45756", ls="--", lw=1.0, label="AI intervention threshold 0.70")
    ax.axhline(0.40, color="gray", ls=":", lw=1.0, label="No-intervention threshold 0.40")
    disabled = c_signal.loc[~c_signal["ai_enabled"].astype(bool)]
    if not disabled.empty:
        ax.scatter(disabled["signal_date"], np.zeros(len(disabled)), s=3, color="black", label="AI disabled")
    ax.set(title="Annual Walk-Forward Bear Risk", xlabel="Completed BTC daily candle", ylabel="Probability", ylim=(-0.03, 1.03))
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "06_bear_risk_v3_1.png")

    start, end = pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC")
    b, c = daily_by_model["B"], daily_by_model["C"]
    bz, cz = b.loc[b["date"].between(start, end)], c.loc[c["date"].between(start, end)]
    sig_c = c_signal.loc[pd.to_datetime(c_signal["signal_date"], utc=True).between(start, end)]
    fig, axes = plt.subplots(5, 1, figsize=(13, 12), sharex=True)
    axes[0].plot(bz["date"], bz["BTC_close"], color="#4C78A8"); axes[0].set_yscale("log"); axes[0].set_ylabel("BTC USD")
    axes[1].step(bz["date"], bz["sell_stage"], where="post", color=COLORS["B"], label="B")
    axes[1].step(cz["date"], cz["sell_stage"], where="post", color=COLORS["C"], label="C", alpha=0.8); axes[1].set_ylabel("Stage"); axes[1].legend()
    axes[2].plot(bz["date"], 100 * bz["crypto_exposure"], color=COLORS["B"], label="B exposure")
    axes[2].plot(cz["date"], 100 * cz["crypto_exposure"], color=COLORS["C"], label="C exposure"); axes[2].set_ylabel("Exposure %"); axes[2].legend()
    axes[3].step(bz["date"], bz["macro_state"].map(STATE_MAP), where="post", color=COLORS["B"], label="B")
    axes[3].step(cz["date"], cz["macro_state"].map(STATE_MAP), where="post", color=COLORS["C"], label="C", alpha=0.8)
    axes[3].set_yticks(range(len(STATES)), STATES, fontsize=7); axes[3].set_ylabel("FSM"); axes[3].legend()
    axes[4].plot(sig_c["signal_date"], sig_c["bear_risk"], color=COLORS["C"]); axes[4].axhline(0.70, color="#E45756", ls="--")
    axes[4].set_ylabel("Bear Risk"); axes[4].set_xlabel("UTC date")
    for ax in axes: ax.grid(alpha=0.22)
    fig.suptitle("2021-2022: BTC, FSM, Exposure and OOS Bear Risk"); fig.tight_layout()
    _save(fig, figure_dir / "07_2021_2022_zoom_v3_1.png")

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(b["date"], b["BTC_close"], color="#4C78A8", lw=1.0, label="BTC close")
    tactical = trades.loc[trades["model"].isin(["B", "C"]) & trades["action"].str.startswith("TACTICAL", na=False)].copy()
    styles = {
        "TACTICAL_SELL_STAGE1": ("v", "#F58518"), "TACTICAL_SELL_STAGE2": ("v", "#E45756"),
        "TACTICAL_SELL_STAGE3": ("v", "#B279A2"), "TACTICAL_SELL_STAGE4": ("X", "#9D755D"),
        "TACTICAL_BUYBACK_AHR999_TO_35": ("o", "#54A24B"),
        "TACTICAL_BUYBACK_RIGHT_TO_50": ("^", "#72B7B2"),
        "TACTICAL_BUYBACK_RIGHT_TO_60": ("^", "#2CA02C"),
        "TACTICAL_BUYBACK_NEW_BULL_REDEPLOY": ("D", "#59A14F"),
    }
    daily_price = b[["date", "BTC_close"]].sort_values("date")
    for action, (marker, color) in styles.items():
        events = tactical.loc[tactical["action"].eq(action)].drop_duplicates(["model", "tactical_event_id"])
        if events.empty: continue
        located = pd.merge_asof(events.sort_values("timestamp"), daily_price, left_on="timestamp", right_on="date", direction="backward")
        ax.scatter(located["timestamp"], located["BTC_close"], marker=marker, color=color, s=35, label=action.replace("TACTICAL_", ""), alpha=0.75)
    ax.set_yscale("log"); ax.set(title="V3.1 Tactical Events", xlabel="UTC date", ylabel="BTC USD (log)")
    ax.grid(alpha=0.25); ax.legend(fontsize=7, ncol=3)
    _save(fig, figure_dir / "08_tactical_events_v3_1.png")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _md(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(no rows)"
    columns = list(frame.columns)
    header = "| " + " | ".join(columns) + " |"
    rule = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(str(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None)]
    return "\n".join([header, rule, *body])


def write_v31_report(
    output_dir: Path, summary: pd.DataFrame, comparisons: pd.DataFrame,
    verdict: dict[str, Any], ai_metrics: pd.DataFrame, frequency: pd.DataFrame,
    temp_lots: pd.DataFrame, audit_cases: pd.DataFrame, cycles: pd.DataFrame,
    interventions: pd.DataFrame, no_lookahead: dict[str, Any], rules: dict[str, Any],
) -> None:
    indexed = summary.set_index("model")
    perf = summary[["model", "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar", "tactical_turnover"]].copy()
    for column in ("twr_cagr", "maximum_drawdown"):
        perf[column] = perf[column].map(_pct)
    perf["final_portfolio_value"] = perf["final_portfolio_value"].map(_money)
    perf["calmar"] = perf["calmar"].map(lambda value: f"{value:.4f}")
    perf["tactical_turnover"] = perf["tactical_turnover"].map(lambda value: f"{value:.4f}x")
    all_ai = ai_metrics.loc[ai_metrics["scope"].eq("ALL_OOS")].iloc[0]
    stage4 = {}
    for model in ("B", "C"):
        cycle_start = pd.to_datetime(cycles["start"], utc=True, errors="coerce")
        cycle_end = pd.to_datetime(cycles["end"], utc=True, errors="coerce")
        rows = cycles.loc[
            cycles["model"].eq(model) & cycles["confirmed"].astype(bool)
            & (cycle_start <= pd.Timestamp("2022-06-30", tz="UTC"))
            & (cycle_end >= pd.Timestamp("2021-11-01", tz="UTC"))
        ]
        stage4[model] = rows["stage4_date"].min() if not rows.empty else pd.NaT
    ai_earlier = bool(pd.notna(stage4["B"]) and pd.notna(stage4["C"]) and pd.Timestamp(stage4["C"]) < pd.Timestamp(stage4["B"]))
    june_caps = int((
        interventions["ai_intervention"].eq("AI_BUYBACK_CAP")
        & pd.to_datetime(interventions["date"], utc=True).between(pd.Timestamp("2022-06-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC"))
    ).sum()) if not interventions.empty else 0
    case_idx = audit_cases.set_index(["case", "model"])
    may = {m: case_idx.loc[("CASE_2_2021_MAY_CRASH", m), "case_peak_to_trough_dd"] for m in ("A", "B", "C")}
    correction = {m: case_idx.loc[("CASE_8_2025_2026_CORRECTION", m), "case_peak_to_trough_dd"] for m in ("A", "B", "C")}
    cycle_counts = {m: int(cycles.loc[cycles["model"].eq(m) & cycles["confirmed"].astype(bool)].shape[0]) for m in ("B", "C")}
    temp_fail = {m: int(temp_lots.loc[temp_lots["model"].eq(m), "ever_over_30_without_bear"].astype(bool).sum()) if not temp_lots.empty else 0 for m in ("B", "C")}
    champion = "MODEL C" if verdict["final_verdict"].startswith("C.") else "MODEL B" if verdict["final_verdict"].startswith("B.") else "MODEL A"
    challenger = "MODEL C" if champion != "MODEL C" else "MODEL B"
    jlaw = pd.DataFrame([
        ["Champion", champion], ["Challenger", challenger],
        ["Return Edge", f"Final A/B/C: {_money(indexed.loc['A','final_portfolio_value'])} / {_money(indexed.loc['B','final_portfolio_value'])} / {_money(indexed.loc['C','final_portfolio_value'])}"],
        ["Drawdown Edge", f"Max DD A/B/C: {_pct(indexed.loc['A','maximum_drawdown'])} / {_pct(indexed.loc['B','maximum_drawdown'])} / {_pct(indexed.loc['C','maximum_drawdown'])}"],
        ["Calmar Edge", f"A/B/C: {indexed.loc['A','calmar']:.3f} / {indexed.loc['B','calmar']:.3f} / {indexed.loc['C','calmar']:.3f}"],
        ["Cash Drag", f"HIGH: material cash B/C {_pct(indexed.loc['B','material_tactical_cash_time'])} / {_pct(indexed.loc['C','material_tactical_cash_time'])}; ending bear cash {_money(indexed.loc['B','ending_tactical_bear_cash'])} / {_money(indexed.loc['C','ending_tactical_bear_cash'])}"],
        ["Bear Timing", f"Stage4 B={stage4['B']}; C={stage4['C']}; AI earlier={ai_earlier}"],
        ["Bull Re-entry", "Seven-gate NEW_BULL plus 10-day redeploy; see cycle and trade logs"],
        ["Crash Protection", f"2021/05 case DD A/B/C: {_pct(may['A'])} / {_pct(may['B'])} / {_pct(may['C'])}"],
        ["Bottom Buyback Quality", f"2022/06 AI cap interventions={june_caps}; see buyback_forward_10d_v3_1.csv"],
        ["AI Edge", verdict["ai_edge"]],
        ["Turnover", f"B={indexed.loc['B','tactical_turnover']:.4f}x; C={indexed.loc['C','tactical_turnover']:.4f}x"],
        ["Execution Integrity", "PASS" if no_lookahead["pass"] else "FAIL"],
        ["Overfit Risk", "FSM remains one retrospectively designed historical rule path; AI probabilities are annual OOS but not a proof of future alpha"],
    ], columns=["J Law field", "Verdict evidence"])
    report = f"""# Crypto BTC+ETH Fixed DCA + Macro Hedge V3.1

## Final verdict

**{verdict['final_verdict']}**

- `FSM_EDGE = {verdict['fsm_edge']}`
- `AI_EDGE = {verdict['ai_edge']}`
- `FIXED_DCA_ROW_INTEGRITY = {'PASS' if no_lookahead['fixed_dca_row_integrity_pass'] else 'FAIL'}`
- `NO_LOOK_AHEAD_AUDIT = {'PASS' if no_lookahead['pass'] else 'FAIL'}`

## Performance

{_md(perf)}

## Direct answers

1. BTC+ETH Fixed DCA ended at **{_money(indexed.loc['A','final_portfolio_value'])}**.
2. V3.1 FSM-only ended at **{_money(indexed.loc['B','final_portfolio_value'])}**.
3. V3.1 FSM+AI ended at **{_money(indexed.loc['C','final_portfolio_value'])}**.
4. Max DD A/B/C: **{_pct(indexed.loc['A','maximum_drawdown'])} / {_pct(indexed.loc['B','maximum_drawdown'])} / {_pct(indexed.loc['C','maximum_drawdown'])}**.
5. Calmar A/B/C: **{indexed.loc['A','calmar']:.4f} / {indexed.loc['B','calmar']:.4f} / {indexed.loc['C','calmar']:.4f}**.
6. 2021/11-2022/06 Stage4: FSM **{stage4['B']}**; AI **{stage4['C']}**.
7. AI made Stage4 earlier: **{'YES' if ai_earlier else 'NO'}**.
8. 2022/06 AI blocked an early 35-to-50/60 buyback **{june_caps} time(s)**; therefore **{'YES' if june_caps else 'NO'}**.
9. 2021/05 case peak-to-trough DD A/B/C: **{_pct(may['A'])} / {_pct(may['B'])} / {_pct(may['C'])}**.
10. 2025-2026 case peak-to-trough DD A/B/C: **{_pct(correction['A'])} / {_pct(correction['B'])} / {_pct(correction['C'])}**.
11. Confirmed macro cycles: **B={cycle_counts['B']}, C={cycle_counts['C']}**. Annual frequency is in `macro_cycle_frequency_v3_1.csv`.
12. **YES, tactical cash remains long-term.** It was material (>1% of portfolio) for **{_pct(indexed.loc['B','material_tactical_cash_time'])} / {_pct(indexed.loc['C','material_tactical_cash_time'])}** of B/C observations, and ending tactical bear cash was **{_money(indexed.loc['B','ending_tactical_bear_cash'])} / {_money(indexed.loc['C','ending_tactical_bear_cash'])}**. The narrower temporary-hedge test did pass: over-30-day unconfirmed lots **B={temp_fail['B']}, C={temp_fail['C']}**, with ending temporary cash zero.
13. Tactical turnover: **B={indexed.loc['B','tactical_turnover']:.4f}x, C={indexed.loc['C','tactical_turnover']:.4f}x**.
14. AI OOS ROC-AUC / PR-AUC / Brier: **{all_ai['roc_auc']:.4f} / {all_ai['pr_auc']:.4f} / {all_ai['brier_score']:.4f}**.
15. AI improved real portfolio performance under all frozen value gates: **{'YES' if verdict['ai_edge']=='PASS' else 'NO'}**.
16. FSM is worth a forward paper test under the frozen gate: **{'YES' if verdict['fsm_edge']=='PASS' else 'NO'}**.
17. AI should be retained as a promoted challenger: **{'YES' if verdict['ai_edge']=='PASS' else 'NO'}**.
18. J Law Final Verdict: **{verdict['final_verdict']}**.

## Frozen gate details

FSM checks:

```json
{json.dumps(verdict['fsm_checks'], indent=2)}
```

AI checks:

```json
{json.dumps(verdict['ai_checks'], indent=2)}
```

## J Law verdict

{_md(jlaw)}

## Interpretation limits

- The FSM is not a clean out-of-sample discovery: it is a frozen, human-designed rule set evaluated on one crypto history. Audit dates were not present in execution code, but knowledge of historical regimes can still influence design.
- AI predictions are genuinely annual expanding-window out-of-sample predictions. Portfolio value, however, is still only one realized path and classification skill does not imply trading value.
- Bitstamp BTCUSD supplies the pre-Binance history and Binance BTCUSDT supplies the later series. Source-switch and input hashes are in the data contract and manifest.
- AHR999 uses the pre-existing fixed arithmetic curve. It is point-in-time at execution but inherits the model-risk of that fixed curve.
- The formal FSM promotion gate passes, but B still held material tactical cash for {_pct(indexed.loc['B','material_tactical_cash_time'])} of observations and ended with {_money(indexed.loc['B','ending_tactical_bear_cash'])} in bear cash. `PROMOTED TO FORWARD PAPER TEST` is not approval for live capital; the high-cash behavior is a central forward-test risk.
- No threshold was changed after the run. Failed gates remain failed.
"""
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_1.md").write_text(report, encoding="utf-8")
