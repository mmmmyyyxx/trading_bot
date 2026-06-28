"""AKShare downloader with A-share metadata enrichment."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable
import json

import pandas as pd
import requests

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

SOURCE_PRIORITY = {"eastmoney": 1, "tencent_tx": 2, "ak_daily": 3, "legacy_unknown": 99, "unknown": 99}

AUDIT_COLUMNS = [
    "data_source",
    "amount_estimated",
    "price_adjust",
    "source_priority",
    "source_fetch_time",
    "source_error",
    "volume_unit",
    "has_valid_ohlc",
    "has_valid_volume",
    "has_valid_amount",
    "has_valid_limit",
    "has_valid_list_date",
    "has_valid_industry",
    "quality_flags",
]

TRUTHY_ENV = {"1", "true", "TRUE", "yes"}


class AKShareDownloader:
    """Fetch daily A-share bars and enrich them with tradability fields."""

    def __init__(
        self,
        metadata_cache_path: str | Path = "data/cache/akshare_metadata.parquet",
        refresh_metadata: bool = False,
        load_metadata: bool = True,
    ) -> None:
        if os.environ.get("ASHARE_USE_SYSTEM_PROXY", "").strip() not in {"1", "true", "TRUE", "yes"}:
            os.environ.setdefault("NO_PROXY", "*")
            os.environ.setdefault("no_proxy", "*")
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise RuntimeError("akshare is not installed. Install with `pip install akshare`.") from exc
        self._ak = ak
        self.metadata_cache_path = Path(metadata_cache_path)
        self.metadata = self.load_metadata(refresh=refresh_metadata) if load_metadata else {}
        self.fetch_attempts: list[dict[str, object]] = []

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
        if "industry_source" not in data.columns:
            data["industry_source"] = ""
        existing_source = data["industry_source"].fillna("").astype(str)
        metadata_source = data["metadata_industry_source"].fillna("").astype(str)
        industry_from_metadata = metadata_industry.str.len() > 0
        data["industry_source"] = metadata_source.where(industry_from_metadata & metadata_source.str.len().gt(0), existing_source)
        data.loc[data["industry"].fillna("").astype(str).str.strip().ne("") & data["industry_source"].fillna("").astype(str).str.strip().eq(""), "industry_source"] = "akshare_metadata_cache"
        if "industry_update_date" not in data.columns:
            data["industry_update_date"] = pd.NaT
        metadata_update_date = pd.to_datetime(data["metadata_industry_update_date"], errors="coerce")
        existing_update_date = pd.to_datetime(data["industry_update_date"], errors="coerce")
        data["industry_update_date"] = metadata_update_date.combine_first(existing_update_date)

        data = data.sort_values(["symbol", "date"])
        prev_close = data.groupby("symbol")["close"].shift(1).fillna(data["close"])
        rates = [limit_rate(symbol, is_st) for symbol, is_st in zip(data["symbol"], data["is_st"])]
        data["limit_up"] = prev_close * (1.0 + pd.Series(rates, index=data.index))
        data["limit_down"] = prev_close * (1.0 - pd.Series(rates, index=data.index))

        return validate_bars(
            data.drop(
                columns=[
                    "metadata_seen",
                    "metadata_is_st",
                    "metadata_list_date",
                    "metadata_industry",
                    "metadata_industry_source",
                    "metadata_industry_update_date",
                ],
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
        fetchers = self._bar_fetchers()
        for order, fetcher in enumerate(fetchers, start=1):
            source = _fetcher_source_name(fetcher.__name__)
            try:
                frame = fetcher(symbol, start, end, adjust_arg)
                if not frame.empty:
                    self.fetch_attempts.append(
                        {
                            "symbol": normalize_symbol(symbol),
                            "source": source,
                            "attempt_order": order,
                            "status": "success",
                            "rows": int(len(frame)),
                            "fallback_used": bool(order > 1),
                            "error": "",
                        }
                    )
                    return frame
            except Exception as exc:  # pragma: no cover - network/API dependent
                self.fetch_attempts.append(
                    {
                        "symbol": normalize_symbol(symbol),
                        "source": source,
                        "attempt_order": order,
                        "status": "failed",
                        "rows": 0,
                        "fallback_used": bool(order > 1),
                        "error": str(exc),
                    }
                )
                LOGGER.warning("%s failed for %s: %s", fetcher.__name__, symbol, exc)
                continue
            self.fetch_attempts.append(
                {
                    "symbol": normalize_symbol(symbol),
                    "source": source,
                    "attempt_order": order,
                    "status": "empty",
                    "rows": 0,
                    "fallback_used": bool(order > 1),
                    "error": "empty",
                }
            )
        return pd.DataFrame()

    def _bar_fetchers(self) -> list:
        source = os.environ.get("ASHARE_BAR_SOURCE", "eastmoney").strip().lower()
        if source == "tencent":
            fetchers = [self._fetch_tencent]
        elif source == "ak_daily":
            fetchers = [self._fetch_daily]
        else:
            fetchers = [self._fetch_eastmoney, self._fetch_tencent]
        if os.environ.get("ASHARE_ENABLE_AK_DAILY_FALLBACK", "").strip() in TRUTHY_ENV:
            fetchers.append(self._fetch_daily)
        return fetchers

    def _fetch_daily(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        raw = self._ak.stock_zh_a_daily(
            symbol=to_ak_daily_symbol(symbol),
            start_date=start,
            end_date=end,
            adjust=adjust_arg,
        )
        return self._standardize_frame(raw, symbol, source="ak_daily", price_adjust=adjust_arg or "raw")

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
        if "volume" in renamed.columns:
            # Eastmoney daily A-share volume is reported in lots (手). Store
            # normalized share volume so amount / volume is price-like.
            renamed["volume"] = pd.to_numeric(renamed["volume"], errors="coerce") * 100.0
        return self._standardize_frame(renamed, symbol, source="eastmoney", price_adjust=adjust_arg or "raw")

    def _fetch_tencent(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        raw = _fetch_tencent_raw(to_ak_daily_symbol(symbol), start, end, adjust_arg)
        return self._standardize_frame(raw, symbol, source="tencent_tx", price_adjust=adjust_arg or "raw")

    def _standardize_frame(
        self,
        raw: pd.DataFrame,
        symbol: str,
        source: str = "",
        amount_estimated: bool = False,
        price_adjust: str = "",
        volume_unit: str = "share",
    ) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        required = ["date", "open", "high", "low", "close", "volume", "amount"]
        missing = [column for column in required if column not in raw.columns]
        if missing:
            raise ValueError(f"AKShare data for {symbol} missing columns: {missing}")
        frame = raw[required].copy()
        frame["symbol"] = normalize_symbol(symbol)
        if source and "data_source" not in raw.columns:
            frame["data_source"] = source
        elif "data_source" in raw.columns:
            frame["data_source"] = raw["data_source"].astype(str)
        if "amount_estimated" in raw.columns:
            frame["amount_estimated"] = raw["amount_estimated"].fillna(False).astype(bool)
        else:
            frame["amount_estimated"] = bool(amount_estimated)
        frame["price_adjust"] = price_adjust
        frame["source_priority"] = SOURCE_PRIORITY.get(source, 50)
        frame["source_fetch_time"] = pd.Timestamp.now(tz="UTC").isoformat()
        frame["source_error"] = ""
        frame["volume_unit"] = volume_unit
        frame["quality_flags"] = ""
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
            "metadata_industry_source": entry.get("industry_source", "akshare_metadata_cache") if entry.get("industry", "") else "",
            "metadata_industry_update_date": entry.get("industry_update_date"),
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
    for column in AUDIT_COLUMNS:
        if column not in data.columns:
            if column == "data_source":
                data[column] = "legacy_unknown"
            elif column == "amount_estimated":
                data[column] = False
            elif column == "source_priority":
                data[column] = SOURCE_PRIORITY["legacy_unknown"]
            elif column.startswith("has_valid_"):
                data[column] = True
            else:
                data[column] = ""

    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    for column in ["open", "high", "low", "close", "volume", "amount", "factor", "limit_up", "limit_down"]:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    for column in ["is_paused", "is_st"]:
        data[column] = data[column].fillna(False).astype(bool)
    data["list_date"] = pd.to_datetime(data["list_date"], errors="coerce")
    data["industry"] = data["industry"].fillna("").astype(str)
    missing_source = data["data_source"].fillna("").astype(str).str.strip().eq("")
    data["data_source"] = data["data_source"].fillna("").astype(str).str.strip()
    data.loc[missing_source, "data_source"] = "legacy_unknown"
    data["amount_estimated"] = data["amount_estimated"].astype("boolean").fillna(False).astype(bool)
    data["source_priority"] = pd.to_numeric(data["source_priority"], errors="coerce")
    data.loc[data["source_priority"].isna(), "source_priority"] = data["data_source"].map(lambda value: SOURCE_PRIORITY.get(str(value), 50))
    data["source_priority"] = data["source_priority"].fillna(50).astype(int)

    flags = data["quality_flags"].fillna("").astype(str).map(lambda text: {part for part in text.split(";") if part})
    legacy_mask = data["data_source"].eq("legacy_unknown")
    for idx in data.index[legacy_mask]:
        flags.at[idx] = set(flags.at[idx]) | {"legacy_missing_data_source"}

    data["has_valid_ohlc"] = (
        data[["open", "high", "low", "close"]].notna().all(axis=1)
        & data[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & data["high"].ge(data[["open", "low", "close"]].max(axis=1))
        & data["low"].le(data[["open", "high", "close"]].min(axis=1))
    )
    data["has_valid_volume"] = data["volume"].notna() & data["volume"].ge(0)
    data["has_valid_amount"] = data["amount"].notna() & data["amount"].ge(0)
    data["has_valid_limit"] = (
        data[["limit_up", "limit_down", "close"]].notna().all(axis=1)
        & data["limit_up"].gt(data["limit_down"])
        & data["limit_up"].ge(data["close"])
        & data["limit_down"].le(data["close"])
    )
    data["has_valid_list_date"] = data["list_date"].isna() | data["list_date"].le(data["date"])
    data["has_valid_industry"] = data["industry"].str.strip().ne("")
    data["quality_flags"] = flags.map(lambda values: ";".join(sorted(values)))
    data = data.dropna(subset=["date", "symbol", "open", "high", "low", "close"])
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _fetch_tencent_raw(symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
    if symbol[:2].lower() not in {"sh", "sz"}:
        return pd.DataFrame()
    url = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    start_year = int(start[:4])
    end_year = int(end[:4])
    frames = []
    session = requests.Session()
    session.trust_env = False
    for year in range(start_year, end_year + 1):
        params = {
            "_var": f"kline_day{adjust_arg}{year}",
            "param": f"{symbol},day,{year}-01-01,{year + 1}-12-31,640,{adjust_arg}",
            "r": "0.8205512681390605",
        }
        response = session.get(url, params=params, timeout=20)
        response.raise_for_status()
        payload = _decode_tencent_payload(response.text, symbol)
        if not payload:
            continue
        frames.append(_standardize_tencent_rows(payload, symbol))
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates("date", keep="last")
    data["date"] = pd.to_datetime(data["date"])
    data = data[(data["date"] >= pd.Timestamp(start)) & (data["date"] <= pd.Timestamp(end))]
    return data.sort_values("date").reset_index(drop=True)


def _decode_tencent_payload(text: str, symbol: str) -> list:
    marker = text.find("={")
    if marker < 0:
        return []
    data = json.loads(text[marker + 1 :]).get("data", {}).get(symbol, {})
    for key in ["qfqday", "hfqday", "day"]:
        if key in data:
            return data[key]
    return []


def _standardize_tencent_rows(rows: list, symbol: str) -> pd.DataFrame:
    records = []
    for row in rows:
        if len(row) < 6:
            continue
        volume_lots = _to_float(row[5])
        amount_10k = _to_float(row[8]) if len(row) > 8 else None
        close = _to_float(row[2])
        volume = volume_lots * 100.0 if volume_lots is not None else None
        amount_estimated = amount_10k is None
        amount = amount_10k * 10_000.0 if amount_10k is not None else None
        if amount is None and close is not None and volume is not None:
            amount = close * volume
        records.append(
            {
                "date": row[0],
                "open": row[1],
                "close": row[2],
                "high": row[3],
                "low": row[4],
                "volume": volume,
                "amount": amount,
                "data_source": "tencent_tx",
                "amount_estimated": amount_estimated,
                "symbol": normalize_symbol(symbol),
            }
        )
    return pd.DataFrame(records)


def _to_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fetcher_source_name(name: str) -> str:
    return {
        "_fetch_eastmoney": "eastmoney",
        "_fetch_tencent": "tencent_tx",
        "_fetch_daily": "ak_daily",
    }.get(name, name.replace("_fetch_", ""))


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
            "industry_source": "" if pd.isna(row.get("industry_source", "")) else str(row.get("industry_source", "")),
            "industry_update_date": row.get("industry_update_date"),
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
                "industry_source": entry.get("industry_source", ""),
                "industry_update_date": entry.get("industry_update_date"),
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
