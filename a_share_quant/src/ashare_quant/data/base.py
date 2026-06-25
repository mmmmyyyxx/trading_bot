"""Common data provider interface and OHLCV schema validation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Iterable

import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype

REQUIRED_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "adj_factor",
    "is_paused",
    "is_st",
    "limit_up",
    "limit_down",
]


class ProviderUnavailable(RuntimeError):
    """Raised when a configured market data provider cannot be used."""


class DataProvider(ABC):
    """Abstract interface for daily A-share data providers."""

    @abstractmethod
    def fetch_bars(
        self,
        symbols: Iterable[str],
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Return daily bars in the standard schema."""


def validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize daily bars to the project schema."""
    missing = [col for col in REQUIRED_COLUMNS if col not in bars.columns]
    if missing:
        raise ValueError(f"Missing required bar columns: {missing}")

    normalized = bars.copy()
    normalized["date"] = pd.to_datetime(normalized["date"])
    normalized["symbol"] = normalized["symbol"].astype(str)

    for col in ["open", "high", "low", "close", "volume", "amount", "adj_factor", "limit_up", "limit_down"]:
        normalized[col] = pd.to_numeric(normalized[col], errors="coerce")

    for col in ["is_paused", "is_st"]:
        normalized[col] = normalized[col].fillna(False).astype(bool)

    normalized = normalized.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    return normalized.sort_values(["date", "symbol"]).reset_index(drop=True)


def bars_are_normalized(bars: pd.DataFrame) -> bool:
    """Return whether bars already satisfy the backtest-required schema and dtypes."""
    if bars.empty:
        return all(col in bars.columns for col in REQUIRED_COLUMNS)
    if any(col not in bars.columns for col in REQUIRED_COLUMNS):
        return False
    if not is_datetime64_any_dtype(bars["date"]):
        return False
    if bars[["date", "symbol", "open", "high", "low", "close"]].isna().any().any():
        return False
    for col in ["open", "high", "low", "close", "volume", "amount", "adj_factor", "limit_up", "limit_down"]:
        if not is_numeric_dtype(bars[col]):
            return False
    for col in ["is_paused", "is_st"]:
        if not is_bool_dtype(bars[col]):
            return False
    return True

