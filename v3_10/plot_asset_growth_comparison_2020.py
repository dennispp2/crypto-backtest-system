from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.ticker import FuncFormatter


ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
FIGURES = ROOT / "figures"
SOURCE = RESULTS / "daily_portfolio_v3_10.csv"
SUMMARY_SOURCE = RESULTS / "summary_v3_10.csv"
DATA_OUTPUT = RESULTS / "asset_growth_comparison_2020.csv"
SUMMARY_OUTPUT = RESULTS / "asset_growth_comparison_summary_2020.csv"
PNG_OUTPUT = FIGURES / "08_asset_growth_comparison_2020.png"
PDF_OUTPUT = FIGURES / "08_asset_growth_comparison_2020.pdf"


SERIES = {
    "H0": {
        "column": "initial_hold",
        "label": "期初配置後持有（不定投）",
        "color": "#52525b",
        "linestyle": "--",
        "linewidth": 2.0,
    },
    "A": {
        "column": "fixed_dca",
        "label": "單純定投",
        "color": "#2563eb",
        "linestyle": "-",
        "linewidth": 2.1,
    },
    "B": {
        "column": "v31_shadow",
        "label": "V3.1 影子模型",
        "color": "#6d5a9c",
        "linestyle": "-.",
        "linewidth": 2.2,
    },
    "Q": {
        "column": "v310_champion",
        "label": "V3.10 最佳模型",
        "color": "#f7931a",
        "linestyle": "-",
        "linewidth": 3.0,
    },
}


def load_chart_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    daily = pd.read_csv(SOURCE, parse_dates=["date"])
    daily = daily.loc[daily["model"].isin(SERIES)].copy()
    if daily.empty or daily["model"].nunique() != len(SERIES):
        raise RuntimeError("REQUIRED_MODEL_SERIES_MISSING")
    if daily.duplicated(["model", "date"]).any():
        raise RuntimeError("DUPLICATE_MODEL_DATE")

    expected_dates = None
    for model in SERIES:
        dates = pd.Index(daily.loc[daily["model"].eq(model), "date"])
        if expected_dates is None:
            expected_dates = dates
        elif not dates.equals(expected_dates):
            raise RuntimeError(f"DATE_ALIGNMENT_FAIL: {model}")

    values = daily.pivot(index="date", columns="model", values="portfolio_value").sort_index()
    if values.isna().any().any():
        raise RuntimeError("PORTFOLIO_VALUE_MISSING")
    chart = pd.DataFrame(index=values.index)
    for model, spec in SERIES.items():
        chart[spec["column"]] = values[model]
    flow = (
        daily.loc[daily["model"].eq("A"), ["date", "external_flow"]]
        .set_index("date")["external_flow"]
        .astype(float)
        .sort_index()
    )
    chart["cumulative_invested_dca_models"] = 20_000.0 + flow.cumsum()
    chart.index.name = "date"

    summary = pd.read_csv(SUMMARY_SOURCE)
    summary = summary.loc[summary["model"].isin(SERIES)].copy()
    summary["display_name"] = summary["model"].map(lambda model: SERIES[model]["label"])
    summary = summary[[
        "model", "display_name", "start", "end", "initial_capital",
        "external_contributions_after_inception", "total_invested_capital",
        "final_portfolio_value", "twr_cagr", "maximum_drawdown", "calmar",
    ]].sort_values("final_portfolio_value", ascending=False)

    expected_final = chart.iloc[-1]
    for row in summary.itertuples(index=False):
        column = SERIES[row.model]["column"]
        if abs(float(row.final_portfolio_value) - float(expected_final[column])) > 1e-6:
            raise RuntimeError(f"SUMMARY_FINAL_VALUE_MISMATCH: {row.model}")
    return chart, summary


def draw_chart(chart: pd.DataFrame, summary: pd.DataFrame) -> None:
    plt.rcParams.update({
        "font.family": ["Microsoft JhengHei", "Microsoft JhengHei UI", "DejaVu Sans"],
        "font.size": 11,
        "axes.unicode_minus": False,
        "text.parse_math": False,
    })
    fig, ax = plt.subplots(figsize=(15, 8.5), dpi=180)
    fig.patch.set_facecolor("#fafafa")
    ax.set_facecolor("#ffffff")

    for model, spec in SERIES.items():
        ax.plot(
            chart.index,
            chart[spec["column"]],
            label=spec["label"],
            color=spec["color"],
            linestyle=spec["linestyle"],
            linewidth=spec["linewidth"],
            zorder=4 if model == "Q" else 3,
        )
    ax.plot(
        chart.index,
        chart["cumulative_invested_dca_models"],
        color="#a1a1aa",
        linestyle=":",
        linewidth=1.8,
        label="定投型策略累計投入本金",
        zorder=2,
    )

    last_date = chart.index[-1]
    label_offsets = {"Q": 14, "B": -10, "A": 4, "H0": -2}
    for model, spec in SERIES.items():
        final_value = float(chart.iloc[-1][spec["column"]])
        ax.annotate(
            f"{spec['label']}  ${final_value:,.0f}",
            xy=(last_date, final_value),
            xytext=(12, label_offsets[model]),
            textcoords="offset points",
            color=spec["color"],
            fontsize=10,
            fontweight="bold" if model == "Q" else "normal",
            va="center",
            bbox={"boxstyle": "round,pad=0.22", "fc": "white", "ec": "none", "alpha": 0.86},
        )

    ax.set_xlim(chart.index.min(), chart.index.max() + pd.Timedelta(days=310))
    ax.set_ylim(bottom=0)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _position: f"${value / 1000:,.0f}k"))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(axis="y", color="#e4e4e7", linewidth=0.8)
    ax.grid(axis="x", visible=False)
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#a1a1aa")
    ax.set_ylabel("總資產（美元）")
    ax.set_xlabel("")

    fig.suptitle("BTC＋ETH 資產成長比較", x=0.075, y=0.965, ha="left", fontsize=21, fontweight="bold", color="#18181b")
    ax.set_title(
        "2020-01-01 至 2026-09-03｜四套策略皆以 US$20,000 起始；定投型策略另投入 US$2／4H",
        loc="left",
        fontsize=11.5,
        color="#52525b",
        pad=16,
    )
    ax.legend(loc="upper left", ncol=3, frameon=False, fontsize=10.5, handlelength=3.2)

    dca_invested = float(summary.loc[summary["model"].eq("A"), "total_invested_capital"].iloc[0])
    fig.text(
        0.075,
        0.042,
        "註：『期初配置後持有』沿用公平起始配置（BTC＋ETH 70%、現金 30%），之後不追加投入、不戰術交易。\n"
        f"單純定投、V3.1、V3.10 的期末累計投入均為 US${dca_invested:,.0f}；V3.9 與 V3.10 歷史曲線完全重疊，故不重複繪製。",
        ha="left",
        va="bottom",
        fontsize=9.3,
        color="#52525b",
    )
    fig.text(
        0.99,
        0.015,
        "來源：Frozen V3.10 daily portfolio｜含既定手續費與滑價",
        ha="right",
        va="bottom",
        fontsize=8.8,
        color="#71717a",
    )
    fig.subplots_adjust(left=0.075, right=0.84, top=0.86, bottom=0.14)
    FIGURES.mkdir(parents=True, exist_ok=True)
    fig.savefig(PNG_OUTPUT, dpi=180, facecolor=fig.get_facecolor())
    fig.savefig(PDF_OUTPUT, facecolor=fig.get_facecolor())
    plt.close(fig)


def main() -> None:
    chart, summary = load_chart_data()
    chart.to_csv(DATA_OUTPUT, encoding="utf-8-sig")
    summary.to_csv(SUMMARY_OUTPUT, index=False, encoding="utf-8-sig")
    draw_chart(chart, summary)
    print(f"PNG={PNG_OUTPUT}")
    print(f"PDF={PDF_OUTPUT}")
    print(f"DATA={DATA_OUTPUT}")
    print(f"SUMMARY={SUMMARY_OUTPUT}")


if __name__ == "__main__":
    main()
