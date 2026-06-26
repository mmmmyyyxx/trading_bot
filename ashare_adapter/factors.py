"""Small local baseline factors used for smoke tests and diagnostics."""

from __future__ import annotations

import pandas as pd


def short_term_reversal(bars: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """Negative recent return over a trailing window."""

    data = bars.sort_values(["symbol", "date"]).copy()
    grouped = data.groupby("symbol")["close"]
    data["short_term_reversal"] = -(data["close"] / grouped.shift(window) - 1.0)
    return data[["date", "symbol", "short_term_reversal"]]


def low_volatility(bars: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    """Negative trailing realized volatility; larger values mean lower volatility."""

    data = bars.sort_values(["symbol", "date"]).copy()
    returns = data.groupby("symbol")["close"].pct_change()
    data["low_volatility"] = -returns.groupby(data["symbol"]).transform(
        lambda series: series.rolling(window, min_periods=window).std()
    )
    return data[["date", "symbol", "low_volatility"]]


def reversal_lowvol_scores(
    bars: pd.DataFrame,
    reversal_window: int = 20,
    volatility_window: int = 60,
    reversal_weight: float = 0.5,
    lowvol_weight: float = 0.5,
) -> pd.DataFrame:
    """Build a simple cross-sectionally normalized reversal + low-vol score."""

    rev = short_term_reversal(bars, reversal_window)
    lowvol = low_volatility(bars, volatility_window)
    scores = rev.merge(lowvol, on=["date", "symbol"], how="outer")
    scores["reversal_z"] = scores.groupby("date")["short_term_reversal"].transform(_zscore)
    scores["lowvol_z"] = scores.groupby("date")["low_volatility"].transform(_zscore)
    scores["score"] = reversal_weight * scores["reversal_z"] + lowvol_weight * scores["lowvol_z"]
    return scores.sort_values(["date", "symbol"]).reset_index(drop=True)


def _zscore(series: pd.Series) -> pd.Series:
    std = series.std(ddof=0)
    if pd.isna(std) or std == 0:
        return series * 0.0
    return (series - series.mean()) / std
