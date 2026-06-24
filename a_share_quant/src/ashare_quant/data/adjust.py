"""Price adjustment helpers."""

from __future__ import annotations

import pandas as pd


def apply_adjustment(bars: pd.DataFrame, adjust: str = "qfq") -> pd.DataFrame:
    """Apply a simple adjustment factor when raw factors are supplied."""
    if adjust in {"", "none", "raw"}:
        return bars.copy()
    adjusted = bars.copy()
    if "adj_factor" not in adjusted.columns:
        adjusted["adj_factor"] = 1.0
    for col in ["open", "high", "low", "close"]:
        adjusted[col] = adjusted[col] * adjusted["adj_factor"]
    return adjusted

