"""Reserved quality factor hook."""

from __future__ import annotations

import pandas as pd


def quality_factor(bars: pd.DataFrame) -> pd.DataFrame:
    """Return a neutral quality factor until fundamentals are connected."""
    data = bars[["date", "symbol"]].copy()
    data["quality"] = 0.0
    return data

