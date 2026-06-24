"""Rebalance-date helpers."""

from __future__ import annotations

import pandas as pd

from ashare_quant.data.calendar import rebalance_signal_dates, trading_days_from_bars


def get_signal_dates(bars: pd.DataFrame, frequency: str) -> list[pd.Timestamp]:
    """Return signal dates based on available trading days."""
    return rebalance_signal_dates(trading_days_from_bars(bars), frequency)

