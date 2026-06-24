"""Realized volatility factor."""

from __future__ import annotations

import pandas as pd


def volatility_factor(bars: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Trailing standard deviation of daily close-to-close returns."""
    data = bars.sort_values(["symbol", "date"]).copy()
    returns = data.groupby("symbol")["close"].pct_change()
    data["volatility"] = returns.groupby(data["symbol"]).transform(
        lambda s: s.rolling(window, min_periods=window).std()
    )
    return data[["date", "symbol", "volatility"]]

