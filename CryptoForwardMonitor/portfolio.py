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
