"""Backtest result container."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass
class BacktestResult:
    """All backtest outputs needed by reports and tests."""

    equity_curve: pd.DataFrame
    trades: pd.DataFrame
    positions: pd.DataFrame
    metrics: dict[str, float]

