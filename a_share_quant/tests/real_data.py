from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_quant.config import load_config
from ashare_quant.data.storage import SQLiteStorage


def load_real_cached_bars() -> pd.DataFrame:
    """Load the real AKShare cache used by local tests."""
    cache_path = Path(load_config("configs/default.yaml").data.cache_path)
    if not cache_path.exists():
        raise FileNotFoundError(f"Real AKShare cache is required: {cache_path}")
    return SQLiteStorage(cache_path).load_bars()
