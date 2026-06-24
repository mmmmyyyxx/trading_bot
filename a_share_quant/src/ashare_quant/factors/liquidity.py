"""Liquidity factor."""

from __future__ import annotations

import pandas as pd


def liquidity_factor(bars: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Trailing average traded amount; higher is better."""
    data = bars.sort_values(["symbol", "date"]).copy()
    data["liquidity"] = data.groupby("symbol")["amount"].transform(
        lambda s: s.rolling(window, min_periods=window).mean()
    )
    return data[["date", "symbol", "liquidity"]]

