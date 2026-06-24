"""Portfolio constraints."""

from __future__ import annotations

import pandas as pd


def apply_long_only(weights: pd.Series) -> pd.Series:
    """Remove negative weights."""
    return weights.clip(lower=0.0)


def apply_max_weight(weights: pd.Series, max_weight: float) -> pd.Series:
    """Cap each symbol weight and leave capped residual as cash."""
    if max_weight <= 0:
        raise ValueError("max_weight must be positive.")
    return weights.clip(upper=max_weight)


def normalize_if_needed(weights: pd.Series) -> pd.Series:
    """Normalize only when weights exceed full investment."""
    total = float(weights.sum())
    if total > 1.0:
        return weights / total
    return weights

