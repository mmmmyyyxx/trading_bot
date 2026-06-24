"""Validation helpers."""

from __future__ import annotations

import pandas as pd


def require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    """Raise ValueError if a DataFrame is missing required columns."""
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

