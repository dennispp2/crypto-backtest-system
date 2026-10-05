from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import pandas as pd

from .v38_analysis import actual_tactical_events


COLORS = {
    "H0": "#8E8E8E", "A": "#4C78A8", "B": "#E45756",
    "J7": "#B279A2", "K": "#54A24B",
}


def _save(fig: plt.Figure, png_path: Path) -> None:
    png_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=300, bbox_inches="tight")
    fig.savefig(png_path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def _bottom_zoom(
    output: Path,
    daily_by_model: dict[str, pd.DataFrame],
    result_map: dict[str, Any],
    k_overlay: pd.DataFrame,
    start: str,
    end: str,
    title: str,
) -> None:
    start_ts, end_ts = pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC")
    fig, axes = plt.subplots(4, 1, figsize=(14, 12), sharex=True)
    reference = daily_by_model["B"].loc[lambda x: x["date"].between(start_ts, end_ts)]
    axes[0].plot(reference["date"], reference["BTC_close"], color="#222222", lw=1.25, label="BTC")
    for model in ("B", "J7", "K"):
        daily = daily_by_model[model].loc[lambda x: x["date"].between(start_ts, end_ts)]
        axes[1].step(daily["date"], 100 * daily["crypto_exposure"], where="post",
                     color=COLORS[model], lw=1.15, label=f"{model} exposure")
        axes[3].plot(daily["date"], daily["portfolio_value"],
                     color=COLORS[model], lw=1.15, label=f"{model} value")
    axes[2].plot(reference["date"], reference["ahr999"], color="#6F4E7C", lw=1.15, label="AHR999")
    axes[2].axhline(0.35, color="black", ls="--", lw=0.8, label="V3.1 threshold")

    price_map = reference.set_index("date")["BTC_close"]
    markers = {"B": "o", "J7": "s", "K": "^"}
    for model in ("B", "J7", "K"):
        events = actual_tactical_events(result_map[model])
        events = events.loc[events["timestamp"].between(start_ts, end_ts)].copy()
        events["btc"] = events["timestamp"].dt.floor("D").map(price_map)
        for side, edge in (("BUY", "#157A35"), ("SELL", "#B01923")):
            points = events.loc[events["side"].eq(side)]
            axes[0].scatter(
                points["timestamp"], points["btc"], marker=markers[model], s=42,
                facecolors="none", edgecolors=edge, label=f"{model} executed {side}", zorder=5,
            )
    decisions = k_overlay.loc[
        pd.to_datetime(k_overlay["timestamp"], utc=True).between(start_ts, end_ts)
        & k_overlay["overlay_decision"].isin(["DELAY", "CANCEL"])
    ].copy()
    decisions["timestamp"] = pd.to_datetime(decisions["timestamp"], utc=True)
    decisions["btc"] = decisions["timestamp"].dt.floor("D").map(price_map)
    original_delay = decisions.loc[
        decisions["overlay_decision"].eq("DELAY")
        & decisions["shadow_action"].ne("PENDING_AHR_BUY")
    ]
    pending = decisions.loc[
        decisions["overlay_decision"].eq("DELAY")
        & decisions["shadow_action"].eq("PENDING_AHR_BUY")
    ]
    cancelled = decisions.loc[decisions["overlay_decision"].eq("CANCEL")]
    axes[0].scatter(original_delay["timestamp"], original_delay["btc"], marker="x", s=55,
                    color="#F2A900", label="K delayed AHR", zorder=6)
    axes[0].scatter(pending["timestamp"], pending["btc"], marker=".", s=24,
                    color="#FFBF00", label="K pending AHR", zorder=6)
    axes[0].scatter(cancelled["timestamp"], cancelled["btc"], marker="X", s=55,
                    color="#7B2CBF", label="K cancelled AHR", zorder=6)
    axes[0].set_ylabel("BTC USD")
    axes[1].set_ylabel("Exposure %")
    axes[2].set_ylabel("AHR999")
    axes[3].set_ylabel("Portfolio USD")
    axes[3].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.23)
        ax.legend(fontsize=6.7, ncol=4)
    fig.suptitle(title)
    fig.tight_layout()
    _save(fig, output)


def create_v38_figures(
    output_dir: Path,
    daily_by_model: dict[str, pd.DataFrame],
    result_map: dict[str, Any],
    k_overlay: pd.DataFrame,
    parity: pd.DataFrame,
) -> None:
    figure_dir = output_dir / "figures"
    models = ("H0", "A", "B", "J7", "K")
    plt.style.use("default")

    fig, ax = plt.subplots(figsize=(13, 6))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], daily["portfolio_value"], color=COLORS[model], lw=1.2, label=model)
    ax.set(title="V3.8 Portfolio Equity: H0 / A / B / J7 / K", xlabel="UTC date", ylabel="Portfolio value (USD)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "01_equity_curve_v3_8.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["unit_nav"], color=COLORS[model], lw=1.15, label=model)
    ax.set(title="V3.8 Cash-flow-adjusted TWR growth (start = 100)", xlabel="UTC date", ylabel="TWR index")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "02_normalized_growth_v3_8.png")

    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in models:
        daily = daily_by_model[model]
        ax.plot(daily["date"], 100 * daily["drawdown"], color=COLORS[model], lw=1.15, label=model)
    ax.set(title="V3.8 Drawdown", xlabel="UTC date", ylabel="Drawdown (%)")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "03_drawdown_v3_8.png")

    _bottom_zoom(
        figure_dir / "04_2022_overlay_v3_8.png", daily_by_model, result_map,
        k_overlay, "2022-06-01", "2022-07-31",
        "2022 bottom: B versus J7 versus K execution",
    )
    _bottom_zoom(
        figure_dir / "05_2026_overlay_v3_8.png", daily_by_model, result_map,
        k_overlay, "2026-02-01", "2026-06-30",
        "2026 bottom: B versus J7 versus K execution",
    )

    monthly_frames = []
    for model in ("B", "J7", "K"):
        events = actual_tactical_events(result_map[model])
        events["series"] = f"{model} events"
        monthly_frames.append(events[["timestamp", "series"]])
    monthly = pd.concat(monthly_frames, ignore_index=True)
    monthly["month"] = monthly["timestamp"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
    monthly = monthly.groupby(["month", "series"], as_index=False).size().rename(columns={"size": "events"})
    pivot = monthly.pivot(index="month", columns="series", values="events").fillna(0)
    fig, ax = plt.subplots(figsize=(13, 5.5))
    for model in ("B", "J7", "K"):
        series = f"{model} events"
        values = pivot[series] if series in pivot else pd.Series(0.0, index=pivot.index)
        ax.plot(pivot.index, values, color=COLORS[model], marker="o", ms=2.4, lw=1.0, label=series)
    ax.set(title="Monthly tactical event frequency", xlabel="UTC month", ylabel="Executed events")
    ax.grid(alpha=0.25); ax.legend()
    _save(fig, figure_dir / "06_tactical_frequency_v3_8.png")

    states = sorted(set(parity["B_macro_state"].dropna()) | set(parity["J_shadow_macro_state"].dropna()))
    codes = {state: index for index, state in enumerate(states)}
    fig, axes = plt.subplots(3, 1, figsize=(13, 9), sharex=True)
    axes[0].step(parity["date"], parity["B_macro_state"].map(codes), where="post",
                 color=COLORS["B"], lw=2.0, label="B state")
    axes[0].step(parity["date"], parity["J_shadow_macro_state"].map(codes), where="post",
                 color=COLORS["K"], lw=0.9, ls="--", label="K shadow state")
    axes[0].set_yticks(list(codes.values()), labels=list(codes.keys()))
    axes[1].step(parity["date"], parity["B_stage"], where="post", color=COLORS["B"], lw=2.0, label="B stage")
    axes[1].step(parity["date"], parity["J_shadow_stage"], where="post", color=COLORS["K"], lw=0.9, ls="--", label="K shadow stage")
    axes[2].step(parity["date"], parity["B_cycle_id"], where="post", color=COLORS["B"], lw=2.0, label="B cycle")
    axes[2].step(parity["date"], parity["J_shadow_cycle_id"], where="post", color=COLORS["K"], lw=0.9, ls="--", label="K shadow cycle")
    axes[1].set_ylabel("Stage"); axes[2].set_ylabel("Cycle ID"); axes[2].set_xlabel("UTC date")
    for ax in axes:
        ax.grid(alpha=0.23); ax.legend()
    axes[0].set_title("V3.8 Shadow State Parity (lines must overlap)")
    fig.tight_layout()
    _save(fig, figure_dir / "07_shadow_state_parity_v3_8.png")


def _money(value: float) -> str:
    return f"US${value:,.2f}"


def _signed_money(value: float) -> str:
    return f"{'-' if value < 0 else '+'}US${abs(value):,.2f}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _signed_pct(value: float) -> str:
    return f"{100 * value:+.2f}%"


def _md(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "(no rows)"
    return "\n".join([
        "| " + " | ".join(frame.columns.astype(str)) + " |",
        "| " + " | ".join(["---"] * len(frame.columns)) + " |",
        *["| " + " | ".join(str(value) for value in row) + " |" for row in frame.itertuples(index=False, name=None)],
    ])


def write_v38_report(
    output_dir: Path,
    summary: pd.DataFrame,
    tactical: pd.DataFrame,
    comparison: pd.DataFrame,
    verdict: dict[str, Any],
    j_law: dict[str, Any],
    bottom: pd.DataFrame,
    events: pd.DataFrame,
    opportunity: dict[str, Any],
    integrity: dict[str, Any],
    replay_b: dict[str, Any],
    replay_j7: dict[str, Any],
    shadow_replay: dict[str, Any],
    parity: dict[str, Any],
    scope: dict[str, Any],
) -> None:
    perf_index = summary.set_index("model")
    stats = tactical.set_index("model")
    comp = comparison.iloc[0]
    event_index = events.set_index(["event", "model"])
    bottom_index = bottom.set_index(["period", "model"])

    def values(column: str) -> str:
        return " / ".join(str(perf_index.loc[m, column]) for m in ("B", "J7", "K"))

    def money_values(column: str) -> str:
        return " / ".join(_money(float(perf_index.loc[m, column])) for m in ("B", "J7", "K"))

    def pct_values(column: str) -> str:
        return " / ".join(_pct(float(perf_index.loc[m, column])) for m in ("B", "J7", "K"))

    def stat_values(column: str, suffix: str = "") -> str:
        return " / ".join(f"{float(stats.loc[m, column]):.4f}{suffix}" for m in ("B", "J7", "K"))

    def event_dd(name: str, model: str) -> float:
        return float(event_index.loc[(name, model), "peak_to_trough_drawdown"])

    def bottom_count(period: str, model: str) -> int:
        return int(bottom_index.loc[(period, model), "tactical_event_count"])

    mismatch_total = sum(value for key, value in parity.items() if key.endswith("_mismatch_days"))
    cost_saved = float(perf_index.loc["B", "total_trading_costs"] - perf_index.loc["K", "total_trading_costs"])
    wealth_lost = float(perf_index.loc["B", "final_portfolio_value"] - perf_index.loc["K", "final_portfolio_value"])
    b2022, k2022 = bottom_count("BOTTOM_2022", "B"), bottom_count("BOTTOM_2022", "K")
    b2026, k2026 = bottom_count("BOTTOM_2026", "B"), bottom_count("BOTTOM_2026", "K")
    covid_guardrail = event_dd("COVID_2020", "K") >= event_dd("COVID_2020", "B") - 0.02
    may_guardrail = event_dd("MAY_2021", "K") >= event_dd("MAY_2021", "B") - 0.02
    answers = [
        f"1. B 完整重現：**{'PASS' if replay_b['pass'] else 'FAIL'}**。",
        f"2. J7 完整重現：**{'PASS' if replay_j7['pass'] else 'FAIL'}**。",
        f"3. K Shadow State mismatch：**{mismatch_total} 天**。",
        f"4. Stage mismatch：**{parity['stage_mismatch_days']} 天**。",
        f"5. Cycle mismatch：**{parity['cycle_mismatch_days']} 天**。",
        f"6. 非 AHR 被限制：**{scope['restricted_non_ahr_rows']} 筆**；Overlay Scope {'PASS' if scope['pass'] else 'FAIL'}。",
        f"7. B / J7 / K 最終資產：**{money_values('final_portfolio_value')}**。",
        f"8. B / J7 / K CAGR：**{pct_values('twr_cagr')}**。",
        f"9. B / J7 / K Max DD：**{pct_values('maximum_drawdown')}**。",
        f"10. B / J7 / K Tactical Events：**{' / '.join(str(int(stats.loc[m, 'total_tactical_events'])) for m in ('B', 'J7', 'K'))}**。",
        f"11. B / J7 / K Turnover：**{stat_values('tactical_turnover', 'x')}**。",
        f"12. K 相較 B 的 3-close Whipsaw 減少：**{_pct(comp['short_three_close_whipsaw_reduction_fraction'])}**。",
        f"13. K 相較 B 的 7-day Whipsaw 減少：**{_pct(comp['seven_calendar_day_whipsaw_reduction_fraction'])}**。",
        f"14. 2022 Bottom events：B {b2022}、K {k2022}，減少 **{_pct(1-k2022/b2022)}**。",
        f"15. 2026 Bottom events：B {b2026}、K {k2026}，減少 **{_pct(1-k2026/b2026)}**。",
        f"16. 2022 Bear DD B/K：**{_pct(event_dd('BEAR_2021NOV_2022JUN','B'))} / {_pct(event_dd('BEAR_2021NOV_2022JUN','K'))}**，Guardrail {'PASS' if verdict['checks']['G6_2022_BEAR_DD_REGRESSION_LTE_2PP'] else 'FAIL'}。",
        f"17. 2025→26 DD B/K：**{_pct(event_dd('CORRECTION_2025_2026','B'))} / {_pct(event_dd('CORRECTION_2025_2026','K'))}**，Guardrail {'PASS' if verdict['checks']['G7_2025_2026_DD_REGRESSION_LTE_2PP'] else 'FAIL'}。",
        f"18. COVID B/K：{_pct(event_dd('COVID_2020','B'))} / {_pct(event_dd('COVID_2020','K'))}，{'PASS' if covid_guardrail else 'FAIL'}；May B/K：{_pct(event_dd('MAY_2021','B'))} / {_pct(event_dd('MAY_2021','K'))}，{'PASS' if may_guardrail else 'FAIL'}。",
        f"19. 延後成交平均價格差：BTC **{_signed_pct(opportunity['average_btc_price_cost_fraction'])}**、ETH **{_signed_pct(opportunity['average_eth_price_cost_fraction'])}**；正值代表買貴。",
        f"20. 相較 B 節省交易成本：**{_money(cost_saved)}**。",
        f"21. 相較 B 損失最終資產：**{_money(wealth_lost)}**，等於 B 的 {_pct(wealth_lost/perf_index.loc['B','final_portfolio_value'])}。",
        f"22. K Final >=98% B：**{'PASS' if verdict['checks']['G10_FINAL_VALUE_GTE_98PCT_OF_B'] else 'FAIL'}**；實際 {_pct(comp['final_value_fraction_of_b'])}。",
        f"23. 少交易＋幾乎不犧牲資產＋不改 V3.1 大腦：**{'YES' if verdict['promotion_gate']=='PASS' else 'NO'}**；State isolation 本身 {'PASS' if parity['pass'] else 'FAIL'}。",
        f"24. K 是否值得取代 V3.1：**{'YES' if verdict['final_verdict'].startswith('A.') else 'NO'}**；正式判決為 {verdict['final_verdict']}。",
    ]

    perf = summary[[
        "model", "final_portfolio_value", "xirr", "twr_cagr", "maximum_drawdown",
        "peak_date", "trough_date", "recovery_date", "sharpe", "sortino", "calmar",
        "tactical_event_count", "tactical_turnover", "total_trading_costs",
        "average_crypto_exposure", "material_tactical_cash_time",
    ]].copy()
    for column in ("xirr", "twr_cagr", "maximum_drawdown", "average_crypto_exposure", "material_tactical_cash_time"):
        perf[column] = perf[column].map(_pct)
    for column in ("final_portfolio_value", "total_trading_costs"):
        perf[column] = perf[column].map(_money)
    for column in ("sharpe", "sortino", "calmar"):
        perf[column] = perf[column].map(lambda value: f"{value:.4f}")
    perf["tactical_turnover"] = perf["tactical_turnover"].map(lambda value: f"{value:.4f}x")
    law = pd.DataFrame([{"Item": key, "Result": value} for key, value in j_law.items()])
    overlay_summary = pd.DataFrame([{
        "AHR Requested": opportunity["ahr_requested_shadow_events"],
        "AHR Delayed": opportunity["ahr_delayed_shadow_requests"],
        "AHR Executed after Delay": opportunity["ahr_executed_after_delay"],
        "AHR Cancelled": opportunity["ahr_cancelled_pending_requests"],
        "AHR Executed without Delay": opportunity["ahr_executed_without_delay"],
        "Average Delay (Completed Closes)": opportunity["average_delay_completed_closes"],
        "Median Delay (Completed Closes)": opportunity["median_delay_completed_closes"],
        "Average BTC Price Cost": _signed_pct(opportunity["average_btc_price_cost_fraction"]),
        "Average ETH Price Cost": _signed_pct(opportunity["average_eth_price_cost_fraction"]),
        "Average BTC 30d Forward Return": _signed_pct(opportunity["average_30d_btc_return_after_original_signal"]),
        "Average BTC 60d Forward Return": _signed_pct(opportunity["average_60d_btc_return_after_original_signal"]),
    }])
    report = f"""# BTC+ETH Macro Hedge V3.8

## 最終判決

**{verdict['final_verdict']}**

- `PROMOTION_GATE = {verdict['promotion_gate']}`
- `V3_1_REPLAY_INTEGRITY = {'PASS' if replay_b['pass'] else 'FAIL'}`
- `V3_7_J7_REPLAY_INTEGRITY = {'PASS' if replay_j7['pass'] else 'FAIL'}`
- `SHADOW_ENGINE_REPLAY = {'PASS' if shadow_replay['pass'] else 'FAIL'}`
- `V3_8_ISOLATION_AUDIT = {'PASS' if parity['pass'] else 'FAIL'}`
- `OVERLAY_SCOPE_AUDIT = {'PASS' if scope['pass'] else 'FAIL'}`
- `NO_LOOK_AHEAD = {'PASS' if integrity['no_lookahead_pass'] else 'FAIL'}`
- `EXECUTION_INTEGRITY = {'PASS' if integrity['execution_integrity_pass'] else 'FAIL'}`

## 績效

{_md(perf)}

## K AHR Overlay 統計

{_md(overlay_summary)}

## 24 個直接回答

{chr(10).join(answers)}

## Frozen Promotion Gates

```json
{json.dumps(verdict['checks'], indent=2, ensure_ascii=False)}
```

## J Law Verdict

{_md(law)}

## K vs B

{_md(comparison)}

## Bottom / Whipsaw

{_md(bottom)}

## Event Drawdown

{_md(events)}

## 限制與偏差

- K 僅限制 V3.1 `TACTICAL_BUYBACK_AHR999_TO_35`；Shadow State、Stage、Cycle、Target、Crash、Right-side、NEW_BULL 與 Risk Sell 均未改動。
- Cooldown 使用新完成日線訊號計數，不以 72 小時近似。B 與 K 的每個新 signal 仍在下一個可交易 4H open 執行。
- Risk Sell 若因 K 已低於原 target 而 0 成交，仍記為 `EXECUTE / NO_TRADE_ALREADY_BELOW_TARGET`，不計為 suppression。
- 30/60 日 forward return 只存在 opportunity-cost 報表，從未進入交易引擎。這些是事後歸因，不能解讀為可交易訊號。
- 本研究只有一條已實現歷史路徑。雖然本輪 freeze-first 且不調參，從 7 日縮短為 3 closes 的研究問題仍受 V3.7 已知結果啟發，具有 sequential testing 與 selection bias。
- 模擬未涵蓋極端 spread、容量、稅務、託管或交易所故障。Promotion 只代表可進 forward paper test，不等於可投入實盤。
- 初步執行曾發現 cooldown 邊界 off-by-one，該次結果已作廢並保留稽核檔；正式結果使用原先凍結的「第 1、2、3 close 均禁止，第 4 日才可執行」規格，沒有更改策略參數或 gate。
- 沒有依結果修改 threshold，也沒有建立 V3.9。
"""
    report_dir = output_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3_8.md").write_text(report, encoding="utf-8")
    (output_dir / "FINAL_REPORT_V3_8.md").write_text(report, encoding="utf-8")


__all__ = ["create_v38_figures", "write_v38_report"]
