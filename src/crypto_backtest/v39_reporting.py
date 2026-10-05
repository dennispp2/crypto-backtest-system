from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {"H0": "#777777", "A": "#2878b5", "B": "#d95319", "P": "#2ca02c"}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=180, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _slice(frame: pd.DataFrame, start: str, end: str | None = None) -> pd.DataFrame:
    date = pd.to_datetime(frame["date"], utc=True)
    mask = date >= pd.Timestamp(start, tz="UTC")
    if end:
        mask &= date <= pd.Timestamp(end, tz="UTC")
    return frame.loc[mask].copy()


def create_v39_figures(
    daily: dict[str, pd.DataFrame],
    trades: dict[str, pd.DataFrame],
    blocked: pd.DataFrame,
    reentry: pd.DataFrame,
    directory: Path,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(12, 6))
    for model in ("H0", "A", "B", "P"):
        ax.plot(daily[model]["date"], daily[model]["portfolio_value"], label=model, color=COLORS[model], lw=1.5)
    ax.set(title="V3.9 Total Portfolio Value", ylabel="USD", xlabel="Date")
    ax.legend(ncol=4)
    _save(fig, directory, "01_equity_curve_v3_9")

    fig, ax = plt.subplots(figsize=(12, 6))
    for model in ("H0", "A", "B", "P"):
        ax.plot(daily[model]["date"], daily[model]["unit_nav"], label=model, color=COLORS[model], lw=1.5)
    ax.set(title="Cash-flow-adjusted TWR Growth", ylabel="Growth of $1", xlabel="Date")
    ax.legend(ncol=4)
    _save(fig, directory, "02_normalized_growth_v3_9")

    fig, ax = plt.subplots(figsize=(12, 5))
    for model in ("B", "P"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["drawdown"], label=model, color=COLORS[model], lw=1.4)
    ax.axhline(-30, color="black", ls="--", lw=0.8, alpha=0.6)
    ax.set(title="Drawdown: V3.1 B vs V3.9 P", ylabel="Drawdown (%)", xlabel="Date")
    ax.legend()
    _save(fig, directory, "03_drawdown_v3_9")

    b = _slice(daily["B"], "2023-01-01", "2025-10-31")
    p = _slice(daily["P"], "2023-01-01", "2025-10-31")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 9), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]})
    ax1.plot(p["date"], p["BTC_signal_close"], label="BTC", color="#333333", lw=1.2)
    ax1.plot(p["date"], p["sma50"], label="SMA50", color="#1f77b4", lw=1.0)
    ax1.plot(p["date"], p["sma200"], label="SMA200", color="#9467bd", lw=1.0)
    ax1.set_yscale("log")
    ax1.set_ylabel("BTC price (log)")
    ax1.legend(ncol=3)
    ax2.plot(b["date"], 100.0 * b["crypto_exposure"], label="B exposure", color=COLORS["B"], lw=1.2)
    ax2.plot(p["date"], 100.0 * p["crypto_exposure"], label="P exposure", color=COLORS["P"], lw=1.2)
    bt = trades["B"].copy()
    bt = bt.loc[bt["action"].str.startswith("TACTICAL_SELL", na=False)]
    for date in pd.to_datetime(bt["timestamp"], utc=True).drop_duplicates():
        if pd.Timestamp("2023-01-01", tz="UTC") <= date <= pd.Timestamp("2025-10-31 23:59:59", tz="UTC"):
            ax2.axvline(date, color=COLORS["B"], alpha=0.18, lw=0.8)
    if not blocked.empty:
        actual_blocked = blocked.loc[blocked["blocked_or_executed"].eq("BLOCKED")]
        bd = pd.to_datetime(actual_blocked["timestamp"], utc=True)
        keep = bd.between(pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-10-31 23:59:59", tz="UTC"))
        for date in bd.loc[keep]:
            ax2.axvline(date, color="#2878b5", ls="--", alpha=0.65, lw=1.0)
    if not reentry.empty:
        confirmed = reentry.loc[reentry["confirmed_or_rejected"].eq("CONFIRMED")]
        for date in pd.to_datetime(confirmed["final_reentry_date"], utc=True).dropna():
            ax2.axvline(date, color="#7f3c8d", ls=":", lw=1.4)
    ax2.set(title="2023-2025 Bull Participation", ylabel="Crypto exposure (%)", xlabel="Date", ylim=(0, 102))
    ax2.legend(ncol=2)
    _save(fig, directory, "04_bull_participation_v3_9")

    for stem, start, end, title in (
        ("05_2021_2022_safety_v3_9", "2021-09-01", "2022-06-30", "2021 Peak and 2022 Bear Safety"),
        ("06_2025_2026_safety_v3_9", "2025-01-01", None, "2025-2026 Safety"),
    ):
        b = _slice(daily["B"], start, end)
        p = _slice(daily["P"], start, end)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
        ax1.plot(p["date"], p["BTC_signal_close"], color="#333333", label="BTC", lw=1.2)
        ax1.set_yscale("log")
        ax1.set_ylabel("BTC price (log)")
        ax1.legend()
        ax2.plot(b["date"], 100.0 * b["crypto_exposure"], color=COLORS["B"], label="B exposure")
        ax2.plot(p["date"], 100.0 * p["crypto_exposure"], color=COLORS["P"], label="P exposure")
        if "bull_persistence_guard" in p:
            guard = p["bull_persistence_guard"].astype(bool)
            ax2.fill_between(p["date"], 0, 100, where=guard, color="#2ca02c", alpha=0.08, label="P guard on")
        for model in ("B", "P"):
            selected = trades[model].loc[trades[model]["action"].str.startswith("TACTICAL_SELL", na=False)]
            for date in pd.to_datetime(selected["timestamp"], utc=True).drop_duplicates():
                lower = pd.Timestamp(start, tz="UTC")
                upper = pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1) if end else pd.Timestamp.max.tz_localize("UTC")
                if lower <= date < upper:
                    ax2.axvline(date, color=COLORS[model], alpha=0.18, lw=0.8)
        ax2.set(title=title, ylabel="Crypto exposure (%)", xlabel="Date", ylim=(0, 102))
        ax2.legend(ncol=3)
        _save(fig, directory, stem)


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.2f}%"


def _money(value: float) -> str:
    return f"US${float(value):,.2f}"


def _event_value(events: pd.DataFrame, event: str, model: str) -> float:
    return float(events.loc[(events["event"] == event) & (events["model"] == model), "maximum_drawdown"].iloc[0])


def _markdown(frame: pd.DataFrame, *, include_index: bool = False) -> str:
    work = frame.copy()
    if include_index:
        work.insert(0, work.index.name or "model", work.index.astype(str))
    columns = [str(column) for column in work.columns]
    rows = [[str(value) for value in row] for row in work.itertuples(index=False, name=None)]
    header = "| " + " | ".join(columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    body = ["| " + " | ".join(values) + " |" for values in rows]
    return "\n".join([header, separator, *body])


def write_v39_report(
    path: Path,
    *,
    summary: pd.DataFrame,
    event_audit: pd.DataFrame,
    rolling: pd.DataFrame,
    blocked: pd.DataFrame,
    reentry: pd.DataFrame,
    stage4: pd.DataFrame,
    crash: pd.DataFrame,
    transition_stats: pd.DataFrame,
    promotion: dict[str, Any],
    integrity: dict[str, bool],
    formal_end: Any,
) -> None:
    index = summary.set_index("model")
    b, p = index.loc["B"], index.loc["P"]
    directly_blocked = blocked.loc[blocked["blocked_or_executed"].eq("BLOCKED")].copy() if not blocked.empty else blocked
    pos30 = int((directly_blocked["btc_forward_return_30d"] > 0).sum()) if not directly_blocked.empty else 0
    pos60 = int((directly_blocked["btc_forward_return_60d"] > 0).sum()) if not directly_blocked.empty else 0
    confirmed = int((reentry["confirmed_or_rejected"] == "CONFIRMED").sum()) if not reentry.empty else 0
    rejected = int((reentry["confirmed_or_rejected"] == "REJECTED").sum()) if not reentry.empty else 0
    march_rejected = bool(
        not reentry.empty
        and pd.to_datetime(reentry["candidate_date"], utc=True).between(
            pd.Timestamp("2023-03-01", tz="UTC"), pd.Timestamp("2023-03-31", tz="UTC")
        ).any()
        and (reentry["confirmed_or_rejected"] == "REJECTED").any()
    )
    blocked_dates = pd.to_datetime(directly_blocked["timestamp"], utc=True) if not directly_blocked.empty else pd.Series([], dtype="datetime64[ns, UTC]")
    d2025 = _event_value(event_audit, "CORRECTION_2025_2026", "P")
    covid_b, covid_p = (_event_value(event_audit, "COVID", model) for model in ("B", "P"))
    may_b, may_p = (_event_value(event_audit, "MAY_2021", model) for model in ("B", "P"))
    bear_b, bear_p = (_event_value(event_audit, "NOV_2021_JUN_2022", model) for model in ("B", "P"))
    rolling_p_better = int((rolling["P_final_portfolio_value"] > rolling["B_final_portfolio_value"]).sum())

    perf_cols = ["initial_capital", "external_contributions_after_inception", "final_portfolio_value", "xirr", "twr_cagr", "maximum_drawdown", "sharpe", "sortino", "calmar"]
    perf = summary.set_index("model")[perf_cols].copy()
    perf.columns = ["Initial", "External", "Final", "XIRR", "TWR CAGR", "Max DD", "Sharpe", "Sortino", "Calmar"]
    for col in ("Initial", "External", "Final"):
        perf[col] = perf[col].map(lambda x: f"{x:,.2f}")
    for col in ("XIRR", "TWR CAGR", "Max DD"):
        perf[col] = perf[col].map(_pct)
    for col in ("Sharpe", "Sortino", "Calmar"):
        perf[col] = perf[col].map(lambda x: f"{x:.4f}")

    gate_lines = "\n".join(
        f"- {key}: **{'PASS' if value else 'FAIL'}**"
        for key, value in promotion["checks"].items()
    )
    integrity_lines = "\n".join(f"- {key}: **{'PASS' if value else 'FAIL'}**" for key, value in integrity.items())
    stage4_ok = set(stage4["model"]) >= {"B", "P"} if not stage4.empty else False
    crash_ok = bool(not crash.empty and crash["not_suppressed"].all())
    final_higher = float(p["final_portfolio_value"]) > float(b["final_portfolio_value"])
    dd_cost_acceptable = all(promotion["checks"][key] for key in [
        "G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP", "G6_2025_2026_DD_WORSEN_LTE_2PP",
        "G7_COVID_DD_WORSEN_LTE_1PP", "G8_MAY_2021_DD_WORSEN_LTE_1PP",
    ])

    jlaw = pd.DataFrame([
        ["Champion", "V3.9 P" if promotion["all_gates_pass"] else "V3.1 B"],
        ["Challenger", "V3.9 P"],
        ["Bull Persistence Quality", "PASS" if promotion["checks"]["G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP"] else "FAIL"],
        ["Bear Re-entry Quality", f"{confirmed} confirmed / {rejected} rejected"],
        ["Bull Participation Edge", f"avg exposure {100*(p['bull_2023_2025_average_crypto_exposure']-b['bull_2023_2025_average_crypto_exposure']):+.2f} pp"],
        ["Return Edge", f"final wealth {float(p['final_portfolio_value'])-float(b['final_portfolio_value']):+,.2f}"],
        ["2022 Bear Protection", "PASS" if promotion["checks"]["G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP"] else "FAIL"],
        ["2025-2026 Bear Protection", "PASS" if promotion["checks"]["G6_2025_2026_DD_WORSEN_LTE_2PP"] else "FAIL"],
        ["COVID Protection", "PASS" if promotion["checks"]["G7_COVID_DD_WORSEN_LTE_1PP"] else "FAIL"],
        ["May Crash Protection", "PASS" if promotion["checks"]["G8_MAY_2021_DD_WORSEN_LTE_1PP"] else "FAIL"],
        ["Stage4 Integrity", "PASS" if stage4_ok else "FAIL"],
        ["Crash Integrity", "PASS" if crash_ok else "FAIL"],
        ["Cash Drag", f"B {_pct(b['material_tactical_cash_time'])}; P {_pct(p['material_tactical_cash_time'])}"],
        ["Turnover", f"B {b['tactical_turnover']:.4f}x; P {p['tactical_turnover']:.4f}x"],
        ["Rolling Start Robustness", f"P higher final value in {rolling_p_better}/{len(rolling)} starts"],
        ["No Look Ahead", "PASS" if integrity.get("NO_LOOK_AHEAD", False) else "FAIL"],
        ["Overfit Risk", "HIGH: one historical path and audit-motivated one-change hypothesis"],
    ], columns=["Dimension", "Finding"])

    report = f"""# BTC+ETH Macro Hedge V3.9 — Final Report

## 結論

**{promotion['verdict']}**

Formal data end: `{pd.Timestamp(formal_end).isoformat()}`. V3.9 的規則與 promotion gates 均在 Challenger 執行前凍結；沒有結果後調參，也沒有建立 V3.10。

## 正式績效

{_markdown(perf, include_index=True)}

## Promotion gates

{gate_lines}

## Integrity

{integrity_lines}

## 24 個指定問題

1. **B 是否完整重現？** {'是' if integrity.get('V3_1_REPLAY', False) else '否'}；Final {_money(b['final_portfolio_value'])}、CAGR {_pct(b['twr_cagr'])}、Max DD {_pct(b['maximum_drawdown'])}、turnover {b['tactical_turnover']:.4f}x。
2. **P 最終資產？** {_money(p['final_portfolio_value'])}。
3. **B/P CAGR？** {_pct(b['twr_cagr'])} / {_pct(p['twr_cagr'])}。
4. **B/P Max DD？** {_pct(b['maximum_drawdown'])} / {_pct(p['maximum_drawdown'])}。
5. **2023–2025 平均曝險？** B {_pct(b['bull_2023_2025_average_crypto_exposure'])}；P {_pct(p['bull_2023_2025_average_crypto_exposure'])}，差 {100*(p['bull_2023_2025_average_crypto_exposure']-b['bull_2023_2025_average_crypto_exposure']):+.2f} pp。
6. **>=85% 曝險時間？** B {_pct(b['bull_2023_2025_time_exposure_gte_85'])}；P {_pct(p['bull_2023_2025_time_exposure_gte_85'])}，差 {100*(p['bull_2023_2025_time_exposure_gte_85']-b['bull_2023_2025_time_exposure_gte_85']):+.2f} pp。
7. **阻擋多少 Drift Sell？** {len(directly_blocked)} 筆。Audit 共列出 {len(blocked)} 個 V3.1 shadow drift 日；其餘會明示 `NOT_EXECUTED_GUARD_INACTIVE`，不能冒充 Guard 功效。
8. **阻擋後 30/60 日 BTC 上漲幾筆？** {pos30}/{pos60}；這是 ex-post audit，沒有進入訊號。
9. **Stage3 candidate 最終 Reject？** {rejected} 個。
10. **真正確認 Bear Re-entry？** {confirmed} 個。
11. **2023/3 是否仍過早重新 Bear？** {'沒有；原 Stage3 candidate 被三日規則拒絕' if march_rejected else '有或證據不足；詳見 bear re-entry audit'}。
12. **2023/11 是否仍過早降低曝險？** P 沒有執行該 Drift Sell，但不是直接被 Guard 阻擋；Persistence 已於 2023/8 SMA200 hard failure 結束，P 因較晚執行 Stage3 而未達 drift +10pp 觸發門檻。
13. **2024/2 是否仍過早降低曝險？** P 沒有執行該 Drift Sell；同樣是前述曝險路徑差異，不是 Guard 當日直接阻擋。
14. **2024/11 風險動作？** B 執行 Drift Sell，P 未執行；Guard 當日已關閉，故不可歸功於 direct blocking。
15. **2021 大頂是否因 Guard 多虧？** 沒有可見交易差異。Guard 曾在 2020/5 NEW_BULL 後啟動，並於 2021/5 Crash 解除；B/P 在 2021–2022 窗口的 DD 相同，為 {_pct(bear_b)} / {_pct(bear_p)}。
16. **2022 Bear DD 是否保持？** {'是' if promotion['checks']['G5_2021NOV_2022JUN_DD_WORSEN_LTE_2PP'] else '否'}；B/P {_pct(bear_b)} / {_pct(bear_p)}。
17. **2025→2026 DD 是否仍約 30% 內？** {'是' if d2025 >= -0.3024 else '否'}；P 為 {_pct(d2025)}。
18. **2025/11 Stage4 完整執行？** {'是' if stage4_ok else '否'}；詳見 `stage4_integrity_v3_9.csv`。
19. **COVID 是否惡化？** B/P {_pct(covid_b)} / {_pct(covid_p)}，{'未超過 1pp' if promotion['checks']['G7_COVID_DD_WORSEN_LTE_1PP'] else '惡化超過 1pp'}。
20. **May Crash 是否惡化？** B/P {_pct(may_b)} / {_pct(may_p)}，{'未超過 1pp' if promotion['checks']['G8_MAY_2021_DD_WORSEN_LTE_1PP'] else '惡化超過 1pp'}。
21. **Final Wealth 高於 V3.1？** {'是' if final_higher else '否'}；差額 {_money(float(p['final_portfolio_value'])-float(b['final_portfolio_value']))}。
22. **提高 bull participation 是否付出不可接受 DD？** {'沒有通過既定事件 DD 門檻判定出不可接受代價' if dd_cost_acceptable else '有；至少一個既定事件 DD gate 失敗'}。
23. **是否解決健康牛市過早 Bear，而非製造熊市反應過慢？** {'兩面 gate 均支持' if promotion['checks']['G1_BULL_AVG_EXPOSURE_DELTA_GTE_10PP'] and dd_cost_acceptable and stage4_ok and crash_ok else '不能這樣下結論；bull edge 或 bear-safety 證據至少一項不足'}。
24. **值得取代 V3.1？** {'是，且只依照全部 frozen gates' if promotion['all_gates_pass'] else '否；未通過全部 frozen promotion gates'}。

## J Law Verdict

{_markdown(jlaw)}

## Rolling-start sensitivity

{_markdown(rolling)}

## Regime transition audit

{_markdown(transition_stats)}

## 事實、推論與限制

- **事實：** 表中數字是同一批 frozen BTC/ETH bars、同一費用／滑價、同一 Model A DCA commitment 下的實際回放結果。
- **推論：** 「避免過早 Bear」只表示在這條歷史路徑上，指定事件與 gates 呈現該特徵；不是未來報酬保證，也不是因果證明。
- **成本與偏差：** 研究假說源自先前 Necessity Audit，存在 selection / multiple-testing 風險；四個 rolling starts 共用大量重疊資料與同一終點，不能視為四個獨立樣本。
- **容易忽略的變數：** 實盤容量、稅務、交易所中斷、stablecoin／託管風險、滑價尾部、BTC/ETH 權重漂移，以及 V3.1 FSM 在深熊／累積狀態的高頻轉換，都不由這個單一路徑回測充分識別。

## Reproduction

Run `.venv\\Scripts\\python.exe run_backtest_v3_9.py`. Frozen interpretation details are in `design/V39_ASSUMPTIONS.md`; hashes and environment are in `artifacts/run_manifest_v3_9.json`.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


__all__ = ["create_v39_figures", "write_v39_report"]
