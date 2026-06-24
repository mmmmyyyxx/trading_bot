"""Reserved Tushare adapter with token loading from the environment."""

from __future__ import annotations

import os
from typing import Iterable

import pandas as pd

from ashare_quant.data.base import DataProvider, ProviderUnavailable


class TushareProvider(DataProvider):
    """Placeholder adapter that never stores tokens in source code."""

    def __init__(self, token_env: str = "TUSHARE_TOKEN") -> None:
        self.token = os.getenv(token_env)
        if not self.token:
            raise ProviderUnavailable(f"{token_env} is not set.")

    def fetch_bars(
        self,
        symbols: Iterable[str],
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Raise a clear message until the Tushare adapter is implemented."""
        raise ProviderUnavailable("TushareProvider is reserved for future implementation.")

