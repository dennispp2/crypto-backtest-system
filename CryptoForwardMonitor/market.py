from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/24hr"


class MarketError(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    price: float
    change_24h_percent: float
    data_timestamp: datetime


@dataclass(frozen=True)
class MarketSnapshot:
    btc: MarketQuote
    eth: MarketQuote
    fetched_at: datetime


def _http_json(url: str, timeout: float) -> dict[str, object]:
    request = urllib.request.Request(
        url, headers={"User-Agent": "CryptoForwardMonitor/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class BinanceMarketClient:
    def __init__(
        self, timeout: float = 5.0,
        fetch_json: Callable[[str, float], dict[str, object]] = _http_json,
    ) -> None:
        self.timeout = timeout
        self.fetch_json = fetch_json

    def _quote(self, symbol: str) -> MarketQuote:
        url = f"{BINANCE_TICKER_URL}?{urllib.parse.urlencode({'symbol': symbol})}"
        try:
            payload = self.fetch_json(url, self.timeout)
            timestamp_ms = int(payload.get("closeTime", 0))
            timestamp = (
                datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
                if timestamp_ms else datetime.now(timezone.utc)
            )
            return MarketQuote(
                symbol=symbol,
                price=float(payload["lastPrice"]),
                change_24h_percent=float(payload["priceChangePercent"]),
                data_timestamp=timestamp,
            )
        except Exception as exc:
            raise MarketError(f"MARKET API FAILED ({symbol}): {exc}") from exc

    def fetch(self) -> MarketSnapshot:
        btc = self._quote("BTCUSDT")
        eth = self._quote("ETHUSDT")
        return MarketSnapshot(btc=btc, eth=eth, fetched_at=datetime.now(timezone.utc))

