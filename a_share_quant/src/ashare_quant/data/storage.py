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
        to_store = self._prepare_for_storage(bars)
        mode = "replace" if replace else "append"
        with sqlite3.connect(self.db_path) as conn:
            to_store.to_sql("bars", conn, if_exists=mode, index=False)
            if replace:
                self._ensure_indexes(conn)

    def upsert_bars(self, bars: pd.DataFrame) -> None:
        """Insert or replace bars keyed by date and symbol."""
        to_store = self._prepare_for_storage(bars)
        if to_store.empty:
            return

        columns = list(to_store.columns)
        column_sql = ", ".join(f'"{column}"' for column in columns)
        with sqlite3.connect(self.db_path) as conn:
            if not self._table_exists(conn, "bars"):
                to_store.to_sql("bars", conn, if_exists="replace", index=False)
                self._ensure_indexes(conn)
                return

            self._ensure_schema(conn, columns)
            to_store.to_sql("_bars_upsert", conn, if_exists="replace", index=False)
            self._ensure_indexes(conn)
            conn.execute(f"INSERT OR REPLACE INTO bars ({column_sql}) SELECT {column_sql} FROM _bars_upsert")
            conn.execute("DROP TABLE IF EXISTS _bars_upsert")

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

    def _prepare_for_storage(self, bars: pd.DataFrame) -> pd.DataFrame:
        normalized = validate_bars(bars).copy()
        normalized = normalized.drop_duplicates(subset=["date", "symbol"], keep="last")
        normalized["date"] = normalized["date"].dt.strftime("%Y-%m-%d")
        if "list_date" in normalized.columns:
            normalized["list_date"] = pd.to_datetime(normalized["list_date"], errors="coerce").dt.strftime("%Y-%m-%d")
        return normalized

    def _ensure_indexes(self, conn: sqlite3.Connection) -> None:
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_bars_date_symbol ON bars(date, symbol)")

    def _ensure_schema(self, conn: sqlite3.Connection, columns: list[str]) -> None:
        existing = {
            row[1]
            for row in conn.execute("PRAGMA table_info(bars)").fetchall()
        }
        for column in columns:
            if column in existing:
                continue
            conn.execute(f'ALTER TABLE bars ADD COLUMN "{column}" TEXT')

    def _table_exists(self, conn: sqlite3.Connection, table_name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
            (table_name,),
        ).fetchone()
        return row is not None

    def bar_stats(self) -> dict[str, object]:
        """Return lightweight cache statistics without loading the full table."""
        if not self.db_path.exists():
            return {"rows": 0, "symbols": 0, "start": None, "end": None}
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT COUNT(*), COUNT(DISTINCT symbol), MIN(date), MAX(date) FROM bars"
            ).fetchone()
        if row is None:
            return {"rows": 0, "symbols": 0, "start": None, "end": None}
        rows, symbols, start, end = row
        return {
            "rows": int(rows or 0),
            "symbols": int(symbols or 0),
            "start": start,
            "end": end,
        }

