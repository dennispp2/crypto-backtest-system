from __future__ import annotations

import gzip
import hashlib
import json
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


BINANCE_KLINES = "https://api.binance.com/api/v3/klines"
BINANCE_TIME = "https://api.binance.com/api/v3/time"
BITSTAMP_OHLC = "https://www.bitstamp.net/api/v2/ohlc/btcusd/"

KLINE_COLUMNS = [
    "open_time_ms",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time_ms",
    "quote_volume",
    "trade_count",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]

INTERVAL_MS = {"4h": 4 * 60 * 60 * 1000, "1d": 24 * 60 * 60 * 1000}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _get_json(url: str, *, retries: int = 6, timeout: int = 60) -> Any:
    last_error: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "crypto-backtest-research/1.0",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network failures are retried and then surfaced
            last_error = exc
            time.sleep(min(8.0, 0.5 * (2**attempt)))
    raise RuntimeError(f"GET failed after {retries} attempts: {url}") from last_error


def binance_server_time_ms() -> int:
    return int(_get_json(BINANCE_TIME)["serverTime"])


def download_binance_klines(
    symbol: str,
    interval: str,
    start_time_ms: int,
    end_time_ms: int,
) -> pd.DataFrame:
    if interval not in INTERVAL_MS:
        raise ValueError(f"Unsupported interval: {interval}")
    rows: list[list[Any]] = []
    cursor = int(start_time_ms)
    while cursor <= end_time_ms:
        query = urllib.parse.urlencode(
            {
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_time_ms,
                "limit": 1000,
            }
        )
        batch = _get_json(f"{BINANCE_KLINES}?{query}")
        if not batch:
            break
        rows.extend(batch)
        next_cursor = int(batch[-1][0]) + INTERVAL_MS[interval]
        if next_cursor <= cursor:
            raise RuntimeError(f"Binance cursor did not advance for {symbol} {interval}")
        cursor = next_cursor
        if len(batch) < 1000:
            break
        time.sleep(0.03)

    if not rows:
        raise RuntimeError(f"No Binance rows returned for {symbol} {interval}")
    df = pd.DataFrame(rows, columns=KLINE_COLUMNS)
    numeric = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "quote_volume",
        "taker_buy_base",
        "taker_buy_quote",
    ]
    df[numeric] = df[numeric].astype(float)
    df["trade_count"] = df["trade_count"].astype(int)
    df["open_time"] = pd.to_datetime(df["open_time_ms"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time_ms"], unit="ms", utc=True)
    df = (
        df.loc[df["close_time_ms"] < end_time_ms]
        .drop_duplicates("open_time", keep="last")
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    return df[
        [
            "open_time",
            "close_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trade_count",
        ]
    ]


def download_bitstamp_daily(start_unix: int, end_unix: int) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    cursor = int(start_unix)
    one_day = 86_400
    while cursor <= end_unix:
        # Bitstamp returns the most recent `limit` rows when an excessively wide
        # start/end range is supplied.  Start-only pagination is required to
        # walk forward from 2013 without silently truncating to the latest 1000.
        query = urllib.parse.urlencode({"step": one_day, "limit": 1000, "start": cursor})
        payload = _get_json(f"{BITSTAMP_OHLC}?{query}")
        batch = payload.get("data", {}).get("ohlc", [])
        if not batch:
            break
        rows.extend(batch)
        last = int(batch[-1]["timestamp"])
        next_cursor = last + one_day
        if next_cursor <= cursor:
            raise RuntimeError("Bitstamp cursor did not advance")
        cursor = next_cursor
        if last >= end_unix - one_day:
            break
        time.sleep(0.05)

    if not rows:
        raise RuntimeError("No Bitstamp BTCUSD daily rows returned")
    df = pd.DataFrame(rows)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["open_time"] = pd.to_datetime(df["timestamp"].astype(int), unit="s", utc=True)
    df["close_time"] = df["open_time"] + pd.Timedelta(days=1) - pd.Timedelta(milliseconds=1)
    df = (
        df.loc[df["close"] > 0]
        .drop_duplicates("open_time", keep="last")
        .sort_values("open_time")
        .reset_index(drop=True)
    )
    return df[["open_time", "close_time", "open", "high", "low", "close", "volume"]]


def write_csv_gz(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", newline="") as handle:
        df.to_csv(handle, index=False, date_format="%Y-%m-%dT%H:%M:%S%z")


def read_csv_gz(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, parse_dates=["open_time", "close_time"])


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _coverage_row(
    path: Path,
    df: pd.DataFrame,
    *,
    asset: str,
    source: str,
    interval: str,
    url: str,
    retrieved_at: str,
    source_switch_date: str = "",
) -> dict[str, Any]:
    return {
        "asset": asset,
        "source": source,
        "interval": interval,
        "start_date": df["open_time"].min().isoformat(),
        "end_date": df["close_time"].max().isoformat(),
        "source_switch_date": source_switch_date,
        "rows": len(df),
        "retrieved_at": retrieved_at,
        "url": url,
        "file": f"data/raw/{path.name}",
        "sha256": sha256_file(path),
    }


def acquire_raw_data(project_dir: Path, rules: dict[str, Any], *, refresh: bool = False) -> pd.DataFrame:
    raw_dir = project_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    retrieved_at = utc_now_iso()
    server_ms = binance_server_time_ms()
    start_ms = int(pd.Timestamp(rules["requested_primary_start"]).timestamp() * 1000)
    manifest_rows: list[dict[str, Any]] = []

    for asset, symbol in rules["symbols"].items():
        for interval in ("4h", "1d"):
            path = raw_dir / f"binance_{symbol}_{interval}.csv.gz"
            if refresh or not path.exists():
                df = download_binance_klines(symbol, interval, start_ms, server_ms)
                write_csv_gz(df, path)
            else:
                df = read_csv_gz(path)
            manifest_rows.append(
                _coverage_row(
                    path,
                    df,
                    asset=asset,
                    source="Binance Spot",
                    interval=interval,
                    url=BINANCE_KLINES,
                    retrieved_at=retrieved_at,
                    source_switch_date=(
                        df["open_time"].min().isoformat() if asset == "BTC" and interval == "1d" else ""
                    ),
                )
            )

    bitstamp_path = raw_dir / "bitstamp_BTCUSD_1d.csv.gz"
    start_unix = int(pd.Timestamp(rules["extended_btc_start"]).timestamp())
    end_unix = server_ms // 1000
    if refresh or not bitstamp_path.exists():
        bitstamp = download_bitstamp_daily(start_unix, end_unix)
        server_time = pd.to_datetime(server_ms, unit="ms", utc=True)
        bitstamp = bitstamp.loc[bitstamp["close_time"] < server_time]
        write_csv_gz(bitstamp, bitstamp_path)
    else:
        bitstamp = read_csv_gz(bitstamp_path)
    btc_binance_daily = read_csv_gz(raw_dir / "binance_BTCUSDT_1d.csv.gz")
    manifest_rows.append(
        _coverage_row(
            bitstamp_path,
            bitstamp,
            asset="BTC",
            source="Bitstamp BTCUSD",
            interval="1d",
            url=BITSTAMP_OHLC,
            retrieved_at=retrieved_at,
            source_switch_date=btc_binance_daily["open_time"].min().isoformat(),
        )
    )

    manifest = pd.DataFrame(manifest_rows)
    manifest.to_csv(project_dir / "data" / "source_manifest.csv", index=False)
    return manifest


def load_raw_bundle(project_dir: Path, rules: dict[str, Any]) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.DataFrame]:
    raw_dir = project_dir / "data" / "raw"
    bars_4h = {
        asset: read_csv_gz(raw_dir / f"binance_{symbol}_4h.csv.gz")
        for asset, symbol in rules["symbols"].items()
    }
    daily = {
        asset: read_csv_gz(raw_dir / f"binance_{symbol}_1d.csv.gz")
        for asset, symbol in rules["symbols"].items()
    }
    bitstamp = read_csv_gz(raw_dir / "bitstamp_BTCUSD_1d.csv.gz")
    return bars_4h, daily, bitstamp


def build_common_4h_frame(bars_by_asset: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, dict[str, Any]]:
    merged: pd.DataFrame | None = None
    contracts: dict[str, Any] = {"assets": {}}
    for asset, source in bars_by_asset.items():
        df = source.copy()
        contracts["assets"][asset] = {
            "rows": len(df),
            "start": df["open_time"].min().isoformat(),
            "end": df["close_time"].max().isoformat(),
            "duplicate_open_times": int(df.duplicated("open_time").sum()),
            "nonpositive_close": int((df["close"] <= 0).sum()),
        }
        keep = df[["open_time", "open", "high", "low", "close", "volume"]].rename(
            columns={c: f"{asset}_{c}" for c in ["open", "high", "low", "close", "volume"]}
        )
        merged = keep if merged is None else merged.merge(keep, on="open_time", how="inner", validate="one_to_one")
    assert merged is not None
    merged = merged.sort_values("open_time").reset_index(drop=True)
    contracts["common"] = {
        "rows": len(merged),
        "start": merged["open_time"].min().isoformat(),
        "end": merged["open_time"].max().isoformat(),
        "is_monotonic": bool(merged["open_time"].is_monotonic_increasing),
        "duplicate_open_times": int(merged.duplicated("open_time").sum()),
    }
    return merged, contracts
