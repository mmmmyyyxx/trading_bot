"""Position state used by the backtest engine."""

from __future__ import annotations

import pandas as pd


class PositionBook:
    """Track long-only positions and same-day buy locks for T+1."""

    def __init__(self) -> None:
        self.shares: dict[str, int] = {}
        self.last_buy_date: dict[str, pd.Timestamp] = {}

    def get(self, symbol: str) -> int:
        """Return current shares for one symbol."""
        return int(self.shares.get(symbol, 0))

    def symbols(self) -> list[str]:
        """Return symbols with positive positions."""
        return [symbol for symbol, qty in self.shares.items() if qty > 0]

    def available_to_sell(self, symbol: str, date: pd.Timestamp, t_plus_one: bool) -> int:
        """Return shares that may be sold on `date`."""
        shares = self.get(symbol)
        if t_plus_one and self.last_buy_date.get(symbol) == pd.Timestamp(date):
            return 0
        return shares

    def buy(self, symbol: str, shares: int, date: pd.Timestamp) -> None:
        """Increase long position and lock today's bought shares."""
        if shares <= 0:
            return
        self.shares[symbol] = self.get(symbol) + int(shares)
        self.last_buy_date[symbol] = pd.Timestamp(date)

    def sell(self, symbol: str, shares: int) -> None:
        """Decrease long position."""
        if shares <= 0:
            return
        remaining = self.get(symbol) - int(shares)
        if remaining <= 0:
            self.shares.pop(symbol, None)
            self.last_buy_date.pop(symbol, None)
        else:
            self.shares[symbol] = remaining

