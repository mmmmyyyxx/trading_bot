"""Trend factor."""

from __future__ import annotations

import pandas as pd


def trend_factor(bars: pd.DataFrame, window: int = 120) -> pd.DataFrame:
    """Close divided by trailing moving average minus one."""
    data = bars.sort_values(["symbol", "date"]).copy()
    moving_average = data.groupby("symbol")["close"].transform(
        lambda s: s.rolling(window, min_periods=window).mean()
    )
    data["trend"] = data["close"] / moving_average - 1.0
    return data[["date", "symbol", "trend"]]

