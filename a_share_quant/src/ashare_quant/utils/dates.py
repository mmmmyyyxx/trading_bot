"""Date conversion helpers."""

from __future__ import annotations

import pandas as pd


def to_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    """Convert a string or Timestamp to pandas Timestamp."""
    return pd.Timestamp(value)

