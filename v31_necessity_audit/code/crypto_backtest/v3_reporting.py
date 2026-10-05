from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


A_NAME = "A - Fixed DCA Champion"
E20_NAME = "V3-E20 - Fixed DCA + Macro Cycle Hedge"
COLORS = {
    A_NAME: "#4C78A8",
    E20_NAME: "#E45756",
    "V3-E30 - Fixed DCA + Macro Cycle Hedge": "#72B7B2",
    "V3-E40 - Fixed DCA + Macro Cycle Hedge": "#F2CF5B",
}
REGIMES = ["BULL", "LATE_BULL", "DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR", "ACCUMULATION", "NEW_BULL"]
REGIME_MAP = {name: index for index, name in enumerate(REGIMES)}


def _save(fig: plt.Figure, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(base.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(
        base.with_suffix(".pdf"),
        bbox_inches="tight",
        metadata={"CreationDate": None, "ModDate": None},
    )
    plt.close(fig)


def create_v3_figures(
    v3_dir: Path,
    daily_by_strategy: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    trades: pd.DataFrame,
) -> None:
    figure_dir = v3_dir / "figures"
    e20 = daily_by_strategy[E20_NAME]
    e20_signals = signals.loc[signals["strategy"].eq(E20_NAME)].copy()
    e20_trades = trades.loc[trades["strategy"].eq(E20_NAME)].copy()
    plt.style.use("default")

    fig, ax = plt.subplots(figsize=(11, 6))
    for strategy, daily in daily_by_strategy.items():
        ax.plot(daily["date"], daily["portfolio_value"], label=strategy, color=COLORS[strategy], lw=1.3)
    ax.set(title="V3 Portfolio Equity Curves", xlabel="UTC date", ylabel="Portfolio value (USD)")
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    _save(fig, figure_dir / "01_equity_curve")

    fig, ax = plt.subplots(figsize=(11, 5.5))
    for strategy, daily in daily_by_strategy.items():
        ax.plot(daily["date"], 100 * daily["drawdown"], label=strategy, color=COLORS[strategy], lw=1.2)
    ax.set(title="V3 Drawdown Curves", xlabel="UTC date", ylabel="Drawdown (%)")
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    _save(fig, figure_dir / "02_drawdown_curve")

    fig, ax = plt.subplots(figsize=(11, 5))
    for strategy, daily in daily_by_strategy.items():
        ax.plot(daily["date"], 100 * daily["crypto_exposure"], label=strategy, color=COLORS[strategy], lw=1.2)
    ax.set(title="Daily Crypto Exposure", xlabel="UTC date", ylabel="Crypto exposure (%)", ylim=(0, 105))
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    _save(fig, figure_dir / "03_crypto_exposure")

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True, gridspec_kw={"height_ratios": [2.2, 1, 1]})
    axes[0].plot(e20["date"], e20["btc_close"], color="#4C78A8", lw=1.1, label="BTC completed-daily close")
    axes[0].plot(e20["date"], e20["sma50"], color="#F58518", lw=0.9, label="SMA50")
    axes[0].plot(e20["date"], e20["sma200"], color="#54A24B", lw=0.9, label="SMA200")
    axes[0].set_yscale("log"); axes[0].set_ylabel("BTC USD (log)"); axes[0].legend(fontsize=8)
    axes[1].step(e20["date"], e20["macro_regime_current"].map(REGIME_MAP), where="post", color="#54A24B")
    axes[1].set_yticks(range(len(REGIMES)), REGIMES, fontsize=7); axes[1].set_ylabel("Macro FSM")
    axes[2].step(e20["date"], e20["sell_stage"], where="post", color="#B279A2")
    axes[2].set_yticks([0, 1, 2, 3, 4]); axes[2].set_ylabel("Sell stage"); axes[2].set_xlabel("UTC date")
    for ax in axes: ax.grid(alpha=0.22)
    fig.suptitle("E20 BTC Trend, Macro Regime and Tactical Stage")
    fig.tight_layout()
    _save(fig, figure_dir / "04_e20_regime_stage")

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.plot(e20["date"], 100 * e20["tactical_cash_ratio"], label="Tactical cash", color="#E45756")
    ax.plot(e20["date"], 100 * e20["normal_cash_ratio"], label="Normal cash", color="#72B7B2")
    ax.plot(e20["date"], 100 * e20["crypto_exposure"], label="Crypto exposure", color="#4C78A8")
    ax.axhline(1, color="gray", ls=":", lw=0.8, label="1% material-cash threshold")
    ax.set(title="E20 Cash and Crypto Exposure", xlabel="UTC date", ylabel="Portfolio share (%)", ylim=(0, 105))
    ax.grid(alpha=0.25); ax.legend(fontsize=8)
    _save(fig, figure_dir / "05_e20_cash_exposure")

    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.plot(e20["date"], e20["btc_close"], color="#4C78A8", lw=1.0, label="BTC close")
    marker_specs = [
        (e20_signals["regime_after"].eq("DISTRIBUTION") & e20_signals["regime_before"].isin(["BULL", "LATE_BULL"]), "Stage 1", "v", "#F58518"),
        (e20_signals["regime_after"].eq("EARLY_BEAR") & ~e20_signals["regime_before"].eq("EARLY_BEAR"), "Stage 2", "v", "#E45756"),
        (e20_signals["regime_after"].eq("BEAR") & e20_signals["regime_before"].eq("EARLY_BEAR"), "Stage 3", "v", "#B279A2"),
        (e20_signals["regime_after"].eq("DEEP_BEAR") & ~e20_signals["regime_before"].eq("DEEP_BEAR"), "Stage 4", "v", "#9D755D"),
        (e20_signals["crash_override_event"].fillna(False).astype(bool), "Crash override", "X", "black"),
        (e20_signals["regime_after"].eq("NEW_BULL") & ~e20_signals["regime_before"].eq("NEW_BULL"), "NEW_BULL", "^", "#54A24B"),
    ]
    for mask, label, marker, color in marker_specs:
        points = e20_signals.loc[mask]
        if not points.empty:
            ax.scatter(points["signal_date"], points["btc_close"], marker=marker, s=42, color=color, label=label, zorder=4)
    buy_specs = [
        (e20_trades["action"].str.contains("AHR_", na=False), "AHR buyback", "o", "#59A14F"),
        (e20_trades["action"].eq("TACTICAL_BUYBACK_RIGHT_RECOVERY"), "Right-side recovery", "P", "#76B7B2"),
        (e20_trades["action"].eq("TACTICAL_BUYBACK_NEW_BULL_REDEPLOY"), "NEW_BULL redeploy", "D", "#54A24B"),
    ]
    for mask, label, marker, color in buy_specs:
        buy_events = e20_trades.loc[e20_trades["side"].eq("BUY") & mask].drop_duplicates("tactical_event_id")
        if buy_events.empty:
            continue
        prices = pd.merge_asof(
            buy_events.sort_values("timestamp"), e20[["date", "btc_close"]].sort_values("date"),
            left_on="timestamp", right_on="date", direction="backward"
        )
        ax.scatter(
            prices["timestamp"], prices["btc_close"], marker=marker, facecolors="none",
            edgecolors=color, s=48, label=label, zorder=4,
        )
    ax.set_yscale("log"); ax.set(title="E20 Cycle Events", xlabel="UTC date", ylabel="BTC USD (log)")
    ax.grid(alpha=0.25); ax.legend(fontsize=7, ncol=3)
    _save(fig, figure_dir / "06_e20_cycle_events")

    start, end = pd.Timestamp("2021-01-01", tz="UTC"), pd.Timestamp("2022-12-31", tz="UTC")
    z = e20.loc[e20["date"].between(start, end)].copy()
    fig, axes = plt.subplots(5, 1, figsize=(13, 12), sharex=True)
    axes[0].plot(z["date"], z["btc_close"], color="#4C78A8", lw=1.1); axes[0].plot(z["date"], z["sma200"], color="#54A24B", lw=0.9)
    axes[0].set_ylabel("BTC / SMA200")
    for strategy, daily in daily_by_strategy.items():
        dz = daily.loc[daily["date"].between(start, end)]
        axes[1].plot(dz["date"], dz["portfolio_value"], color=COLORS[strategy], lw=1.0, label=strategy)
    axes[1].set_ylabel("Portfolio USD"); axes[1].legend(fontsize=6, ncol=2)
    axes[2].plot(z["date"], 100 * z["crypto_exposure"], color="#4C78A8"); axes[2].plot(z["date"], 100 * z["active_exposure_target"], color="#E45756", ls="--")
    axes[2].set_ylabel("Exposure %")
    axes[3].plot(z["date"], 100 * z["tactical_cash_ratio"], color="#E45756"); axes[3].set_ylabel("Tactical cash %")
    axes[4].step(z["date"], z["macro_regime_current"].map(REGIME_MAP), where="post", color="#54A24B")
    axes[4].set_yticks(range(len(REGIMES)), REGIMES, fontsize=7); axes[4].set_ylabel("FSM"); axes[4].set_xlabel("UTC date")
    for ax in axes: ax.grid(alpha=0.22)
    fig.suptitle("V3 Critical Audit: 2021–2022")
    fig.tight_layout()
    _save(fig, figure_dir / "07_2021_2022_zoom")


def build_audit_case_table(
    daily: pd.DataFrame,
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    windows: dict[str, list[str]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    latest = pd.Timestamp(daily["date"].max())
    for label, bounds in windows.items():
        start = pd.Timestamp(bounds[0], tz="UTC")
        end = latest if bounds[1] == "end" else pd.Timestamp(bounds[1], tz="UTC")
        d = daily.loc[daily["date"].between(start, end)]
        s = signals.loc[pd.to_datetime(signals["signal_date"], utc=True).between(start, end)]
        t = trades.loc[pd.to_datetime(trades["timestamp"], utc=True).between(start, end)]
        if d.empty:
            continue
        rows.append(
            {
                "case": label,
                "start": d["date"].min(),
                "end": d["date"].max(),
                "regimes": "|".join(dict.fromkeys(d["macro_regime_current"].astype(str))),
                "maximum_stage": int(d["sell_stage"].max()),
                "minimum_crypto_exposure": float(d["crypto_exposure"].min()),
                "maximum_crypto_exposure": float(d["crypto_exposure"].max()),
                "ending_crypto_exposure": float(d.iloc[-1]["crypto_exposure"]),
                "maximum_tactical_cash_ratio": float(d["tactical_cash_ratio"].max()),
                "ending_tactical_cash": float(d.iloc[-1]["tactical_cash"]),
                "minimum_portfolio_drawdown": float(d["drawdown"].min()),
                "crash_override_events": int(s["crash_override_event"].fillna(False).astype(bool).sum()),
                "new_bull_confirmations": int((s["regime_after"].eq("NEW_BULL") & ~s["regime_before"].eq("NEW_BULL")).sum()),
                "tactical_trade_rows": int(t["action"].str.startswith("TACTICAL", na=False).sum()),
            }
        )
    return pd.DataFrame(rows)


def _usd(value: float) -> str:
    return f"US${value:,.2f}"


def _pct(value: float) -> str:
    return f"{100 * value:.2f}%"


def _iso(value: Any) -> str:
    return "none" if pd.isna(value) else pd.Timestamp(value).isoformat()


def _performance_table(summary: pd.DataFrame) -> str:
    columns = ["strategy", "final_portfolio_value", "external_contributions", "xirr", "time_weighted_cagr", "maximum_drawdown", "calmar", "average_crypto_exposure", "material_tactical_cash_time", "tactical_turnover", "total_trading_costs"]
    view = summary[columns].copy()
    for column in ("final_portfolio_value", "external_contributions", "total_trading_costs"):
        view[column] = view[column].map(_usd)
    for column in ("xirr", "time_weighted_cagr", "maximum_drawdown", "average_crypto_exposure", "material_tactical_cash_time"):
        view[column] = view[column].map(_pct)
    view["calmar"] = view["calmar"].map(lambda value: f"{value:.4f}")
    view["tactical_turnover"] = view["tactical_turnover"].map(lambda value: f"{value:.3f}x")
    lines = ["| " + " | ".join(view.columns) + " |", "| " + " | ".join("---" for _ in view.columns) + " |"]
    lines.extend("| " + " | ".join(str(value) for value in values) + " |" for values in view.itertuples(index=False, name=None))
    return "\n".join(lines)


def _markdown_table(frame: pd.DataFrame) -> str:
    """Render a DataFrame without the optional third-party ``tabulate`` package."""
    columns = [str(column).replace("|", "\\|") for column in frame.columns]
    lines = ["| " + " | ".join(columns) + " |", "| " + " | ".join("---" for _ in columns) + " |"]
    for values in frame.itertuples(index=False, name=None):
        rendered = []
        for value in values:
            if pd.isna(value):
                text = ""
            elif isinstance(value, float):
                text = f"{value:.6g}"
            else:
                text = str(value)
            rendered.append(text.replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(rendered) + " |")
    return "\n".join(lines)


def write_v3_report(
    v3_dir: Path,
    summary: pd.DataFrame,
    daily_by_strategy: dict[str, pd.DataFrame],
    signals: pd.DataFrame,
    trades: pd.DataFrame,
    cycles: pd.DataFrame,
    fsm_audit: pd.DataFrame,
    conflicts: pd.DataFrame,
    audit: dict[str, Any],
    audit_cases: pd.DataFrame,
    v2_tactical_turnover: float,
    rules: dict[str, Any],
) -> str:
    by_name = summary.set_index("strategy")
    a, e20 = by_name.loc[A_NAME], by_name.loc[E20_NAME]
    e20_daily = daily_by_strategy[E20_NAME]
    e20_signals = signals.loc[signals["strategy"].eq(E20_NAME)].copy()
    e20_trades = trades.loc[trades["strategy"].eq(E20_NAME)].copy()
    e20_cycles = cycles.loc[cycles["strategy"].eq(E20_NAME)].copy()
    final_delta = float(e20["final_portfolio_value"] - a["final_portfolio_value"])
    cagr_delta = float(e20["time_weighted_cagr"] - a["time_weighted_cagr"])
    dd_delta = float(e20["maximum_drawdown"] - a["maximum_drawdown"])
    calmar_delta = float(e20["calmar"] - a["calmar"])
    exchange_ratio = (-100 * cagr_delta / (100 * dd_delta)) if dd_delta > 0 else np.nan
    turnover_reduction = 1.0 - float(e20["tactical_turnover"]) / v2_tactical_turnover if v2_tactical_turnover > 0 else np.nan

    may_start, may_end = pd.Timestamp("2021-05-10", tz="UTC"), pd.Timestamp("2021-05-31", tz="UTC")
    may_signals = e20_signals.loc[pd.to_datetime(e20_signals["signal_date"], utc=True).between(may_start, may_end)]
    risk_off = may_signals.loc[
        may_signals["crash_override_event"].fillna(False).astype(bool)
        | (may_signals["regime_after"].isin(["DISTRIBUTION", "EARLY_BEAR", "BEAR", "DEEP_BEAR"]) & ~may_signals["regime_before"].eq(may_signals["regime_after"]))
    ]
    first_risk_off = "none" if risk_off.empty else pd.Timestamp(risk_off.iloc[0]["signal_date"]).isoformat()
    first_stage1_rows = may_signals.loc[may_signals["regime_after"].eq("DISTRIBUTION") & ~may_signals["regime_before"].eq("DISTRIBUTION")]
    first_stage1 = "none" if first_stage1_rows.empty else pd.Timestamp(first_stage1_rows.iloc[0]["signal_date"]).isoformat()
    first_30k = may_signals.loc[may_signals["btc_low"].astype(float) <= 30_000]
    exposure_before_30k = np.nan
    if not first_30k.empty:
        cutoff = pd.Timestamp(first_30k.iloc[0]["signal_date"])
        exposure_before_30k = float(e20_daily.loc[e20_daily["date"] <= cutoff, "crypto_exposure"].iloc[-1])

    feb = e20_signals.loc[pd.to_datetime(e20_signals["signal_date"], utc=True).between(pd.Timestamp("2022-02-01", tz="UTC"), pd.Timestamp("2022-02-28", tz="UTC"))]
    feb_new_bull = int((feb["regime_after"].eq("NEW_BULL") & ~feb["regime_before"].eq("NEW_BULL")).sum())
    feb_daily = e20_daily.loc[e20_daily["date"].between(pd.Timestamp("2022-02-01", tz="UTC"), pd.Timestamp("2022-02-28", tz="UTC"))]
    feb_max_exposure = float(feb_daily["crypto_exposure"].max())

    may_cycle_rows = e20_cycles.loc[
        (pd.to_datetime(e20_cycles["cycle_start"], utc=True) <= may_end)
        & (
            pd.to_datetime(e20_cycles["cycle_end"], utc=True).isna()
            | (pd.to_datetime(e20_cycles["cycle_end"], utc=True) >= may_start)
        )
    ].sort_values("cycle_start")
    may_cycle = None if may_cycle_rows.empty else may_cycle_rows.iloc[-1]
    may_episode_stage1_signal = "none" if may_cycle is None else _iso(may_cycle["stage_1_date"])
    may_episode_stage1_execution = "none" if may_cycle is None else _iso(may_cycle["stage_1_execution"])
    may_max_exposure = float(e20_daily.loc[e20_daily["date"].between(may_start, may_end), "crypto_exposure"].max())

    top_cycle_rows = e20_cycles.loc[
        e20_cycles["cycle_confirmed"].astype(bool)
        & pd.to_datetime(e20_cycles["stage_1_date"], utc=True).between(
            pd.Timestamp("2021-11-01", tz="UTC"), pd.Timestamp("2021-12-31", tz="UTC")
        )
    ].sort_values("stage_1_date")
    top_cycle = None if top_cycle_rows.empty else top_cycle_rows.iloc[0]
    stage_rows: list[dict[str, Any]] = []
    if top_cycle is not None:
        for stage in range(1, 5):
            stage_rows.append(
                {
                    "stage": stage,
                    "signal_date": _iso(top_cycle[f"stage_{stage}_date"]),
                    "execution": _iso(top_cycle[f"stage_{stage}_execution"]),
                    "btc_signal_close": (
                        "" if pd.isna(top_cycle[f"stage_{stage}_btc_price"])
                        else f"US${float(top_cycle[f'stage_{stage}_btc_price']):,.2f}"
                    ),
                    "post_trade_exposure": (
                        "" if pd.isna(top_cycle[f"stage_{stage}_portfolio_exposure"])
                        else _pct(float(top_cycle[f"stage_{stage}_portfolio_exposure"]))
                    ),
                }
            )
    top_stage_table = _markdown_table(pd.DataFrame(stage_rows)) if stage_rows else "No matching confirmed cycle."

    jan_jun = e20_daily.loc[
        e20_daily["date"].between(pd.Timestamp("2022-01-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC"))
    ].copy()
    jan_jun["month"] = jan_jun["date"].dt.strftime("%Y-%m")
    monthly_path = jan_jun.groupby("month", as_index=False).agg(
        minimum_exposure=("crypto_exposure", "min"),
        maximum_exposure=("crypto_exposure", "max"),
        month_end_exposure=("crypto_exposure", "last"),
        month_end_tactical_cash=("tactical_cash", "last"),
    )
    for column in ("minimum_exposure", "maximum_exposure", "month_end_exposure"):
        monthly_path[column] = monthly_path[column].map(_pct)
    monthly_path["month_end_tactical_cash"] = monthly_path["month_end_tactical_cash"].map(_usd)
    monthly_path_table = _markdown_table(monthly_path)

    june_tactical = e20_trades.loc[
        pd.to_datetime(e20_trades["timestamp"], utc=True).between(
            pd.Timestamp("2022-06-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC")
        )
        & e20_trades["action"].str.startswith("TACTICAL", na=False)
    ].copy()
    if june_tactical.empty:
        june_trade_summary = "none"
    else:
        june_events = june_tactical.groupby("tactical_event_id", as_index=False).agg(
            timestamp=("timestamp", "min"), action=("action", "first"), reason=("reason", "first"),
            before_exposure=("before_crypto_exposure", "first"), after_exposure=("after_crypto_exposure", "last"),
            gross_notional=("gross_notional_usd", "sum"),
        )
        june_events["timestamp"] = june_events["timestamp"].map(_iso)
        june_events["before_exposure"] = june_events["before_exposure"].map(_pct)
        june_events["after_exposure"] = june_events["after_exposure"].map(_pct)
        june_events["gross_notional"] = june_events["gross_notional"].map(_usd)
        june_trade_summary = _markdown_table(june_events.drop(columns="tactical_event_id"))

    bull_start, bull_end = pd.Timestamp("2023-01-01", tz="UTC"), pd.Timestamp("2025-12-31", tz="UTC")
    bull_daily = e20_daily.loc[e20_daily["date"].between(bull_start, bull_end)]
    bull_signals = e20_signals.loc[pd.to_datetime(e20_signals["signal_date"], utc=True).between(bull_start, bull_end)]
    bull_new = int((bull_signals["regime_after"].eq("NEW_BULL") & ~bull_signals["regime_before"].eq("NEW_BULL")).sum())
    bull_reset = int((bull_signals["regime_before"].eq("NEW_BULL") & bull_signals["regime_after"].eq("BULL")).sum())
    bull_material_cash_time = float((bull_daily["tactical_cash_ratio"] > float(rules["material_tactical_cash_ratio"])).mean())

    correction = e20_daily.loc[e20_daily["date"] >= pd.Timestamp("2025-01-01", tz="UTC")]
    correction_last = correction.iloc[-1]

    june = e20_daily.loc[e20_daily["date"].between(pd.Timestamp("2022-06-01", tz="UTC"), pd.Timestamp("2022-06-30", tz="UTC"))]
    june_low = june.iloc[int(june["btc_close"].astype(float).to_numpy().argmin())]
    confirmed_cycles = e20_cycles.loc[e20_cycles["cycle_confirmed"].astype(bool)]
    yearly = confirmed_cycles.assign(year=pd.to_datetime(confirmed_cycles["cycle_confirmed_date"], utc=True).dt.year).groupby("year").size()
    max_cycles_year = int(yearly.max()) if not yearly.empty else 0

    gates = rules["evaluation_gates"]
    material_dd = 100 * dd_delta > float(gates["material_max_drawdown_improvement_pp_strictly_greater_than"])
    calmar_edge = calmar_delta > 0
    feb_pass = feb_new_bull == 0 and feb_max_exposure < float(gates["false_bull_maximum_exposure"])
    may_pass = not risk_off.empty
    turnover_pass = np.isfinite(turnover_reduction) and turnover_reduction >= float(gates["turnover_reduction_minimum_fraction"])
    promotion = bool(audit["pass"] and material_dd and calmar_edge and feb_pass and may_pass and turnover_pass)
    if promotion:
        verdict = "V3 PROMOTED TO FORWARD PAPER TEST"
    elif not material_dd and not calmar_edge and float(a["final_portfolio_value"]) >= float(e20["final_portfolio_value"]):
        verdict = "FIXED DCA REMAINS SOLE CHAMPION"
    else:
        verdict = "V3 NEEDS REDESIGN"

    report = f"""# Crypto Fixed DCA + Macro Cycle Hedge V3.0 — Final Report

## Validity

- Formal period: {a['start']} to {a['end']}; 2019 is indicator warm-up only.
- Model A is the unchanged V1 Fixed DCA engine; V3 only replays its DCA ledger.
- Frozen models: A, V3-E20, V3-E30, V3-E40. No threshold search or audit-date trading logic.
- Fixed DCA row integrity: **{'PASS' if audit['fixed_dca_row_integrity_pass'] else 'FAIL'}**.
- No-look-ahead audit: **{'PASS' if audit['pass'] else 'FAIL'}**.
- FSM illegal transitions: **{audit['illegal_transition_count']}**.
- Buy/sell conflicts: **{len(conflicts)}**.

## Performance

{_performance_table(summary)}

## Required answers

1. Fixed DCA final value: **{_usd(float(a['final_portfolio_value']))}**.
2. V3-E20 final value: **{_usd(float(e20['final_portfolio_value']))}**.
3. Max DD — A {_pct(float(a['maximum_drawdown']))}; E20 {_pct(float(e20['maximum_drawdown']))}; improvement {100 * dd_delta:.2f} pp.
4. Peak/trough — A {a['max_dd_peak_date']} → {a['max_dd_trough_date']}; E20 {e20['max_dd_peak_date']} → {e20['max_dd_trough_date']}.
5. 2021/05 — first risk-off signal inside 5/10–5/31: {first_risk_off}; Stage 1 inside that window: {first_stage1}. The active episode had already entered Stage 1 on {may_episode_stage1_signal} and executed on {may_episode_stage1_execution}. Crash events {int(may_signals['crash_override_event'].fillna(False).astype(bool).sum())}; maximum May exposure {_pct(may_max_exposure)}; exposure by first BTC intraday low at/below US$30K {_pct(exposure_before_30k) if np.isfinite(exposure_before_30k) else 'not observed in completed daily audit rows'}.
6. 2022/02 NEW_BULL misclassification: **{'YES' if feb_new_bull else 'NO'}**; confirmations {feb_new_bull}, maximum E20 exposure {_pct(feb_max_exposure)}.
7. 2022/06 BTC completed-daily low date {pd.Timestamp(june_low['date']).isoformat()}: E20 crypto exposure {_pct(float(june_low['crypto_exposure']))}, tactical cash {_usd(float(june_low['tactical_cash']))}, AHR999 {float(june_low['ahr999']):.4f}, state {june_low['macro_regime_current']}/Stage {int(june_low['sell_stage'])}.
8. Confirmed Macro Cycle count: **{len(confirmed_cycles)}**; maximum in one year {max_cycles_year}.
9. Tactical turnover: V2-E20 {v2_tactical_turnover:.3f}x → V3-E20 {float(e20['tactical_turnover']):.3f}x; reduction {100 * turnover_reduction:.2f}%.
10. E20 Calmar improvement: **{'YES' if calmar_edge else 'NO'}**; A {float(a['calmar']):.4f}, E20 {float(e20['calmar']):.4f}, delta {calmar_delta:.4f}.
11. Forward paper test: **{'YES' if promotion else 'NO'}** under the frozen gates.
12. J Law verdict: **{verdict}**.

## V3-E20 versus A

- Delta final value: {_usd(final_delta)}.
- Delta TWR CAGR: {100 * cagr_delta:.2f} pp.
- Delta Max DD: {100 * dd_delta:.2f} pp.
- Delta Calmar: {calmar_delta:.4f}.
- CAGR sacrificed per 1 pp Max-DD improvement: {exchange_ratio:.3f} pp (negative means CAGR increased rather than being sacrificed).

## 2021/11 top to 2022 bear: stage path

{top_stage_table}

## 2022/01–06 E20 exposure path

{monthly_path_table}

## 2022/06 tactical actions

{june_trade_summary}

## Later-cycle checks

- 2023–2025 NEW_BULL confirmations: {bull_new}; completed NEW_BULL → BULL resets: {bull_reset}; maximum crypto exposure {_pct(float(bull_daily['crypto_exposure'].max()))}.
- 2023–2025 material tactical-cash time: {_pct(bull_material_cash_time)}. This fails the qualitative goal of avoiding persistent large cash balances even though the frozen numerical promotion gates did not assign a separate threshold to it.
- Latest 2025–2026 correction row: {_iso(correction_last['date'])}, state {correction_last['macro_regime_current']}/Stage {int(correction_last['sell_stage'])}, crypto exposure {_pct(float(correction_last['crypto_exposure']))}, tactical cash {_usd(float(correction_last['tactical_cash']))}.

## Audit-case summary

{_markdown_table(audit_cases)}

## J Law decision

- Champion: A — Fixed DCA.
- Challenger: V3-E20 — Fixed DCA + Macro Cycle Hedge.
- Return Edge: {'Champion' if float(a['time_weighted_cagr']) >= float(e20['time_weighted_cagr']) else 'Challenger'}.
- Drawdown Edge: {'Challenger' if dd_delta > 0 else 'Champion'}; substantive-gate {'PASS' if material_dd else 'FAIL'}.
- Calmar Edge: {'Challenger' if calmar_edge else 'Champion'}.
- Cash Drag: average tactical cash {_pct(float(e20['average_tactical_cash_ratio']))}; material-cash time {_pct(float(e20['material_tactical_cash_time']))}; raw-positive time {_pct(float(e20['raw_tactical_cash_positive_time']))}.
- Timing Quality: May reaction {'PASS' if may_pass else 'FAIL'}; February false-bull gate {'PASS' if feb_pass else 'FAIL'}.
- Crash Protection: {int(may_signals['crash_override_event'].fillna(False).astype(bool).sum())} May-2021 event(s); all events and forward MAE/MFE are in `crash_override_audit_v3.csv`.
- False-Bull Risk: {'controlled in the February audit' if feb_pass else 'still present'}.
- Turnover: reduction gate {'PASS' if turnover_pass else 'FAIL'} versus V2-E20.
- Execution Integrity: {'PASS' if audit['pass'] else 'FAIL'}.
- Overfit Risk: Medium-high. The rules were frozen and no search was run, but the historical sample contains few independent macro cycles and a complex rule tree.

**FINAL VERDICT: {verdict}**

## Important design boundary

The strict supplied FSM contains no bullish redeployment path for tactical cash produced by a Crash-only overlay or an aborted Distribution that never becomes a confirmed bear. This run does not invent one. Any resulting cash persistence is therefore a specification limitation, not silently relabelled as a successful hedge. The 20/30/40% floor remains a sell-time constraint; market moves may naturally push daily exposure below it.
"""
    report_dir = v3_dir / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "FINAL_REPORT_V3.md").write_text(report, encoding="utf-8")
    return verdict
