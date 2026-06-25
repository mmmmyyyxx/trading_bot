"""Momentum factor."""

from __future__ import annotations

import pandas as pd


def momentum_factor(bars: pd.DataFrame, window: int = 120, skip: int = 20) -> pd.DataFrame:
    """Past return over `window` sessions, skipping the most recent `skip`."""
    data = bars.sort_values(["symbol", "date"]).copy()
    grouped = data.groupby("symbol")["close"]
    data["momentum"] = grouped.shift(skip) / grouped.shift(skip + window) - 1.0
    return data[["date", "symbol", "momentum"]]


def short_term_reversal_factor(bars: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Negative recent return over `window` sessions for short-term reversal tests."""
    data = bars.sort_values(["symbol", "date"]).copy()
    grouped = data.groupby("symbol")["close"]
    data["short_term_reversal"] = -(data["close"] / grouped.shift(window) - 1.0)
    return data[["date", "symbol", "short_term_reversal"]]

