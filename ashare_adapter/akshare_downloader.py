"""AKShare downloader with A-share metadata enrichment."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

import pandas as pd

from ashare_adapter.metadata import (
    is_st_name,
    limit_rate,
    normalize_symbol,
    symbol_from_code,
    to_ak_daily_symbol,
    to_plain_code,
)

LOGGER = logging.getLogger(__name__)

BAR_COLUMNS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "factor",
    "is_paused",
    "is_st",
    "limit_up",
    "limit_down",
    "list_date",
    "industry",
]


class AKShareDownloader:
    """Fetch daily A-share bars and enrich them with tradability fields."""

    def __init__(
        self,
        metadata_cache_path: str | Path = "data/cache/akshare_metadata.parquet",
        refresh_metadata: bool = False,
        load_metadata: bool = True,
    ) -> None:
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise RuntimeError("akshare is not installed. Install with `pip install akshare`.") from exc
        self._ak = ak
        self.metadata_cache_path = Path(metadata_cache_path)
        self.metadata = self.load_metadata(refresh=refresh_metadata) if load_metadata else {}

    def fetch_bars(
        self,
        symbols: Iterable[str],
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
        workers: int = 1,
        retry: int = 2,
        sleep: float = 0.05,
    ) -> pd.DataFrame:
        """Fetch and enrich bars for all symbols."""

        symbol_list = [normalize_symbol(symbol) for symbol in symbols]
        if not symbol_list:
            raise ValueError("No symbols provided.")

        start = pd.Timestamp(start_date).strftime("%Y%m%d")
        end = pd.Timestamp(end_date).strftime("%Y%m%d")
        adjust_arg = "" if adjust in {"none", "raw", ""} else adjust

        def fetch_one(symbol: str) -> pd.DataFrame:
            for attempt in range(max(1, int(retry) + 1)):
                frame = self._fetch_one_symbol(symbol, start, end, adjust_arg)
                if not frame.empty:
                    return frame
                if sleep > 0 and attempt < retry:
                    time.sleep(float(sleep))
            LOGGER.warning("AKShare returned no usable bars for %s.", symbol)
            return pd.DataFrame()

        max_workers = min(max(1, int(workers or 1)), len(symbol_list))
        if max_workers == 1:
            frames = [fetch_one(symbol) for symbol in symbol_list]
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                frames = list(executor.map(fetch_one, symbol_list))

        frames = [frame for frame in frames if not frame.empty]
        if not frames:
            raise RuntimeError("AKShare returned no usable bars.")
        return validate_bars(pd.concat(frames, ignore_index=True))

    def enrich_bars(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Attach ST, paused, listing date, industry, and limit fields."""

        if bars.empty:
            return validate_bars(bars)

        data = bars.copy()
        data["symbol"] = data["symbol"].map(normalize_symbol)
        data["date"] = pd.to_datetime(data["date"])
        for column in ["open", "high", "low", "close", "volume", "amount"]:
            data[column] = pd.to_numeric(data[column], errors="coerce")
        if "factor" not in data.columns:
            data["factor"] = data.get("adj_factor", 1.0)
        data["factor"] = pd.to_numeric(data["factor"], errors="coerce").fillna(1.0)
        data["is_paused"] = (data["volume"].fillna(0) <= 0) | (data["amount"].fillna(0) <= 0)

        metadata = pd.DataFrame([self._metadata_row(symbol) for symbol in sorted(data["symbol"].unique())])
        data = data.merge(metadata, on="symbol", how="left")
        metadata_seen = data["metadata_seen"].fillna(False).astype(bool)
        if "is_st_x" in data.columns:
            existing_st = data["is_st_x"].fillna(False).astype(bool)
            metadata_st = data["metadata_is_st"].fillna(False).astype(bool)
            data["is_st"] = metadata_st.where(metadata_seen, existing_st)
            data = data.drop(columns=["is_st_x"])
        elif "is_st" in data.columns:
            existing_st = data["is_st"].fillna(False).astype(bool)
            metadata_st = data["metadata_is_st"].fillna(False).astype(bool)
            data["is_st"] = metadata_st.where(metadata_seen, existing_st)
        else:
            data["is_st"] = data["metadata_is_st"].fillna(False).astype(bool)
        data = data.drop(columns=["is_st_y"], errors="ignore")

        if "list_date" in data.columns:
            existing_list_date = pd.to_datetime(data["list_date"], errors="coerce")
        else:
            existing_list_date = pd.Series(pd.NaT, index=data.index)
        metadata_list_date = pd.to_datetime(data["metadata_list_date"], errors="coerce")
        data["list_date"] = metadata_list_date.combine_first(existing_list_date)
        data["list_date_fallback"] = metadata_list_date.isna()

        metadata_industry = data["metadata_industry"].fillna("").astype(str)
        existing_industry = data.get("industry", pd.Series("", index=data.index)).fillna("").astype(str)
        data["industry"] = metadata_industry.where(metadata_industry.str.len() > 0, existing_industry)

        data = data.sort_values(["symbol", "date"])
        prev_close = data.groupby("symbol")["close"].shift(1).fillna(data["close"])
        rates = [limit_rate(symbol, is_st) for symbol, is_st in zip(data["symbol"], data["is_st"])]
        data["limit_up"] = prev_close * (1.0 + pd.Series(rates, index=data.index))
        data["limit_down"] = prev_close * (1.0 - pd.Series(rates, index=data.index))

        return validate_bars(
            data.drop(
                columns=["metadata_seen", "metadata_is_st", "metadata_list_date", "metadata_industry"],
                errors="ignore",
            )
        )

    def load_metadata(self, refresh: bool = False) -> dict[str, dict[str, object]]:
        """Load AKShare stock metadata, using a local cache when available."""

        if not refresh:
            cached = _read_metadata_cache(self.metadata_cache_path)
            if cached:
                return cached

        metadata: dict[str, dict[str, object]] = {}
        self._merge_code_name_metadata(metadata)
        self._merge_exchange_metadata(metadata)
        if metadata:
            _write_metadata_cache(self.metadata_cache_path, metadata)
        return metadata

    def _fetch_one_symbol(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        fetchers = [self._fetch_daily, self._fetch_eastmoney]
        for fetcher in fetchers:
            try:
                frame = fetcher(symbol, start, end, adjust_arg)
                if not frame.empty:
                    return frame
            except Exception as exc:  # pragma: no cover - network/API dependent
                LOGGER.warning("%s failed for %s: %s", fetcher.__name__, symbol, exc)
        return pd.DataFrame()

    def _fetch_daily(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        raw = self._ak.stock_zh_a_daily(
            symbol=to_ak_daily_symbol(symbol),
            start_date=start,
            end_date=end,
            adjust=adjust_arg,
        )
        return self._standardize_frame(raw, symbol)

    def _fetch_eastmoney(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        raw = self._ak.stock_zh_a_hist(
            symbol=to_plain_code(symbol),
            period="daily",
            start_date=start,
            end_date=end,
            adjust=adjust_arg,
        )
        renamed = raw.rename(
            columns={
                "\u65e5\u671f": "date",
                "\u5f00\u76d8": "open",
                "\u6700\u9ad8": "high",
                "\u6700\u4f4e": "low",
                "\u6536\u76d8": "close",
                "\u6210\u4ea4\u91cf": "volume",
                "\u6210\u4ea4\u989d": "amount",
            }
        )
        return self._standardize_frame(renamed, symbol)

    def _standardize_frame(self, raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        required = ["date", "open", "high", "low", "close", "volume", "amount"]
        missing = [column for column in required if column not in raw.columns]
        if missing:
            raise ValueError(f"AKShare data for {symbol} missing columns: {missing}")
        frame = raw[required].copy()
        frame["symbol"] = normalize_symbol(symbol)
        return self.enrich_bars(frame)

    def _merge_code_name_metadata(self, metadata: dict[str, dict[str, object]]) -> None:
        try:
            raw = self._ak.stock_info_a_code_name()
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.warning("AKShare code-name metadata unavailable: %s", exc)
            return
        if raw.empty:
            return
        code_col = "code" if "code" in raw.columns else raw.columns[0]
        name_col = "name" if "name" in raw.columns else (raw.columns[1] if len(raw.columns) > 1 else None)
        for _, row in raw.iterrows():
            try:
                symbol = symbol_from_code(row[code_col])
            except ValueError:
                continue
            name = "" if name_col is None else str(row[name_col])
            entry = metadata.setdefault(symbol, {})
            entry["name"] = name
            entry["is_st"] = is_st_name(name)

    def _merge_exchange_metadata(self, metadata: dict[str, dict[str, object]]) -> None:
        calls = [
            (lambda: self._ak.stock_info_sh_name_code(), 0, 1, 5, None),
            (lambda: self._ak.stock_info_sh_name_code(symbol="\u79d1\u521b\u677f"), 0, 1, 5, None),
            (lambda: self._ak.stock_info_sz_name_code(), 1, 2, 3, 6),
        ]
        for loader, code_idx, name_idx, list_idx, industry_idx in calls:
            try:
                frame = loader()
            except Exception as exc:  # pragma: no cover - network/API dependent
                LOGGER.warning("AKShare exchange metadata unavailable: %s", exc)
                continue
            self._merge_exchange_frame(metadata, frame, code_idx, name_idx, list_idx, industry_idx)

    def _merge_exchange_frame(
        self,
        metadata: dict[str, dict[str, object]],
        frame: pd.DataFrame,
        code_idx: int,
        name_idx: int,
        list_idx: int,
        industry_idx: int | None,
    ) -> None:
        if frame.empty:
            return
        code_col = _find_column(frame, ["\u4ee3\u7801"], code_idx)
        name_col = _find_column(frame, ["\u7b80\u79f0"], name_idx) or _find_column(frame, ["\u540d\u79f0"], name_idx)
        list_col = _find_column(frame, ["\u4e0a\u5e02", "\u65e5"], list_idx)
        industry_col = _find_column(frame, ["\u884c\u4e1a"], industry_idx) if industry_idx is not None else None

        for _, row in frame.iterrows():
            try:
                symbol = symbol_from_code(row[code_col])
            except (KeyError, ValueError):
                continue
            entry = metadata.setdefault(symbol, {})
            if name_col is not None:
                name = str(row[name_col])
                entry["name"] = name
                entry["is_st"] = is_st_name(name)
            if list_col is not None:
                list_date = pd.to_datetime(row[list_col], errors="coerce")
                if pd.notna(list_date):
                    entry["list_date"] = pd.Timestamp(list_date).normalize()
            if industry_col is not None:
                industry = str(row[industry_col]).strip()
                if industry and industry.lower() != "nan":
                    entry["industry"] = industry

    def _metadata_row(self, symbol: str) -> dict[str, object]:
        entry = self.metadata.get(symbol, {})
        return {
            "symbol": symbol,
            "metadata_seen": symbol in self.metadata,
            "metadata_is_st": bool(entry.get("is_st", False)),
            "metadata_list_date": entry.get("list_date"),
            "metadata_industry": entry.get("industry", ""),
        }


def validate_bars(bars: pd.DataFrame) -> pd.DataFrame:
    """Validate and normalize the project bar schema."""

    data = bars.copy()
    if data.empty and not set(["date", "symbol"]).issubset(data.columns):
        return pd.DataFrame(columns=BAR_COLUMNS)
    for column in BAR_COLUMNS:
        if column not in data.columns:
            if column == "factor":
                data[column] = data.get("adj_factor", 1.0)
            elif column in {"is_paused", "is_st"}:
                data[column] = False
            elif column in {"limit_up", "limit_down"}:
                data[column] = pd.NA
            else:
                data[column] = "" if column == "industry" else pd.NaT

    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    for column in ["open", "high", "low", "close", "volume", "amount", "factor", "limit_up", "limit_down"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    for column in ["is_paused", "is_st"]:
        data[column] = data[column].fillna(False).astype(bool)
    data["list_date"] = pd.to_datetime(data["list_date"], errors="coerce")
    data["industry"] = data["industry"].fillna("").astype(str)
    data = data.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _find_column(frame: pd.DataFrame, keywords: list[str], fallback_index: int | None) -> str | None:
    for column in frame.columns:
        text = str(column)
        if all(keyword in text for keyword in keywords):
            return str(column)
    if fallback_index is not None and fallback_index < len(frame.columns):
        return str(frame.columns[fallback_index])
    return None


def _read_metadata_cache(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        frame = pd.read_parquet(path)
    except Exception:
        try:
            frame = pd.read_csv(path)
        except Exception as exc:
            LOGGER.warning("Unable to read metadata cache %s: %s", path, exc)
            return {}
    metadata: dict[str, dict[str, object]] = {}
    for _, row in frame.iterrows():
        symbol = normalize_symbol(row["symbol"])
        list_date = pd.to_datetime(row.get("list_date"), errors="coerce")
        metadata[symbol] = {
            "name": "" if pd.isna(row.get("name", "")) else str(row.get("name", "")),
            "is_st": _as_bool(row.get("is_st", False)),
            "industry": "" if pd.isna(row.get("industry", "")) else str(row.get("industry", "")),
            "list_date": pd.Timestamp(list_date).normalize() if pd.notna(list_date) else None,
        }
    return metadata


def _write_metadata_cache(path: Path, metadata: dict[str, dict[str, object]]) -> None:
    rows = []
    for symbol, entry in metadata.items():
        rows.append(
            {
                "symbol": symbol,
                "name": entry.get("name", ""),
                "is_st": bool(entry.get("is_st", False)),
                "industry": entry.get("industry", ""),
                "list_date": entry.get("list_date"),
            }
        )
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    try:
        frame.to_parquet(path, index=False)
    except Exception:
        frame.to_csv(path.with_suffix(".csv"), index=False)


def _as_bool(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y"}
    return bool(value)
