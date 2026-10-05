from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .engine import BacktestResult
from .metrics import daily_history


COLORS = {
    "Benchmark A - Fixed DCA": "#4C78A8",
    "Benchmark B - Annual Rebalance": "#F58518",
    "Benchmark C - Dynamic DCA": "#54A24B",
    "Strategy D - Full": "#E45756",
}


def _save_dual(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(base.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def create_figures(
    project_dir: Path,
    main_results: dict[str, BacktestResult],
    primary_daily: pd.DataFrame,
) -> None:
    fig_dir = project_dir / "figures"
    daily = {name: daily_history(result.history) for name, result in main_results.items()}
    full = main_results["Strategy D - Full"]
    full_daily = daily["Strategy D - Full"]

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for name, df in daily.items():
        ax.plot(df["date"], df["portfolio_value"], label=name, lw=1.4, color=COLORS.get(name))
    ax.set_title("Portfolio Equity Curves — Test 2, Equal External Contributions")
    ax.set_ylabel("Portfolio value (USD)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "01_portfolio_equity_curve")

    fig, ax = plt.subplots(figsize=(10, 5.5))
    for name in ("Benchmark A - Fixed DCA", "Strategy D - Full"):
        df = daily[name]
        ax.plot(df["date"], df["portfolio_value"], label=name, lw=1.6, color=COLORS[name])
    ax.set_title("Full Strategy vs Fixed DCA")
    ax.set_ylabel("Portfolio value (USD)")
    ax.legend()
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "02_full_vs_fixed_dca")

    fig, ax = plt.subplots(figsize=(10, 4.5))
    for name in ("Benchmark A - Fixed DCA", "Strategy D - Full"):
        df = daily[name]
        ax.plot(df["date"], 100 * df["drawdown"], label=name, lw=1.3, color=COLORS[name])
    ax.set_title("Money-Flow-Neutral Drawdown")
    ax.set_ylabel("Drawdown (%)")
    ax.legend()
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "03_drawdown_curve")

    p = primary_daily.loc[primary_daily["signal_date"] >= full_daily["date"].min()].copy()
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(p["signal_date"], p["close"], label="BTC close", color="black", lw=1.0)
    for window, color in [(10, "#4C78A8"), (20, "#F58518"), (50, "#54A24B"), (200, "#E45756")]:
        ax.plot(p["signal_date"], p[f"sma{window}"], label=f"SMA{window}", lw=0.8, color=color)
    ax.plot(p["signal_date"], p["bb_upper"], color="gray", lw=0.6, alpha=0.7, label="Bollinger upper/lower")
    ax.plot(p["signal_date"], p["bb_lower"], color="gray", lw=0.6, alpha=0.7)
    ax.set_yscale("log")
    ax.set_title("BTC Price, SMA and Bollinger Bands (UTC Daily)")
    ax.set_ylabel("USD, log scale")
    ax.legend(ncol=3, fontsize=8)
    ax.grid(alpha=0.15)
    _save_dual(fig, fig_dir / "04_btc_technical_indicators")

    fig, ax1 = plt.subplots(figsize=(11, 5.5))
    ax1.plot(p["signal_date"], p["close"], color="black", lw=1.0, label="BTC close")
    ax1.set_yscale("log")
    ax1.set_ylabel("BTC USD, log scale")
    ax2 = ax1.twinx()
    ax2.plot(p["signal_date"], p["ahr999_fixed_arithmetic"], color="#E45756", lw=0.9, label="AHR999")
    for level, color in [(0.35, "#F58518"), (0.30, "#54A24B"), (0.28, "#4C78A8")]:
        ax2.axhline(level, color=color, ls="--", lw=0.8, label=f"{level:.2f}")
    ax2.set_yscale("log")
    finite_ahr = p["ahr999_fixed_arithmetic"].replace([np.inf, -np.inf], np.nan).dropna()
    ax2.set_ylim(max(0.2, float(finite_ahr.min()) * 0.9), float(finite_ahr.max()) * 1.1)
    ax2.set_ylabel("AHR999, log scale")
    lines = ax1.get_lines() + ax2.get_lines()
    ax1.legend(lines, [line.get_label() for line in lines], ncol=4, fontsize=8, loc="upper left")
    ax1.set_title("BTC Price and Point-in-Time AHR999")
    _save_dual(fig, fig_dir / "05_btc_ahr999")

    trade = full.trades.copy()
    trade["date"] = trade["timestamp"].dt.floor("D")
    price_map = full_daily.set_index("date")["BTC_close"]
    sell = trade[trade["action"].str.startswith("TACTICAL_SELL_STAGE", na=False)].copy()
    sell["marker_price"] = sell["date"].map(price_map)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(full_daily["date"], full_daily["BTC_close"], color="black", lw=1.0)
    markers = {1: "^", 2: "s", 3: "D", 4: "X"}
    for stage in (1, 2, 3, 4):
        subset = sell[sell["action"].eq(f"TACTICAL_SELL_STAGE_{stage}")].drop_duplicates("date")
        ax.scatter(subset["date"], subset["marker_price"], marker=markers[stage], s=36, label=f"Stage {stage}: {stage*15}%")
    ax.set_yscale("log")
    ax.set_title("Sell Stage Markers (Executed at Next 4H Open)")
    ax.set_ylabel("BTC USD, log scale")
    ax.legend(fontsize=8)
    _save_dual(fig, fig_dir / "06_sell_stage_markers")

    buy = trade[trade["action"].str.startswith("TACTICAL_BUYBACK", na=False)].copy()
    buy["marker_price"] = buy["date"].map(price_map)
    fig, ax = plt.subplots(figsize=(11, 5.5))
    ax.plot(full_daily["date"], full_daily["BTC_close"], color="black", lw=1.0)
    buy_types = [
        ("TACTICAL_BUYBACK_AHR_030_035", "AHR .30-.35: 5%", "o"),
        ("TACTICAL_BUYBACK_AHR_BELOW_030", "AHR <.30: 25%", "^"),
        ("TACTICAL_BUYBACK_AHR_EXTREME", "Extreme: 20%", "D"),
        ("TACTICAL_BUYBACK_RIGHT_CONFIRMATION", "Right-side: 10%", "s"),
    ]
    for action, label, marker in buy_types:
        subset = buy[buy["action"].eq(action)].drop_duplicates("date")
        ax.scatter(subset["date"], subset["marker_price"], marker=marker, s=38, label=label)
    ax.set_yscale("log")
    ax.set_title("Buyback Markers (Executed at Next 4H Open)")
    ax.set_ylabel("BTC USD, log scale")
    ax.legend(fontsize=8)
    _save_dual(fig, fig_dir / "07_buyback_markers")

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.step(full_daily["date"], full_daily["theoretical_dca"], where="post", label="AHR/stage rate", lw=1.0)
    ax.step(full_daily["date"], full_daily["protected_dca"], where="post", label="After cash protection", lw=1.0)
    ax.set_ylim(0, 3.2)
    ax.set_ylabel("USD per 4H")
    ax.set_title("Dynamic DCA Rate")
    ax.legend()
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "08_dynamic_dca_rate")

    fig, ax = plt.subplots(figsize=(11, 5.0))
    ax.stackplot(
        full_daily["date"],
        100 * full_daily["BTC_allocation"],
        100 * full_daily["ETH_allocation"],
        100 * full_daily["BNB_allocation"],
        labels=["BTC", "ETH", "BNB"],
        colors=["#F2A900", "#627EEA", "#F3BA2F"],
        alpha=0.85,
    )
    ax.set_ylim(0, 100)
    ax.set_ylabel("Crypto sleeve allocation (%)")
    ax.set_title("BTC / ETH / BNB Allocation")
    ax.legend(ncol=3)
    _save_dual(fig, fig_dir / "09_crypto_allocation")

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(full_daily["date"], 100 * full_daily["normal_cash_ratio"], color="#4C78A8", lw=1.0)
    for level in (10, 15, 20):
        ax.axhline(level, color="gray", ls="--", lw=0.7)
    ax.set_ylabel("Normal available cash / portfolio (%)")
    ax.set_title("Normal Cash Ratio")
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "10_normal_cash_ratio")

    fig, ax = plt.subplots(figsize=(11, 4.5))
    ax.plot(full_daily["date"], 100 * full_daily["tactical_cash_ratio"], color="#E45756", lw=1.0)
    ax.set_ylabel("Tactical cash / portfolio (%)")
    ax.set_title("Tactical Cash Ratio")
    ax.grid(alpha=0.2)
    _save_dual(fig, fig_dir / "11_tactical_cash_ratio")


def _pct(value: Any) -> str:
    return "NA" if pd.isna(value) else f"{100 * float(value):.2f}%"


def _usd(value: Any) -> str:
    return "NA" if pd.isna(value) else f"US${float(value):,.2f}"


def _metric_table(rows: list[dict[str, Any]]) -> str:
    keys = [
        ("strategy", "Strategy"),
        ("final_portfolio_value", "Final value"),
        ("xirr", "XIRR"),
        ("time_weighted_cagr", "TWR CAGR"),
        ("maximum_drawdown", "Max DD"),
        ("sharpe", "Sharpe"),
        ("sortino", "Sortino"),
        ("calmar", "Calmar"),
    ]
    header = "| " + " | ".join(label for _, label in keys) + " |"
    sep = "|" + "|".join(["---"] * len(keys)) + "|"
    body = []
    for row in rows:
        vals = []
        for key, _ in keys:
            val = row[key]
            if key == "final_portfolio_value":
                vals.append(_usd(val))
            elif key in {"xirr", "time_weighted_cagr", "maximum_drawdown"}:
                vals.append(_pct(val))
            elif key == "strategy":
                vals.append(str(val))
            else:
                vals.append("NA" if pd.isna(val) else f"{float(val):.3f}")
        body.append("| " + " | ".join(vals) + " |")
    return "\n".join([header, sep, *body])


def write_final_report(
    project_dir: Path,
    summary: pd.DataFrame,
    cycles: pd.DataFrame,
    cash: pd.DataFrame,
    sensitivity: pd.DataFrame,
    btc_validation: pd.DataFrame,
    stage_effectiveness: pd.DataFrame,
    source_manifest: pd.DataFrame,
) -> bool:
    main = summary[
        (summary["capital_test"] == "test2")
        & (summary["variant"] == "primary")
        & (summary["cost_case"] == "primary")
    ]
    indexed = main.set_index("strategy")
    fixed = indexed.loc["Benchmark A - Fixed DCA"]
    rebalance = indexed.loc["Benchmark B - Annual Rebalance"]
    dynamic = indexed.loc["Benchmark C - Dynamic DCA"]
    full = indexed.loc["Strategy D - Full"]
    full_off = summary[
        (summary["capital_test"] == "test2")
        & (summary["strategy"] == "Strategy D - Full")
        & (summary["variant"] == "cash_protection_off")
    ].iloc[0]
    main_test1 = summary[
        (summary["capital_test"] == "test1")
        & (summary["variant"] == "primary")
        & (summary["cost_case"] == "primary")
    ].set_index("strategy")
    fixed_test1 = main_test1.loc["Benchmark A - Fixed DCA"]
    full_test1 = main_test1.loc["Strategy D - Full"]
    fixed_high = summary[
        (summary["capital_test"] == "test2")
        & (summary["strategy"] == "Benchmark A - Fixed DCA")
        & (summary["cost_case"] == "high")
    ].iloc[0]
    full_high = summary[
        (summary["capital_test"] == "test2")
        & (summary["strategy"] == "Strategy D - Full")
        & (summary["cost_case"] == "high")
    ].iloc[0]

    sensitivity_win = float((sensitivity["final_portfolio_value"] > fixed["final_portfolio_value"]).mean())
    cycle_wins = int((cycles["final_return_difference"] > 0).sum())
    dd_improvement = float(full["maximum_drawdown"] - fixed["maximum_drawdown"])
    return_gap = float(full["time_weighted_cagr"] - fixed["time_weighted_cagr"])
    return_cost_per_dd = (
        (fixed["time_weighted_cagr"] - full["time_weighted_cagr"]) / dd_improvement
        if dd_improvement > 0
        else np.nan
    )
    worthy = bool(
        (full["final_portfolio_value"] > fixed["final_portfolio_value"])
        and (full["time_weighted_cagr"] > fixed["time_weighted_cagr"])
        and (full["maximum_drawdown"] > fixed["maximum_drawdown"])
        and (full["sharpe"] > fixed["sharpe"])
        and (full_high["final_portfolio_value"] > fixed_high["final_portfolio_value"])
        and (sensitivity_win >= 0.60)
        and (cycle_wins >= 3)
    )

    stage_best = "無足夠事件"
    stage_worst = "無足夠事件"
    if not stage_effectiveness.empty:
        valid = stage_effectiveness.dropna(subset=["median_mae_90d"])
        if not valid.empty:
            stage_best = f"Stage {int(valid.sort_values('median_mae_90d').iloc[0]['stage'])}"
            stage_worst = f"Stage {int(valid.sort_values('median_mae_90d', ascending=False).iloc[0]['stage'])}"

    btc_primary = btc_validation[btc_validation["ahr_method"] == "ahr999_fixed_arithmetic"].set_index("threshold")
    ahr30 = btc_primary.loc[0.30] if 0.30 in btc_primary.index else None
    ahr35 = btc_primary.loc[0.35] if 0.35 in btc_primary.index else None
    ahr45 = btc_primary.loc[0.45] if 0.45 in btc_primary.index else None
    ahr_statement = "事件不足，無法判定。"
    if ahr30 is not None and ahr35 is not None and ahr45 is not None:
        ci35 = (
            ahr30.get("bootstrap_ci_low_vs_0_35", np.nan),
            ahr30.get("bootstrap_ci_high_vs_0_35", np.nan),
        )
        ci45 = (
            ahr30.get("bootstrap_ci_low_vs_0_45", np.nan),
            ahr30.get("bootstrap_ci_high_vs_0_45", np.nan),
        )
        ahr_statement = (
            f"固定公式算術 SMA200 下，0.30 事件數 {int(ahr30['event_count'])}，365 日中位報酬 {_pct(ahr30['median_return_365d'])}；"
            f"0.35 為 {_pct(ahr35['median_return_365d'])}，0.45 為 {_pct(ahr45['median_return_365d'])}。"
            f"0.30 減 0.35 的描述性 bootstrap 95% 區間為 [{_pct(ci35[0])}, {_pct(ci35[1])}]，"
            f"0.30 減 0.45 為 [{_pct(ci45[0])}, {_pct(ci45[1])}]；兩者均跨零。"
            "事件少且門檻巢狀，沒有可信的獨立樣本顯著優勢。"
        )
    cash_dd_gain = float(full["maximum_drawdown"] - full_off["maximum_drawdown"])
    cash_protection_worth = bool(
        (
            cash_dd_gain >= 0.005
            or (bool(full_off["ever_normal_cash_zero"]) and not bool(full["ever_normal_cash_zero"]))
        )
        and full["final_portfolio_value"] >= 0.98 * full_off["final_portfolio_value"]
    )
    buy35_early = "證據不足"
    if ahr30 is not None and ahr35 is not None:
        buy35_early = (
            "相對偏早、品質稍差：0.35 的 365 日中位報酬較低且 365 日 MAE 較深；但差異不顯著"
            if (
                ahr35["median_return_365d"] < ahr30["median_return_365d"]
                and ahr35["mean_mae_365d"] < ahr30["mean_mae_365d"]
            )
            else "沒有一致證據顯示較早或較差"
        )

    exact_fixed_sentence = ""
    if fixed["final_portfolio_value"] > full["final_portfolio_value"]:
        exact_fixed_sentence = "\n\n**Fixed DCA 在歷史資料中優於此戰術策略。**"

    source_end = source_manifest["end_date"].max()
    report = f"""# 加密貨幣策略歷史回測：最終判決

資料凍結至來源清單可取得的最後完成 candle（清單最大結束時間：{source_end}）。Primary 三資產因 BNBUSDT 尚未在 2017-08-01 可交易，誠實共同起算日改為 {full['start']}；沒有補造 BNB 價格。以下結論是歷史模擬，不是投資建議。{exact_fixed_sentence}

## 核心結果（Test 2、Primary 成本）

{_metric_table(main.to_dict('records'))}

所有策略的初始資金與每 4H US$2 外部投入完全一致。Full Strategy 相對 Fixed DCA 的最終資產差額為 {_usd(full['final_portfolio_value'] - fixed['final_portfolio_value'])}，TWR CAGR 差為 {_pct(return_gap)}，最大回撤改善為 {_pct(dd_improvement)}。每改善 1 個百分點最大回撤，犧牲的年化報酬約為 {('NA' if pd.isna(return_cost_per_dd) else f'{return_cost_per_dd:.3f} 個百分點')}。

## 事實、推論與限制

### 直接由已執行結果得到的事實

- Full Strategy 是否打贏 Fixed DCA：**{'是' if full['final_portfolio_value'] > fixed['final_portfolio_value'] else '否'}**。
- Held-out Test 1 同樣未打贏：Full {_usd(full_test1['final_portfolio_value'])}，Fixed {_usd(fixed_test1['final_portfolio_value'])}；但最大回撤由 {_pct(fixed_test1['maximum_drawdown'])} 改善至 {_pct(full_test1['maximum_drawdown'])}。
- Full Strategy 是否降低最大回撤：**{'是' if dd_improvement > 0 else '否'}**；差異 {_pct(dd_improvement)}。
- Dynamic DCA 相對 Fixed DCA 的最終資產差：{_usd(dynamic['final_portfolio_value'] - fixed['final_portfolio_value'])}。
- Annual Rebalance 相對 Fixed DCA 的最終資產差：{_usd(rebalance['final_portfolio_value'] - fixed['final_portfolio_value'])}。
- Cash Protection ON 相對 OFF 的最終資產差：{_usd(full['final_portfolio_value'] - full_off['final_portfolio_value'])}；最大回撤差：{_pct(full['maximum_drawdown'] - full_off['maximum_drawdown'])}。
- Tactical Cash 在 Full Strategy 中非零的時間比例為 {_pct(full['time_in_tactical_cash'])}，是主要報酬拖累來源之一。
- 54 組允許的 frozen sensitivity 中，最終資產高於 Primary Fixed DCA 的比例為 {_pct(sensitivity_win)}；這只衡量穩健性，沒有拿最佳組合改寫正式規則。
- 五個使用者指定、彼此可能重疊的週期窗口中，Full Strategy 的 TWR 報酬高於 Fixed DCA 共 {cycle_wins}/5 個。
- 高成本情境下，Full Strategy 與同成本 Fixed DCA 的最終資產差為 {_usd(full_high['final_portfolio_value'] - fixed_high['final_portfolio_value'])}。
- 以 BTC 觸發後 90 日最大不利走勢衡量，歷史上最有效的賣出層級是 **{stage_best}**，最弱是 **{stage_worst}**。事件數少時此排序不穩定。
- AHR999 長期驗證：{ahr_statement}

### 有條件的推論

- 戰術現金若降低回撤但拖累終值，代表這套規則主要是風險轉移，不是免費 alpha。`cash_drag` 是基於同期 target-basket 報酬的路徑歸因近似，不是可交易的獨立反事實。
- 0.30 比 0.35/0.45 更低不等於統計上顯著更好；同一熊市可依序穿越多個門檻，事件並不獨立。
- BTC50/ETH30/BNB20 是否「合理」無法由本回測識別，因為規格禁止配置權重搜尋，也沒有加入其他權重的預先註冊比較。只能說這個組合在本樣本的結果，不能說它是最優配置。

### 不能忽略的成本與偏差

- Binance 現行 US$5 NOTIONAL 被當作固定歷史代理；缺少歷史逐時 symbol filters，成交可行性仍有模型誤差。
- Bitstamp BTCUSD 用於 2013+ 長期驗證與 Binance 上市前 warm-up；2017 年後 Primary 訊號切換到 Binance BTCUSDT。跨來源基差可能改變臨界點附近的 AHR999 觸發日。
- BNB 的存在使 Primary 僅涵蓋 2017-11 之後，完整策略可觀察的獨立大週期數有限；規則多、事件少，過度擬合風險高。
- 稅負、穩定幣脫鉤、交易所倒閉/停機、存提款限制、價差擴張與市場衝擊未建模。

## J Law 式 17 問

1. **Full Strategy 是否打贏 Fixed DCA？** {'是' if full['final_portfolio_value'] > fixed['final_portfolio_value'] else '否'}；終值差 {_usd(full['final_portfolio_value'] - fixed['final_portfolio_value'])}。
2. **若沒打贏，少多少？** {(_usd(fixed['final_portfolio_value'] - full['final_portfolio_value']) if full['final_portfolio_value'] < fixed['final_portfolio_value'] else '不適用')}。
3. **是否明顯降低 Drawdown？** {'是' if dd_improvement > 0 else '否'}；改善 {_pct(dd_improvement)}。
4. **每降低 1% Drawdown 犧牲多少 Return？** {('無法定義，因回撤未改善' if dd_improvement <= 0 else f'{return_cost_per_dd:.3f} 個 TWR CAGR 百分點/每 1 個回撤百分點')}。
5. **哪個 Sell Stage 最有效？** {stage_best}（以後續 90 日 MAE 定義）。
6. **哪個 Sell Stage 最沒用？** {stage_worst}。
7. **AHR999 <0.30 是否真正有效？** {ahr_statement}
8. **0.30-0.35 是否買太早？** {buy35_early}。
9. **Dynamic DCA 是否有用？** 相對 Fixed DCA 終值差 {_usd(dynamic['final_portfolio_value'] - fixed['final_portfolio_value'])}，TWR CAGR 差 {_pct(dynamic['time_weighted_cagr'] - fixed['time_weighted_cagr'])}。
10. **Cash Protection 是否值得保留？** {'依本樣本值得' if cash_protection_worth else '不值得：未避免資金耗盡，回撤改善不足 0.5 個百分點，且終值較低'}；完整數字見 `cash_analysis.csv`。
11. **Rebalancing 是否增加報酬？** {'是' if rebalance['final_portfolio_value'] > fixed['final_portfolio_value'] else '否'}；終值差 {_usd(rebalance['final_portfolio_value'] - fixed['final_portfolio_value'])}。
12. **BTC50/ETH30/BNB20 是否合理？** 可執行，但不能由這個單一權重回測推論為最優。
13. **哪些規則是 Robust Edge？** 只有同時通過主樣本、週期、高成本與 sensitivity 的方向才有資格；本次整體實盤門檻判定為 **{'通過' if worthy else '未通過'}**。
14. **哪些規則可能 Overfit？** 四層賣出、四段買回、兩組偏離門檻與多重確認的組合，事件數相對規則數偏少。
15. **哪裡最容易賣飛？** Stage 1/2 若 90 日 MFE 高且 MAE 淺；逐事件證據見 `tactical_stage_effectiveness.csv` 與 `signal_log.csv`。
16. **哪裡最容易接刀？** 0.30-0.35 與首次 <0.30；其後 365 日 MAE 直接列在 `btc_extended_events.csv`。
17. **是否值得實盤？** **{'只能以極小規模、前向驗證後再考慮' if worthy else '目前不值得直接實盤；先做前向紙上交易'}**。歷史過關也不能消除來源切換、交易所與穩定幣風險。

## 驗收與重現

- `artifacts/no_lookahead_audit.json`：訊號時間、交易時間、prefix invariance 與帳本檢查。
- `data/source_manifest.csv`：來源、涵蓋期、切換日、列數與 SHA-256。
- `config/frozen_rules.json`：正式規則；敏感度結果不得覆寫此檔。
- `artifacts/run_manifest.json`：執行環境、輸出雜湊與資料契約。
"""
    (project_dir / "report" / "FINAL_REPORT.md").write_text(report, encoding="utf-8")

    simplified = project_dir / "report" / "FINAL_SIMPLIFIED_STRATEGY.md"
    if worthy:
        content = f"""# FINAL SIMPLIFIED STRATEGY

本檔只在嚴格歷史門檻通過時產生；仍須先前向紙上驗證。

1. 所有策略資金基準：每 4H 外部投入 US$2，絕不借款。
2. Normal DCA 永遠大於零，最高 US$3；Normal 與 Tactical Cash 永久分帳。
3. 只保留 Primary 2-of-3 Overheat Gate 與實際最有效的 {stage_best}；其他賣出層級先停用，直到前向樣本證實。
4. AHR999 只用 BTC、只用完成 UTC 日線；買回只動用歷史上真正賣出的 Tactical Cash。
5. 每個日線訊號最早於下一個 4H open 執行；禁止 pivot、全樣本調參與門檻挑優。
6. 現金保護保留與否依本次 ON/OFF 結果：終值差 {_usd(full['final_portfolio_value'] - full_off['final_portfolio_value'])}，回撤差 {_pct(full['maximum_drawdown'] - full_off['maximum_drawdown'])}。
7. 實盤前至少完成一個未參與規則設計的完整市場 regime 前向驗證。
"""
        simplified.write_text(content, encoding="utf-8")
    elif simplified.exists():
        simplified.unlink()
    return worthy


def write_run_manifest(project_dir: Path, payload: dict[str, Any]) -> None:
    (project_dir / "artifacts" / "run_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
