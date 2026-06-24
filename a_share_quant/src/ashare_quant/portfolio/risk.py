"""Small portfolio risk helpers for the MVP."""

from __future__ import annotations

import pandas as pd


def gross_exposure(weights: pd.Series) -> float:
    """Return absolute gross exposure."""
    return float(weights.abs().sum())

