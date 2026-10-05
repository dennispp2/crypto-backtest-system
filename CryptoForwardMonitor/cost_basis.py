"""Display-only moving-average cost accounting, independent of trade decisions."""
from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping


@dataclass
class CostPosition:
    units: float = 0.0
    cost: float = 0.0

    @property
    def average(self) -> float | None:
        return self.cost / self.units if self.units > 1e-12 else None


def account_trades(rows: Iterable[Mapping], positions=None) -> dict[str, CostPosition]:
    book = positions if positions is not None else {asset: CostPosition() for asset in ("BTC", "ETH")}
    for row in rows:
        asset, side = row["asset"], row["side"]
        quantity, cash = float(row["quantity"]), float(row["cash_change_usd"])
        if asset not in book or side not in {"BUY", "SELL"}:
            raise ValueError("Unknown asset or trade side")
        if not math.isfinite(quantity) or quantity <= 0 or not math.isfinite(cash):
            raise ValueError("Invalid quantity or cash change")
        position = book[asset]
        if side == "BUY":
            if cash >= 0:
                raise ValueError("Buy requires a cash outflow")
            position.units += quantity
            position.cost -= cash  # Actual cash spent includes fee and slippage.
        else:
            if cash < 0 or quantity > position.units + 1e-9:
                raise ValueError("Sell exceeds holdings or has invalid proceeds")
            remaining = max(0.0, position.units - quantity)
            position.cost *= remaining / position.units
            position.units = remaining
            if remaining < 1e-12:
                position.units = position.cost = 0.0
    return book
