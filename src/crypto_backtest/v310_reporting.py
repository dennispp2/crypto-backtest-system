from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


COLORS = {
    "H0": "#777777", "A": "#2878b5", "B": "#d95319",
    "P39": "#2ca02c", "Q": "#7f3c8d",
}


def _save(fig: plt.Figure, directory: Path, stem: str) -> None:
    fig.tight_layout()
    fig.savefig(directory / f"{stem}.png", dpi=180, bbox_inches="tight")
    fig.savefig(directory / f"{stem}.pdf", bbox_inches="tight")
    plt.close(fig)


def _slice(frame: pd.DataFrame, start: str, end: str | None = None) -> pd.DataFrame:
    dates = pd.to_datetime(frame["date"], utc=True)
    mask = dates >= pd.Timestamp(start, tz="UTC")
    if end:
        mask &= dates <= pd.Timestamp(end, tz="UTC")
    return frame.loc[mask].copy()


def _risk_lines(
    ax: plt.Axes, trades: dict[str, pd.DataFrame], start: str, end: str | None,
) -> None:
    lower = pd.Timestamp(start, tz="UTC")
    upper = (
        pd.Timestamp(end, tz="UTC") + pd.Timedelta(days=1)
        if end else pd.Timestamp.max.tz_localize("UTC")
    )
    for model in ("B", "P39", "Q"):
        selected = trades[model].loc[
            trades[model]["action"].str.startswith("TACTICAL_SELL", na=False)
        ]
        for timestamp in pd.to_datetime(selected["timestamp"], utc=True).drop_duplicates():
            if lower <= timestamp < upper:
                ax.axvline(timestamp, color=COLORS[model], alpha=0.16, lw=0.8)


def create_v310_figures(
    daily: dict[str, pd.DataFrame],
    trades: dict[str, pd.DataFrame],
    candidates: pd.DataFrame,
    rolling: pd.DataFrame,
    directory: Path,
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    plt.style.use("seaborn-v0_8-whitegrid")

    fig, ax = plt.subplots(figsize=(13, 6))
    for model in ("H0", "A", "B", "P39", "Q"):
        ax.plot(daily[model]["date"], daily[model]["portfolio_value"], label=model, color=COLORS[model], lw=1.4)
    ax.set(title="V3.10 Total Portfolio Value", ylabel="USD", xlabel="Date")
    ax.legend(ncol=5)
    _save(fig, directory, "01_equity_curve_v3_10")

    fig, ax = plt.subplots(figsize=(13, 6))
    for model in ("H0", "A", "B", "P39", "Q"):
        ax.plot(daily[model]["date"], daily[model]["unit_nav"], label=model, color=COLORS[model], lw=1.4)
    ax.set(title="Cash-flow-adjusted TWR Growth", ylabel="Growth of $1", xlabel="Date")
    ax.legend(ncol=5)
    _save(fig, directory, "02_normalized_growth_v3_10")

    fig, ax = plt.subplots(figsize=(13, 5))
    for model in ("B", "P39", "Q"):
        ax.plot(daily[model]["date"], 100.0 * daily[model]["drawdown"], label=model, color=COLORS[model], lw=1.25)
    ax.axhline(-40.01, color="black", ls="--", lw=0.8, alpha=0.55, label="Q gate -40.01%")
    ax.set(title="Drawdown: V3.1 B, V3.9 P39, V3.10 Q", ylabel="Drawdown (%)", xlabel="Date")
    ax.legend(ncol=4)
    _save(fig, directory, "03_drawdown_v3_10")

    q = _slice(daily["Q"], "2023-02-15", "2023-09-30")
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 9), sharex=True, gridspec_kw={"height_ratios": [1.15, 1]})
    ax1.plot(q["date"], q["BTC_signal_close"], label="BTC", color="#222222", lw=1.2)
    ax1.plot(q["date"], q["sma20"], label="SMA20", color="#17becf", lw=0.95)
    ax1.plot(q["date"], q["sma50"], label="SMA50", color="#1f77b4", lw=0.95)
    ax1.plot(q["date"], q["sma200"], label="SMA200", color="#9467bd", lw=0.95)
    ax1.set_ylabel("BTC price")
    ax1.legend(ncol=4)
    for model in ("B", "P39", "Q"):
        selected = _slice(daily[model], "2023-02-15", "2023-09-30")
        ax2.plot(selected["date"], 100.0 * selected["crypto_exposure"], label=f"{model} exposure", color=COLORS[model], lw=1.15)
    if not candidates.empty:
        marker_style = {
            "candidate": ("candidate_date", "#ff7f0e", "o"),
            "rejected": ("resolution_date", "#d62728", "x"),
            "confirmed": ("final_reentry_date", "#2ca02c", "^"),
        }
        for label, (column, color, marker) in marker_style.items():
            selected = candidates if label == "candidate" else candidates.loc[
                candidates["confirmed_or_rejected"].eq(label.upper())
            ]
            dates = pd.to_datetime(selected[column], utc=True, errors="coerce").dropna()
            for index, date in enumerate(dates):
                if pd.Timestamp("2023-02-15", tz="UTC") <= date <= pd.Timestamp("2023-09-30", tz="UTC"):
                    ax2.axvline(date, color=color, ls=":" if marker != "x" else "--", lw=1.1, label=label if index == 0 else None)
        hard = candidates.loc[candidates["resolution_reason"].eq("SMA200_HARD_FAILURE")]
        for index, date in enumerate(pd.to_datetime(hard["resolution_date"], utc=True, errors="coerce").dropna()):
            ax2.axvline(date, color="black", ls="-.", lw=1.2, label="SMA200 hard failure" if index == 0 else None)
    ax2.set(title="2023 Isolated Stage3 Confirmation", ylabel="Crypto exposure (%)", xlabel="Date", ylim=(0, 102))
    ax2.legend(ncol=4)
    _save(fig, directory, "04_2023_stage3_isolation_v3_10")

    for stem, start, end, title in (
        ("05_2021_2022_safety_v3_10", "2021-09-01", "2022-06-30", "2021 Peak and 2022 Bear Safety"),
        ("06_2025_2026_safety_v3_10", "2025-01-01", None, "2025-2026 Safety"),
    ):
        base = _slice(daily["Q"], start, end)
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
        ax1.plot(base["date"], base["BTC_signal_close"], color="#222222", label="BTC", lw=1.15)
        ax1.set_yscale("log")
        ax1.set_ylabel("BTC price (log)")
        ax1.legend()
        for model in ("B", "P39", "Q"):
            selected = _slice(daily[model], start, end)
            ax2.plot(selected["date"], 100.0 * selected["crypto_exposure"], color=COLORS[model], label=f"{model} exposure", lw=1.1)
        _risk_lines(ax2, trades, start, end)
        ax2.set(title=title, ylabel="Crypto exposure (%)", xlabel="Date", ylim=(0, 102))
        ax2.legend(ncol=3)
        _save(fig, directory, stem)

    labels = rolling["fresh_start"].astype(str).str[:4].tolist()
    x = np.arange(len(labels))
    width = 0.24
    fig, ax = plt.subplots(figsize=(11, 5.5))
    for offset, model in zip((-width, 0.0, width), ("B", "P39", "Q")):
        ratio = rolling[f"{model}_final_portfolio_value"] / rolling["B_final_portfolio_value"]
        ax.bar(x + offset, ratio, width, label=model, color=COLORS[model])
    ax.axhline(1.0, color="black", lw=0.8)
    ax.set_xticks(x, labels)
    ax.set(title="Rolling Fresh-start Final Value Ratio to V3.1 B", ylabel="Final value / B final", xlabel="Fresh start")
    ax.legend(ncol=3)
    _save(fig, directory, "07_rolling_start_v3_10")


def _pct(value: float) -> str:
    return f"{100.0 * float(value):.2f}%"


def _money(value: float) -> str:
    return f"US${float(value):,.2f}"


def _markdown(frame: pd.DataFrame, *, include_index: bool = False) -> str:
    work = frame.copy()
    if include_index:
        work.insert(0, work.index.name or "model", work.index.astype(str))
    columns = [str(column) for column in work.columns]
    rows = [[str(value) for value in row] for row in work.itertuples(index=False, name=None)]
    return "\n".join([
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
        *["| " + " | ".join(row) + " |" for row in rows],
    ])


def _event(events: pd.DataFrame, name: str, model: str) -> float:
    return float(events.loc[(events["event"] == name) & (events["model"] == model), "maximum_drawdown"].iloc[0])


def _drift_class(scope: pd.DataFrame, date: str) -> str:
    execution_dates = pd.to_datetime(scope["execution_4h_open"], utc=True, errors="coerce")
    selected = scope.loc[execution_dates.eq(pd.Timestamp(date, tz="UTC"))]
    if selected.empty:
        return "NO_DIFFERENCE_OR_NO_SIGNAL"
    meaningful = selected.loc[selected["has_economic_or_state_difference"]]
    return str(meaningful.iloc[0]["classification"]) if not meaningful.empty else "SAME"


def write_v310_report(
    path: Path,
    *,
    summary: pd.DataFrame,
    event_audit: pd.DataFrame,
    rolling: pd.DataFrame,
    candidates: pd.DataFrame,
    scope: pd.DataFrame,
    lineage: pd.DataFrame,
    stage4: pd.DataFrame,
    crash: pd.DataFrame,
    promotion: dict[str, Any],
    integrity: dict[str, bool],
    formal_end: Any,
) -> None:
    index = summary.set_index("model")
    b, p, q = index.loc["B"], index.loc["P39"], index.loc["Q"]
    candidate_count = len(candidates)
    rejected = int(candidates["confirmed_or_rejected"].eq("REJECTED").sum()) if candidate_count else 0
    confirmed = int(candidates["confirmed_or_rejected"].eq("CONFIRMED").sum()) if candidate_count else 0
    hard = int(candidates["resolution_reason"].eq("SMA200_HARD_FAILURE").sum()) if candidate_count else 0
    march_reject = bool(
        candidate_count
        and pd.to_datetime(candidates["candidate_date"], utc=True).between(
            pd.Timestamp("2023-03-01", tz="UTC"), pd.Timestamp("2023-03-31 23:59:59", tz="UTC")
        ).any()
        and candidates["resolution_reason"].eq("THREE_CLOSE_SEQUENCE_BROKEN").any()
    )
    august_hard = bool(
        candidate_count
        and pd.to_datetime(candidates["resolution_date"], utc=True, errors="coerce").between(
            pd.Timestamp("2023-08-01", tz="UTC"), pd.Timestamp("2023-08-31 23:59:59", tz="UTC")
        ).any()
        and candidates["resolution_reason"].eq("SMA200_HARD_FAILURE").any()
    )
    unexplained = int(lineage["classification"].eq("UNEXPLAINED_PATH_DIFFERENCE").sum()) if not lineage.empty else 0
    unexpected_scope = int(scope["classification"].eq("UNEXPECTED_DIFFERENCE").sum())
    stage4_ok = set(stage4["model"]) >= {"B", "P39", "Q"} if not stage4.empty else False
    crash_ok = bool(not crash.empty and crash["q_not_suppressed"].all())
    q_better_starts = int((rolling["Q_final_portfolio_value"] > rolling["B_final_portfolio_value"]).sum())
    bear_b, bear_q = (_event(event_audit, "NOV_2021_JUN_2022", model) for model in ("B", "Q"))
    correction_b, correction_p, correction_q = (
        _event(event_audit, "CORRECTION_2025_2026", model) for model in ("B", "P39", "Q")
    )
    covid_b, covid_q = (_event(event_audit, "COVID", model) for model in ("B", "Q"))
    may_b, may_q = (_event(event_audit, "MAY_2021", model) for model in ("B", "Q"))
    capture = float(promotion["uplift_capture_ratio"])

    perf_columns = [
        "initial_capital", "external_contributions_after_inception", "final_portfolio_value",
        "xirr", "twr_cagr", "maximum_drawdown", "sharpe", "sortino", "calmar",
    ]
    perf = summary.set_index("model")[perf_columns].copy()
    perf.columns = ["Initial", "External", "Final", "XIRR", "TWR CAGR", "Max DD", "Sharpe", "Sortino", "Calmar"]
    for column in ("Initial", "External", "Final"):
        perf[column] = perf[column].map(lambda value: f"{value:,.2f}")
    for column in ("XIRR", "TWR CAGR", "Max DD"):
        perf[column] = perf[column].map(_pct)
    for column in ("Sharpe", "Sortino", "Calmar"):
        perf[column] = perf[column].map(lambda value: f"{value:.4f}")

    gate_lines = "\n".join(
        f"- {key}: **{'PASS' if value else 'FAIL'}**"
        for key, value in promotion["checks"].items()
    )
    integrity_lines = "\n".join(
        f"- {key}: **{'PASS' if value else 'FAIL'}**" for key, value in integrity.items()
    )
    capture_finding = (
        "支持：至少捕捉 frozen 75% 門檻" if capture >= 0.75
        else "不支持：未捕捉 frozen 75% 門檻"
    )
    jlaw = pd.DataFrame([
        ["Champion", "V3.10 Q" if promotion["all_gates_pass"] else "V3.1 B"],
        ["Reference Challenger", "V3.9 P39"],
        ["Isolated Challenger", "V3.10 Q"],
        ["Baseline Integrity", "PASS" if integrity.get("V3_1_REPLAY", False) else "FAIL"],
        ["Stage3 Scope Integrity", "PASS" if integrity.get("STAGE3_SCOPE_INTEGRITY", False) else "FAIL"],
        ["Causal Isolation Quality", f"{unexplained} unexplained trade differences"],
        ["Stage3 Confirmation Edge", capture_finding],
        ["Return Edge", f"Q-B {_money(q['final_portfolio_value'] - b['final_portfolio_value'])}"],
        ["Uplift Capture", _pct(capture)],
        ["Overall Drawdown", f"B {_pct(b['maximum_drawdown'])}; Q {_pct(q['maximum_drawdown'])}"],
        ["2022 Bear Protection", f"B {_pct(bear_b)}; Q {_pct(bear_q)}"],
        ["2025-2026 Protection", f"B {_pct(correction_b)}; Q {_pct(correction_q)}"],
        ["Stage4 Integrity", "PASS" if stage4_ok else "FAIL"],
        ["Crash Integrity", "PASS" if crash_ok else "FAIL"],
        ["Rolling Start Robustness", f"Q>B in {q_better_starts}/{len(rolling)} starts"],
        ["Turnover", f"B {b['tactical_turnover']:.4f}x; Q {q['tactical_turnover']:.4f}x"],
        ["Path Dependency Risk", "HIGH: one delayed transition changes all later notionals"],
        ["Overfit Risk", "HIGH: rule was motivated by the previously observed 2023 path"],
        ["No Look Ahead", "PASS" if integrity.get("NO_LOOK_AHEAD", False) else "FAIL"],
    ], columns=["Dimension", "Finding"])

    report = f"""# BTC+ETH Macro Hedge V3.10 — Final Report

## 結論

**{promotion['verdict']}**

Formal data end: `{pd.Timestamp(formal_end).isoformat()}`. V3.10 的規則、解讀、來源 hashes 與 promotion gates 均在 Q 執行前凍結；沒有結果後調參，也沒有建立 V3.11。

## 正式績效

{_markdown(perf, include_index=True)}

## Promotion gates

{gate_lines}

精確 75% uplift 門檻為 {_money(promotion['precise_75pct_final_value_threshold_usd'])}；Q 捕捉率為 {_pct(capture)}。

## Integrity

{integrity_lines}

## 27 個指定問題

1. **V3.1 是否完整重現？** {'是' if integrity.get('V3_1_REPLAY', False) else '否'}；Final {_money(b['final_portfolio_value'])}。
2. **V3.9 是否完整重現？** {'是' if integrity.get('V3_9_REPLAY', False) else '否'}；Final {_money(p['final_portfolio_value'])}。
3. **V3.10 Final？** {_money(q['final_portfolio_value'])}。
4. **B/P39/Q Final？** {_money(b['final_portfolio_value'])} / {_money(p['final_portfolio_value'])} / {_money(q['final_portfolio_value'])}。
5. **B/P39/Q CAGR？** {_pct(b['twr_cagr'])} / {_pct(p['twr_cagr'])} / {_pct(q['twr_cagr'])}。
6. **B/P39/Q Max DD？** {_pct(b['maximum_drawdown'])} / {_pct(p['maximum_drawdown'])} / {_pct(q['maximum_drawdown'])}。
7. **Q 捕捉多少 V3.9 Return Uplift？** {_pct(capture)}；Q-B {_money(promotion['v310_return_uplift_usd'])}，P39-B {_money(promotion['v39_return_uplift_usd'])}。
8. **Stage3 Candidates？** {candidate_count}。
9. **Reject？** {rejected}。
10. **Confirmed？** {confirmed}。
11. **SMA200 Hard Failure 結束？** {hard}。
12. **2023/3 是否再次正確 Reject？** {'是' if march_reject else '否'}。
13. **2023/8 真正弱化後是否回 Bear？** {'是，hard failure 取消等待並交回 V3.1 FSM' if august_hard else '否或證據不足'}。
14. **2023/11 Drift 差異？** {_drift_class(scope, '2023-11-02')}；不是 direct Drift blocking。
15. **2024/2 Drift 差異？** {_drift_class(scope, '2024-02-19')}；不是 direct Drift blocking。
16. **2024/11 Drift 差異？** {_drift_class(scope, '2024-11-22')}；不是 direct Drift blocking。
17. **2021 大頂防守是否變差？** {'沒有；2022 event guardrail 通過' if promotion['checks']['G5_2022_BEAR_DD_WORSEN_LTE_1PP'] else '有；2022 event guardrail 失敗'}。
18. **2022 Bear DD？** B {_pct(bear_b)}；Q {_pct(bear_q)}。
19. **2025→2026 DD？** B {_pct(correction_b)}；P39 {_pct(correction_p)}；Q {_pct(correction_q)}。
20. **2025/11 Stage4 完整執行？** {'是' if stage4_ok else '否'}。
21. **COVID 是否惡化？** B {_pct(covid_b)}；Q {_pct(covid_q)}；{'未超過 0.5pp' if promotion['checks']['COVID_DD_WORSEN_LTE_0_5PP'] else '惡化超過 0.5pp'}。
22. **May Crash 是否惡化？** B {_pct(may_b)}；Q {_pct(may_q)}；{'未超過 0.5pp' if promotion['checks']['MAY_2021_DD_WORSEN_LTE_0_5PP'] else '惡化超過 0.5pp'}。
23. **Turnover 是否明顯增加？** B {b['tactical_turnover']:.4f}x；Q {q['tactical_turnover']:.4f}x；{'通過 +5% 上限' if promotion['checks']['G9_TURNOVER_INCREASE_LTE_5PCT'] else '超過 +5% 上限'}。
24. **Rolling Starts 幾組 Q>B？** {q_better_starts}/{len(rolling)}；這些高度重疊，不是獨立樣本。
25. **無法追溯的交易差異？** {unexplained} 筆；scope unexpected {unexpected_scope} 筆。
26. **V3.9 的約 +18.7K 主要來自 Stage3 Confirmation？** {capture_finding}；這是 deterministic path attribution，不是未來因果保證。
27. **單一修改是否值得取代 V3.1？** {'是；且僅因全部 frozen gates 通過' if promotion['all_gates_pass'] else '否；至少一個 frozen gate 未通過'}。

## J Law Verdict

{_markdown(jlaw)}

## Rolling-start sensitivity

{_markdown(rolling)}

## 事實、推論與限制

- **事實：** H0/A/B/P39/Q 使用同一 frozen BTC/ETH 資料、成本、滑價、最低名目額與 Model A DCA commitment；Q 沒有 Drift Sell Guard、AI、額外曝險目標或新 AHR 門檻。
- **推論：** Uplift capture 是這條歷史價格路徑上的 deterministic counterfactual attribution。它能回答程式路徑來源，不能證明未來市場的因果效果。
- **偏差：** Stage3 規則由先前看到的 2023 事件所啟發，存在研究者自由度、multiple-testing 與歷史事件選擇偏差。四個 rolling starts 共用終點及大部分資料，不能當作四次獨立驗證。
- **容易忽略的成本／變數：** 稅務、交易所中斷、stablecoin 與託管風險、滑價尾部、容量、BTC/ETH 權重漂移和 4H open 可成交性均未由此回測完全識別。

## Reproduction

Run `.venv\\Scripts\\python.exe run_backtest_v3_10.py`. Frozen semantics are in `design/V310_ASSUMPTIONS.md`; hashes and environment are in `v3_10/artifacts/run_manifest_v3_10.json`.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report, encoding="utf-8")


__all__ = ["create_v310_figures", "write_v310_report"]
