"""SQLite cache for normalized daily bars."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

from ashare_quant.data.base import validate_bars


class SQLiteStorage:
    """Persist and load normalized daily bars using the stdlib sqlite driver."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def save_bars(self, bars: pd.DataFrame, replace: bool = True) -> None:
        """Save bars to the `bars` table."""
        normalized = validate_bars(bars)
        to_store = normalized.copy()
        to_store["date"] = to_store["date"].dt.strftime("%Y-%m-%d")
        if "list_date" in to_store.columns:
            to_store["list_date"] = pd.to_datetime(to_store["list_date"]).dt.strftime("%Y-%m-%d")
        mode = "replace" if replace else "append"
        with sqlite3.connect(self.db_path) as conn:
            to_store.to_sql("bars", conn, if_exists=mode, index=False)

    def load_bars(
        self,
        symbols: list[str] | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> pd.DataFrame:
        """Load cached bars, optionally filtering symbols and dates."""
        if not self.db_path.exists():
            raise FileNotFoundError(f"Cache does not exist: {self.db_path}")

        clauses: list[str] = []
        params: list[object] = []
        if symbols:
            placeholders = ",".join("?" for _ in symbols)
            clauses.append(f"symbol in ({placeholders})")
            params.extend(symbols)
        if start_date:
            clauses.append("date >= ?")
            params.append(start_date)
        if end_date:
            clauses.append("date <= ?")
            params.append(end_date)

        query = "select * from bars"
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by date, symbol"

        with sqlite3.connect(self.db_path) as conn:
            bars = pd.read_sql_query(query, conn, params=params)
        return validate_bars(bars)

