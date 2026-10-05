from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#8E8E8E", "A": "#4C78A8", "B": "#E45756", "J": "#54A24B"}


def _save(fig: plt.Figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=250, bbox_inches="tight")
    plt.close(fig)


def _actual_events(result: Any) -> pd.DataFrame:
    tactical = result.trades.loc[result.trades["action"].str.startswith("TACTICAL", na=False)].copy()
    if tactical.empty:
        return pd.DataFrame()
    tactical["timestamp"] = pd.to_datetime(tactical["timestamp"], utc=True)
    return tactical.groupby(
        ["tactical_event_id", "timestamp", "action", "side"], as_index=False, dropna=False,
    ).agg(gross_notional=("gross_notional_usd", "sum"))


def _bottom_zoom(
    output: Path,
    daily_by_model: dict[str, pd.DataFrame],
    model_b: Any,
    model_j: Any,
    overlay: pd.DataFrame,
    start: str,
    end: str,
    title: str,
) -> None:
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    reference = daily_by_model["B"].loc[lambda x: x["date"].between(start_ts, end_ts)]
    axes[0].plot(reference["date"], reference["BTC_close"], color="#222222", lw=1.25, label="BTC")
    for model in ("B", "J"):
        data = daily_by_model[model].loc[lambda x: x["date"].between(start_ts, end_ts)]
        axes[1].step(data["date"], 100 * data["crypto_exposure"], where="post", color=COLORS[model], lw=1.3, label=f"{model} actual exposure")
        axes[3].plot(data["date"], data["portfolio_value"], color=COLORS[model], lw=1.2, label=f"{model} value")
    axes[2].plot(reference["date"], reference["ahr999"], color="#6F4E7C", lw=1.15, label="AHR999")
    axes[2].axhline(0.35, color="black", ls="--", lw=0.8, label="V3.1 threshold")

    for model, result, marker in (("B", model_b, "o"), ("J", model_j, "^")):
        events = _actual_events(result)
        if events.empty:
            continue
        events = events.loc[events["timestamp"].between(start_ts, end_ts)]
        price_map = reference.set_index("date")["BTC_close"]
        for side, edge in (("BUY", "#157A35"), ("SELL", "#B01923")):
            points = events.loc[events["side"].eq(side)].copy()
            points["date"] = points["timestamp"].dt.floor("D")
            points["btc"] = points["date"].map(price_map)
            axes[0].scatter(points["timestamp"], points["btc"], marker=marker, s=48,
                            facecolors="none", edgecolors=edge, label=f"{model} executed {side}", zorder=5)
    decisions = overlay.loc[
        pd.to_datetime(overlay["timestamp"], utc=True).between(start_ts, end_ts)
        & overlay["overlay_decision"].isin(["DELAY", "CANCEL"])
    ].copy()
    decisions["timestamp"] = pd.to_datetime(decisions["timestamp"], utc=True)
    price_map = reference.set_index("date")["BTC_close"]
    decisions["btc"] = decisions["timestamp"].dt.floor("D").map(price_map)
    for decision, marker, color in (("DELAY", "x", "#F2A900"), ("CANCEL", "X", "#7B2CBF")):
        points = decisions.loc[decisions["overlay_decision"].eq(decision)]
        axes[0].scatter(points["timestamp"], points["btc"], marker=marker, s=58,
                        color=color, label=f"J AHR {decision.lower()}", zorder=6)
    axes[0].set_ylabel("BTC USD")
    axes[1].set_ylabel("Exposure %")
    axes[2].set_ylabel("AHR999")
    axes[3].set_ylabel("Portfolio USD")
    axes[3].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.23)
        ax.legend(fontsize=7, ncol=4)
    fig.suptitle(title)
    fig.tight_layout()
    _save(fig, output)


def create_v37_figures(
    output_dir: Path,
    daily_by_model: dict[str, pd.DataFrame],
    model_b: Any,
    model_j: Any,
    overlay: pd.DataFrame,
    parity: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    plt.style.use("default")
    models = ("H0", "A", "B", "J")

    fig, ax = plt.subplots(figsize=(13, 6))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], daily["portfolio_value"], color=COLORS[model], lw=1.25, label=model)
    ax.set(title="V3.7 Portfolio Equity: H0 / A / B / J", xlabel="UTC date", ylabel="Portfolio value (USD)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "01_equity_curve_v3_7.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["unit_nav"], color=COLORS[model], lw=1.2, label=model)
    ax.set(title="V3.7 Cash-flow-adjusted TWR growth (start = 100)", xlabel="UTC date", ylabel="TWR index")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "02_normalized_growth_v3_7.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["drawdown"], color=COLORS[model], lw=1.2, label=model)
    ax.set(title="V3.7 Drawdown", xlabel="UTC date", ylabel="Drawdown (%)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "03_drawdown_v3_7.png")

    _bottom_zoom(
        figure_dir / "04_2022_execution_overlay_v3_7.png", daily_by_model,
        model_b, model_j, overlay, "2022-06-01", "2022-07-31",
        "2022 bottom: V3.1 desired execution versus V3.7 overlay",
    )
    _bottom_zoom(
        figure_dir / "05_2026_execution_overlay_v3_7.png", daily_by_model,
        model_b, model_j, overlay, "2026-02-01", "2026-06-30",
        "2026 bottom: V3.1 desired execution versus V3.7 overlay",
    )

    monthly_frames = []
    for model, result in (("B", model_b), ("J", model_j)):
        events = _actual_events(result)
        if not events.empty:
            events["model"] = model
            events["series"] = f"{model} executed"
            monthly_frames.append(events[["timestamp", "series"]])
    restricted = overlay.loc[overlay["overlay_decision"].isin(["DELAY", "SUPPRESS"])].copy()
    restricted["timestamp"] = pd.to_datetime(restricted["timestamp"], utc=True)
    restricted["series"] = "J delayed/suppressed AHR"
    monthly_frames.append(restricted[["timestamp", "series"]])
    monthly = pd.concat(monthly_frames, ignore_index=True)
    monthly["month"] = monthly["timestamp"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby(["month", "series"], as_index=False).size().rename(columns={"size": "events"})
    pivot = monthly.pivot(index="month", columns="series", values="events").fillna(0)
    fig, ax = plt.subplots(figsize=(13, 5.5))
    styles = {"B executed": (COLORS["B"], "-"), "J executed": (COLORS["J"], "-"), "J delayed/suppressed AHR": ("#F2A900", "--")}
    for series, (color, linestyle) in styles.items():
        values = pivot[series] if series in pivot else pd.Series(0.0, index=pivot.index)
        ax.plot(pivot.index, values, color=color, ls=linestyle, marker="o", ms=2.4, lw=1.0, label=series)
    ax.set(title="Monthly tactical frequency at true event timestamps", xlabel="UTC month", ylabel="Events")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "06_tactical_frequency_v3_7.png")

    states = sorted(set(parity["B_macro_state"].dropna()) | set(parity["J_shadow_macro_state"].dropna()))
    codes = {state: index for index, state in enumerate(states)}
    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)
    axes[0].step(parity["date"], parity["B_macro_state"].map(codes), where="post", color=COLORS["B"], lw=2.0, label="B macro state")
    axes[0].step(parity["date"], parity["J_shadow_macro_state"].map(codes), where="post", color=COLORS["J"], lw=0.9, ls="--", label="J shadow state")
    axes[0].set_yticks(list(codes.values()), labels=list(codes.keys()))
    axes[1].step(parity["date"], parity["B_stage"], where="post", color=COLORS["B"], lw=2.0, label="B stage")
    axes[1].step(parity["date"], parity["J_shadow_stage"], where="post", color=COLORS["J"], lw=0.9, ls="--", label="J shadow stage")
    axes[1].set_ylabel("Stage"); axes[1].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.23); ax.legend()
    axes[0].set_title("V3.7 Shadow State Parity (lines must overlap)")
    fig.tight_layout()
    _save(fig, figure_dir / "07_shadow_state_parity_v3_7.png")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _signed_money(value: float) -> str:
    return f"{'-' if value < 0 else '+'}US${abs(value):,.2f}"


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


def write_v37_report(
    output_dir: Path,
    summary: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    bottom_summary: pd.DataFrame,
    tactical_stats: pd.DataFrame,
    event_audit: pd.DataFrame,
    integrity: dict[str, Any],
    replay: dict[str, Any],
    shadow_replay: dict[str, Any],
    parity_summary: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    perf = summary[[
        "model", "initial_capital", "external_contributions_after_inception",
        "final_portfolio_value", "xirr", "twr_cagr", "maximum_drawdown",
        "peak_date", "trough_date", "recovery_date", "sharpe", "sortino", "calmar",
        "average_crypto_exposure", "average_tactical_cash", "material_tactical_cash_time",
        "tactical_turnover", "tactical_event_count", "tactical_trade_count",
        "fees", "slippage", "total_trading_costs",
    ]].copy()
    for column in ("xirr", "twr_cagr", "maximum_drawdown", "average_crypto_exposure", "material_tactical_cash_time"):
        perf[column] = perf[column].map(_pct)
    for column in ("initial_capital", "external_contributions_after_inception", "final_portfolio_value", "average_tactical_cash", "fees", "slippage", "total_trading_costs"):
        perf[column] = perf[column].map(_money)
    for column in ("sharpe", "sortino", "calmar"):
        perf[column] = perf[column].map(lambda value: f"{value:.4f}")
    perf["tactical_turnover"] = perf["tactical_turnover"].map(lambda value: f"{value:.4f}x")
    indexed = summary.set_index("model")
    comp = comparison.iloc[0]
    bottom = bottom_summary.set_index(["period", "model"])
    event = event_audit.set_index(["event", "model"])
    tactical = tactical_stats.set_index("model")

    def count(period: str, model: str, column: str = "tactical_event_count") -> int:
        return int(bottom.loc[(period, model), column])

    def dd(name: str, model: str) -> float:
        return float(event.loc[(name, model), "peak_to_trough_drawdown"])

    mismatch_total = sum(value for key, value in parity_summary.items() if key.endswith("_mismatch_days"))
    answers = [
        f"1. B V3.1 完整重現：**{'PASS' if replay['pass'] else 'FAIL'}**；Final {_money(indexed.loc['B','final_portfolio_value'])}、CAGR {_pct(indexed.loc['B','twr_cagr'])}、Max DD {_pct(indexed.loc['B','maximum_drawdown'])}、106 events。",
        f"2. Shadow State mismatch 合計：**{mismatch_total} 天**；六項 parity 明細皆列於 audit。",
        f"3. Stage mismatch：**{parity_summary['stage_mismatch_days']} 天**。",
        f"4. 獨立 Shadow Engine 對 B 的完整 history/trade replay：**{'PASS' if shadow_replay['pass'] else 'FAIL'}**。",
        f"5. Overlay 限制範圍：**{'PASS' if scope['pass'] else 'FAIL'}**；非 AHR 被限制 {scope['restricted_non_ahr_rows']} 筆。另有 {scope['risk_sell_execute_no_fill_at_unchanged_target_count']} 個 Risk Sell 依原 target 執行，但因 J 已低於 target 而無成交；這不是 suppression。",
        f"6. J Final Portfolio Value：**{_money(indexed.loc['J','final_portfolio_value'])}**；較 B {_signed_money(comp['delta_final_value'])}。",
        f"7. J TWR CAGR：**{_pct(indexed.loc['J','twr_cagr'])}**；較 B {comp['delta_cagr_percentage_points']:.2f} 個百分點。",
        f"8. J Max DD：**{_pct(indexed.loc['J','maximum_drawdown'])}**；相對 B 變化 {comp['delta_max_drawdown_percentage_points']:.2f} 個百分點。",
        f"9. J Calmar：**{indexed.loc['J','calmar']:.4f}**；較 B {comp['delta_calmar']:.4f}。",
        f"10. 2022 Bottom events B/J：**{count('BOTTOM_2022','B')} / {count('BOTTOM_2022','J')}**；下降 {_pct(comp['bottom_2022_event_reduction_fraction'])}。",
        f"11. 2026 Bottom events B/J：**{count('BOTTOM_2026','B')} / {count('BOTTOM_2026','J')}**；下降 {_pct(comp['bottom_2026_event_reduction_fraction'])}。",
        f"12. 全期 7 日 Whipsaw pairs B/J：**{count('FULL','B','whipsaw_pair_count')} / {count('FULL','J','whipsaw_pair_count')}**；下降 {_pct(comp['whipsaw_pair_reduction_fraction'])}。",
        f"13. Tactical Turnover B/J：**{tactical.loc['B','tactical_turnover']:.4f}x / {tactical.loc['J','tactical_turnover']:.4f}x**；下降 {_pct(comp['overall_turnover_reduction_fraction'])}。",
        f"14. 2021-11→2022-06 DD B/J：**{_pct(dd('BEAR_2021NOV_2022JUN','B'))} / {_pct(dd('BEAR_2021NOV_2022JUN','J'))}**。",
        f"15. 2025→截止日 DD B/J：**{_pct(dd('CORRECTION_2025_2026','B'))} / {_pct(dd('CORRECTION_2025_2026','J'))}**。",
        f"16. COVID DD B/J：**{_pct(dd('COVID_2020','B'))} / {_pct(dd('COVID_2020','J'))}**。",
        f"17. 2021 May DD B/J：**{_pct(dd('MAY_2021','B'))} / {_pct(dd('MAY_2021','J'))}**。",
        f"18. J AHR：requested **{int(indexed.loc['J','requested_ahr_buys'])}**、executed **{int(indexed.loc['J','executed_ahr_buys'])}**、delayed **{int(indexed.loc['J','delayed_ahr_buys'])}**、cancelled **{int(indexed.loc['J','cancelled_ahr_buys'])}**、duplicate suppressed **{int(indexed.loc['J','duplicate_ahr_suppressions'])}**。",
        f"19. Fixed DCA 逐筆一致：**{'PASS' if integrity['checks']['fixed_dca_row_integrity'] else 'FAIL'}**；同 timestamp tactical 買賣衝突 {integrity['same_timestamp_opposite_tactical_action_violations']} 次。",
        f"20. NO_LOOK_AHEAD / EXECUTION_INTEGRITY：**{'PASS' if integrity['no_lookahead_pass'] else 'FAIL'} / {'PASS' if integrity['execution_integrity_pass'] else 'FAIL'}**。30% DD 沒有進入本輪交易或 Promotion Gate。",
        f"21. 最終分類：**{verdict['final_verdict']}**。",
    ]
    report = f"""# BTC+ETH Macro Hedge V3.7

## 最終判決

**{verdict['final_verdict']}**

- `PROMOTION_GATE = {verdict['promotion_gate']}`
- `V3_1_REPLAY_INTEGRITY = {'PASS' if replay['pass'] else 'FAIL'}`
- `SHADOW_ENGINE_REPLAY = {'PASS' if shadow_replay['pass'] else 'FAIL'}`
- `V3_7_ISOLATION_AUDIT = {'PASS' if parity_summary['pass'] else 'FAIL'}`
- `FIXED_DCA_ROW_INTEGRITY = {'PASS' if integrity['checks']['fixed_dca_row_integrity'] else 'FAIL'}`
- `OVERLAY_SCOPE_AUDIT = {'PASS' if scope['pass'] else 'FAIL'}`
- `NO_LOOK_AHEAD = {'PASS' if integrity['no_lookahead_pass'] else 'FAIL'}`
- `EXECUTION_INTEGRITY = {'PASS' if integrity['execution_integrity_pass'] else 'FAIL'}`
- `FSM_AUDIT = {'PASS' if integrity['checks']['fsm_legal'] else 'FAIL'}`

## 績效

{_md(perf)}

## 21 個直接回答

{chr(10).join(answers)}

## Frozen Promotion Gates

```json
{json.dumps(verdict['checks'], indent=2, ensure_ascii=False)}
```

## B vs J

{_md(comparison)}

## Bottom / Whipsaw

{_md(bottom_summary)}

## Event Drawdown

{_md(event_audit)}

## 限制與偏差

- V3.7 的市場判斷來自另一個獨立執行的原始 V3.1 Shadow Engine；實際 J 持倉只影響成交量，沒有回傳 State、Stage、Cycle 或 Target。
- B 保留原始 V3.1 bar 內順序；J 依本次規格使用 DCA-first。Fixed DCA 逐筆仍須完全相同，但這個微小順序差異應列入歸因。
- Pending AHR 僅在 completed AHR999 仍低於 frozen threshold，且 Shadow state 為 BEAR、DEEP_BEAR 或 ACCUMULATION 時成交；Right-side 與 NEW_BULL 會取消 pending 並原樣執行。
- 本研究只用一條已實現的加密貨幣歷史路徑。Freeze-first 可避免本輪結果後調參，但無法消除研究問題本身受已知歷史行情啟發的 selection bias。
- 手續費、滑價與 minimum notional 是固定模型假設；未納入極端價差、容量、稅務、託管與交易、交易所故障等風險。
- Promotion 只代表符合 frozen 歷史 gate，可進入 forward paper test；不代表可投入實盤。沒有因失敗 gate 修改 threshold，也沒有建立 V3.8。
"""
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_7.md").write_text(report, encoding="utf-8")
    (output_dir / "FINAL_REPORT_V3_7.md").write_text(report, encoding="utf-8")


__all__ = ["create_v37_figures", "write_v37_report"]
