"""Shared factor utilities."""

from __future__ import annotations

import numpy as np
import pandas as pd


def cross_sectional_zscore(values: pd.Series) -> pd.Series:
    """Z-score one cross-section, returning zero when dispersion is absent."""
    std = values.std(ddof=0)
    if pd.isna(std) or std == 0:
        return pd.Series(np.zeros(len(values)), index=values.index, dtype=float)
    return (values - values.mean()) / std


def standardize_by_date(
    frame: pd.DataFrame,
    columns: list[str],
    lower_is_better: set[str] | None = None,
) -> pd.DataFrame:
    """Add `<factor>_score` columns using same-date cross-sectional z-scores."""
    lower_is_better = lower_is_better or set()
    scored = frame.copy()
    for column in columns:
        score = scored.groupby("date")[column].transform(cross_sectional_zscore)
        if column in lower_is_better:
            score = -score
        scored[f"{column}_score"] = score
    return scored

