"""Trading-day helpers built from available daily bars."""

from __future__ import annotations

import pandas as pd


def trading_days_from_bars(bars: pd.DataFrame) -> pd.DatetimeIndex:
    """Return sorted unique trading dates from a bar DataFrame."""
    return pd.DatetimeIndex(pd.to_datetime(bars["date"]).drop_duplicates().sort_values())


def next_trading_day(days: pd.DatetimeIndex, day: pd.Timestamp) -> pd.Timestamp | None:
    """Return the next trading day after `day`, or None at the end."""
    pos = days.searchsorted(pd.Timestamp(day), side="right")
    if pos >= len(days):
        return None
    return days[pos]


def rebalance_signal_dates(days: pd.DatetimeIndex, frequency: str = "M") -> list[pd.Timestamp]:
    """Return dates whose close can be used to trade on the next session."""
    if frequency.upper() in {"M", "MONTH", "MONTHLY"}:
        grouped = pd.Series(days, index=days).groupby(days.to_period("M")).max()
        return [pd.Timestamp(day) for day in grouped.tolist()]
    if frequency.upper() in {"W", "WEEK", "WEEKLY"}:
        grouped = pd.Series(days, index=days).groupby(days.to_period("W")).max()
        return [pd.Timestamp(day) for day in grouped.tolist()]
    return [pd.Timestamp(day) for day in days]

