from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from market import MarketSnapshot
from cost_view import read_costs


class PortfolioError(ValueError):
    pass


@dataclass(frozen=True)
class PortfolioSnapshot:
    timestamp: datetime
    total_value: float
    btc_value: float
    eth_value: float
    cash_value: float
    btc_percent: float
    eth_percent: float
    cash_percent: float
    btc_units: float
    eth_units: float
    valuation: str
    btc_average_cost: float | None = None
    eth_average_cost: float | None = None
    cost_status: str = "均價尚無成本資料"

    def unrealized_return(self, asset: str) -> float | None:
        """Holding-only return including buy costs, before hypothetical sell costs."""
        if asset not in {"btc", "eth"}:
            raise ValueError("Unsupported portfolio asset")
        units = getattr(self, f"{asset}_units")
        average = getattr(self, f"{asset}_average_cost")
        if units <= 1e-12 or average is None or not math.isfinite(average) or average <= 0:
            return None
        cost = units * average
        value = getattr(self, f"{asset}_value")
        return (value / cost - 1.0) * 100.0


def _number(row: dict[str, str], key: str, *, positive: bool = False) -> float:
    try:
        value = float(row[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioError(f"PORTFOLIO FIELD INVALID: {key}") from exc
    if not math.isfinite(value) or value < 0 or (positive and value <= 0):
        raise PortfolioError(f"PORTFOLIO FIELD OUT OF RANGE: {key}")
    return value


def load_portfolio(path: Path, market: MarketSnapshot | None, *, cost_path: Path | None = None,
                   model: str = "") -> PortfolioSnapshot:
    if not path.is_file():
        raise PortfolioError(f"PORTFOLIO FILE NOT FOUND: {path}")
    try:
        content = path.read_bytes()
        rows = list(csv.DictReader(io.StringIO(content.decode("utf-8-sig"))))
    except OSError as exc:
        raise PortfolioError(f"PORTFOLIO FILE READ FAILED: {exc}") from exc
    if not rows:
        raise PortfolioError("PORTFOLIO FILE HAS NO DATA ROWS")

    row = rows[-1]
    try:
        timestamp = datetime.fromisoformat(row["timestamp"].replace("Z", "+00:00"))
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioError("PORTFOLIO TIMESTAMP INVALID") from exc

    recorded_btc_value = _number(row, "btc_value")
    recorded_eth_value = _number(row, "eth_value")
    recorded_btc_price = _number(row, "BTC_close", positive=True)
    recorded_eth_price = _number(row, "ETH_close", positive=True)
    btc_units = recorded_btc_value / recorded_btc_price
    eth_units = recorded_eth_value / recorded_eth_price
    cash_value = sum(
        _number(row, field)
        for field in ("normal_cash", "pending_dca_cash", "tactical_bear_cash", "temporary_hedge_cash")
    )

    if market is None:
        btc_value = recorded_btc_value
        eth_value = recorded_eth_value
        valuation = "模型最近一次收盤價"
    else:
        btc_value = btc_units * market.btc.price
        eth_value = eth_units * market.eth.price
        valuation = "Binance 即時市價"
    total_value = btc_value + eth_value + cash_value
    if total_value <= 0:
        raise PortfolioError("PORTFOLIO TOTAL VALUE IS NOT POSITIVE")

    btc_cost, eth_cost, cost_status = None, None, "均價尚無成本資料"
    if cost_path is not None:
        btc_cost, eth_cost, cost_status = read_costs(
            cost_path, model=model, portfolio_hash=hashlib.sha256(content).hexdigest(),
            timestamp=row["timestamp"], units=(btc_units, eth_units),
        )

    return PortfolioSnapshot(
        timestamp=timestamp,
        total_value=total_value,
        btc_value=btc_value,
        eth_value=eth_value,
        cash_value=cash_value,
        btc_percent=btc_value / total_value * 100,
        eth_percent=eth_value / total_value * 100,
        cash_percent=cash_value / total_value * 100,
        btc_units=btc_units,
        eth_units=eth_units,
        valuation=valuation,
        btc_average_cost=btc_cost, eth_average_cost=eth_cost, cost_status=cost_status,
    )


def load_combined_portfolio(view: dict | None, market: MarketSnapshot | None) -> PortfolioSnapshot | None:
    """Read-only valuation of the persisted hybrid account, never a new Genesis.

    Do not relabel legacy independent AI experiments as V3.10 + AI. Cost basis
    is measured from this account's Genesis, not inherited historical costs.
    """
    if not view or (view.get("genesis") or {}).get("strategy_mode") != "v310_hybrid":
        return None
    state = view.get("state")
    if not isinstance(state, dict):
        raise PortfolioError("COMBINED PORTFOLIO STATE MISSING")
    btc_units = _number(state, "btc_units")
    eth_units = _number(state, "eth_units")
    cash = _number(state, "cash")
    try:
        timestamp = datetime.fromisoformat(state["timestamp"].replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Timezone required")
    except (KeyError, TypeError, ValueError) as exc:
        raise PortfolioError("COMBINED PORTFOLIO TIMESTAMP INVALID") from exc
    if market:
        btc_price, eth_price = market.btc.price, market.eth.price
        quote_time = min(market.btc.data_timestamp, market.eth.data_timestamp).astimezone()
        valuation = f"Binance 市價 · {quote_time:%m/%d %H:%M:%S}"
    else:
        btc_price = _number(state, "btc_price", positive=True)
        eth_price = _number(state, "eth_price", positive=True)
        valuation = "帳本最後一次估值（尚未取得最新行情）"
    if any(not math.isfinite(p) or p <= 0 for p in (btc_price, eth_price)):
        raise PortfolioError("COMBINED MARKET PRICE INVALID")
    btc_value, eth_value = btc_units * btc_price, eth_units * eth_price
    total = btc_value + eth_value + cash
    if not math.isfinite(total) or total <= 0:
        raise PortfolioError("COMBINED PORTFOLIO TOTAL INVALID")
    averages = []
    for asset, units in (("btc", btc_units), ("eth", eth_units)):
        cost = _number(state, f"{asset}_cost_basis")
        averages.append(cost / units if units > 1e-12 else None)
    return PortfolioSnapshot(
        timestamp, total, btc_value, eth_value, cash,
        btc_value / total * 100, eth_value / total * 100, cash / total * 100,
        btc_units, eth_units, valuation, *averages,
        "均價以綜合帳本啟用時市價為起點；非原 V3.10 歷史買入均價。",
    )
