"""Strategy interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd


class Strategy(ABC):
    """Abstract target-weight generator."""

    @abstractmethod
    def generate_targets(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Return target weights by execution date."""

