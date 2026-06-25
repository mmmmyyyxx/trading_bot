"""Reserved value factor hook."""

from __future__ import annotations

import pandas as pd


def value_factor(bars: pd.DataFrame) -> pd.DataFrame:
    """Return a neutral value factor until fundamentals are connected."""
    data = bars[["date", "symbol"]].copy()
    data["value"] = 0.0
    return data
