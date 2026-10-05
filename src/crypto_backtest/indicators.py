from __future__ import annotations

import numpy as np
import pandas as pd


def add_daily_indicators(df: pd.DataFrame, rules: dict, *, include_ahr: bool = False) -> pd.DataFrame:
    out = df.copy().sort_values("open_time").reset_index(drop=True)
    close = out["close"].astype(float)
    for window in (10, 20, 50, 200):
        out[f"sma{window}"] = close.rolling(window, min_periods=window).mean()
    out["bb_mid"] = out["sma20"]
    out["bb_std"] = close.rolling(20, min_periods=20).std(ddof=0)
    out["bb_upper"] = out["bb_mid"] + rules["overheat"]["bollinger_std"] * out["bb_std"]
    out["bb_lower"] = out["bb_mid"] - rules["overheat"]["bollinger_std"] * out["bb_std"]
    for window in (20, 50, 200):
        out[f"close_sma{window}_dev"] = close / out[f"sma{window}"] - 1.0
    out["avg_volume20"] = out["volume"].rolling(20, min_periods=20).mean()
    out["volume_ratio"] = out["volume"] / out["avg_volume20"]
    out["daily_return"] = close.pct_change()
    out["rolling_volatility20"] = out["daily_return"].rolling(20, min_periods=20).std(ddof=1) * np.sqrt(365.25)

    for window in (10, 20, 50):
        sma = out[f"sma{window}"]
        out[f"sma{window}_up"] = (sma > sma.shift(1)) & (sma > sma.shift(3))
        out[f"sma{window}_down"] = (sma < sma.shift(1)) & (sma < sma.shift(3))

    body = (out["close"] - out["open"]).abs()
    upper_wick = out["high"] - out[["open", "close"]].max(axis=1)
    lower_wick = out[["open", "close"]].min(axis=1) - out["low"]
    out["long_upper_wick"] = (upper_wick > rules["overheat"]["long_upper_wick_body_multiple"] * body.clip(lower=1e-12)) & (upper_wick > lower_wick)
    prior_20_high = out["high"].rolling(20, min_periods=20).max().shift(1)
    out["failed_breakout"] = (out["high"] > prior_20_high) & (out["close"] <= prior_20_high)
    out["lower_high_point_in_time"] = out["high"].rolling(5, min_periods=5).max() < out["high"].rolling(5, min_periods=5).max().shift(5)

    out = apply_overheat_thresholds(
        out,
        sma20_deviation=rules["overheat"]["sma20_deviation"],
        sma50_deviation=rules["overheat"]["sma50_deviation"],
        minimum_conditions=rules["overheat"]["minimum_conditions"],
    )

    out["stage1_condition"] = (
        (out["close"] < out["sma10"])
        & (out["close"].shift(1) < out["sma10"].shift(1))
        & (out["close"].shift(2) < out["sma10"].shift(2))
    )
    out["stage2_condition"] = (
        out["sma10_down"]
        & (out["close"] < out["sma20"])
        & (out["close"].shift(1) < out["sma20"].shift(1))
    )
    out["stage3_condition"] = (
        (out["sma10"] < out["sma20"])
        & out["sma20_down"]
        & (out["close"] < out["sma50"])
        & (out["close"].shift(1) < out["sma50"].shift(1))
    )
    out["intermediate_deterioration"] = out["sma20_down"] & (out["sma20"] < out["sma50"]) & (out["close"] < out["sma50"])
    out["stage4_condition"] = (
        (out["close"] < out["sma200"])
        & (out["close"].shift(1) < out["sma200"].shift(1))
        & (out["close"].shift(2) < out["sma200"].shift(2))
        & out["sma50_down"]
        & out["intermediate_deterioration"]
    )
    out["right_confirmation"] = (
        (out["close"] > out["sma20"])
        & (out["close"].shift(1) > out["sma20"].shift(1))
        & out["sma10_up"]
    )
    out["strong_confirmation"] = (
        out["right_confirmation"]
        & (out["close"] > out["sma50"])
        & out["sma20_up"]
        & (out["sma10"] > out["sma20"])
    )
    out["weakness_score"] = (
        (out["close"] < out["sma20"]).astype(int)
        + (out["close"] < out["sma50"]).astype(int)
        + out["sma10_down"].astype(int)
        + out["sma20_down"].astype(int)
    )

    if include_ahr:
        out = add_ahr999(out, rules)
    out["signal_date"] = out["open_time"].dt.floor("D")
    out["signal_available_at"] = out["signal_date"] + pd.Timedelta(days=1)
    return out


def apply_overheat_thresholds(
    df: pd.DataFrame,
    *,
    sma20_deviation: float,
    sma50_deviation: float,
    minimum_conditions: int,
) -> pd.DataFrame:
    out = df.copy()
    out["overheat_bb"] = out["close"] > out["bb_upper"]
    out["overheat_sma20"] = out["close_sma20_dev"] >= sma20_deviation
    out["overheat_sma50"] = out["close_sma50_dev"] >= sma50_deviation
    out["overheat_count"] = out[["overheat_bb", "overheat_sma20", "overheat_sma50"]].sum(axis=1)
    out["overheat_gate"] = out["overheat_count"] >= minimum_conditions
    return out


def add_ahr999(df: pd.DataFrame, rules: dict) -> pd.DataFrame:
    out = df.copy()
    genesis = pd.Timestamp(rules["ahr999"]["genesis_date"], tz="UTC")
    days = (out["open_time"] - genesis).dt.total_seconds() / 86_400.0
    log_days = np.log10(days)
    fitted_fixed = 10.0 ** (
        rules["ahr999"]["slope"] * log_days + rules["ahr999"]["intercept"]
    )
    out["ahr_fitted_fixed"] = fitted_fixed
    out["geometric_cost200"] = np.exp(
        np.log(out["close"].where(out["close"] > 0)).rolling(200, min_periods=200).mean()
    )
    out["ahr999_fixed_arithmetic"] = (out["close"] / out["sma200"]) * (out["close"] / fitted_fixed)
    out["ahr999_fixed_geometric"] = (out["close"] / out["geometric_cost200"]) * (out["close"] / fitted_fixed)

    x = log_days.to_numpy(dtype=float)
    y = np.log10(out["close"].to_numpy(dtype=float))
    valid = np.isfinite(x) & np.isfinite(y)
    xv = np.where(valid, x, 0.0)
    yv = np.where(valid, y, 0.0)
    n = np.cumsum(valid.astype(float))
    sx = np.cumsum(xv)
    sy = np.cumsum(yv)
    sxx = np.cumsum(xv * xv)
    sxy = np.cumsum(xv * yv)
    # Strictly point-in-time: shift cumulative sufficient statistics by one day.
    n_lag = np.r_[np.nan, n[:-1]]
    sx_lag = np.r_[np.nan, sx[:-1]]
    sy_lag = np.r_[np.nan, sy[:-1]]
    sxx_lag = np.r_[np.nan, sxx[:-1]]
    sxy_lag = np.r_[np.nan, sxy[:-1]]
    denom = n_lag * sxx_lag - sx_lag * sx_lag
    slope = np.full_like(denom, np.nan, dtype=float)
    np.divide(
        n_lag * sxy_lag - sx_lag * sy_lag,
        denom,
        out=slope,
        where=np.isfinite(denom) & (denom != 0),
    )
    intercept = np.full_like(n_lag, np.nan, dtype=float)
    np.divide(
        sy_lag - slope * sx_lag,
        n_lag,
        out=intercept,
        where=np.isfinite(n_lag) & (n_lag > 0),
    )
    minimum = int(rules["ahr999"]["expanding_min_observations"])
    slope = np.where(n_lag >= minimum, slope, np.nan)
    intercept = np.where(n_lag >= minimum, intercept, np.nan)
    out["ahr_expanding_slope"] = slope
    out["ahr_expanding_intercept"] = intercept
    out["ahr_fitted_expanding"] = 10.0 ** (slope * x + intercept)
    out["ahr999_expanding_arithmetic"] = (
        (out["close"] / out["sma200"]) * (out["close"] / out["ahr_fitted_expanding"])
    )
    return out


def build_primary_daily(
    bitstamp_daily: pd.DataFrame,
    binance_btc_daily: pd.DataFrame,
    rules: dict,
) -> tuple[pd.DataFrame, str]:
    switch = binance_btc_daily["open_time"].min()
    pre = bitstamp_daily.loc[bitstamp_daily["open_time"] < switch].copy()
    pre["daily_source"] = "Bitstamp BTCUSD"
    post = binance_btc_daily.copy()
    post["daily_source"] = "Binance Spot BTCUSDT"
    hybrid = pd.concat([pre, post], ignore_index=True).sort_values("open_time")
    hybrid = hybrid.drop_duplicates("open_time", keep="last").reset_index(drop=True)
    return add_daily_indicators(hybrid, rules, include_ahr=True), switch.isoformat()


def merge_daily_signals_to_bars(
    bars: pd.DataFrame,
    btc_daily: pd.DataFrame,
    asset_daily: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    signal_cols = [
        "signal_date",
        "signal_available_at",
        "daily_source",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "sma10",
        "sma20",
        "sma50",
        "sma200",
        "bb_upper",
        "bb_lower",
        "close_sma20_dev",
        "close_sma50_dev",
        "close_sma200_dev",
        "volume_ratio",
        "daily_return",
        "rolling_volatility20",
        "sma10_up",
        "sma10_down",
        "sma20_up",
        "sma20_down",
        "sma50_down",
        "overheat_bb",
        "overheat_sma20",
        "overheat_sma50",
        "overheat_count",
        "overheat_gate",
        "long_upper_wick",
        "failed_breakout",
        "lower_high_point_in_time",
        "stage1_condition",
        "stage2_condition",
        "stage3_condition",
        "stage4_condition",
        "intermediate_deterioration",
        "right_confirmation",
        "strong_confirmation",
        "ahr999_fixed_arithmetic",
        "ahr999_fixed_geometric",
        "ahr999_expanding_arithmetic",
    ]
    daily = btc_daily[signal_cols].rename(
        columns={
            "open": "BTC_daily_open",
            "high": "BTC_daily_high",
            "low": "BTC_daily_low",
            "close": "BTC_daily_close",
            "volume": "BTC_daily_volume",
        }
    )
    out = pd.merge_asof(
        bars.sort_values("open_time"),
        daily.sort_values("signal_available_at"),
        left_on="open_time",
        right_on="signal_available_at",
        direction="backward",
        allow_exact_matches=True,
    )
    for asset, ddf in asset_daily.items():
        weak = ddf[["signal_available_at", "weakness_score"]].rename(
            columns={"weakness_score": f"{asset}_weakness_score"}
        )
        out = pd.merge_asof(
            out.sort_values("open_time"),
            weak.sort_values("signal_available_at"),
            on="signal_available_at",
            direction="backward",
            allow_exact_matches=True,
        )
    return out.sort_values("open_time").reset_index(drop=True)
