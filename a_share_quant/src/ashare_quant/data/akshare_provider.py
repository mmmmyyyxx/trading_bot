"""AKShare provider adapter and real metadata enrichment."""

from __future__ import annotations

import logging
from typing import Iterable

import pandas as pd

from ashare_quant.data.base import DataProvider, ProviderUnavailable, validate_bars

LOGGER = logging.getLogger(__name__)


class AKShareProvider(DataProvider):
    """Fetch daily A-share bars through AKShare when it is installed."""

    def __init__(self) -> None:
        try:
            import akshare as ak  # type: ignore
        except ImportError as exc:
            raise ProviderUnavailable("akshare is not installed in this environment.") from exc
        self._ak = ak
        self._metadata = self._load_metadata()
        self.prefer_eastmoney = False

    def fetch_bars(
        self,
        symbols: Iterable[str],
        start_date: str,
        end_date: str,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """Fetch daily bars and normalize Chinese AKShare columns."""
        frames: list[pd.DataFrame] = []
        start = pd.Timestamp(start_date).strftime("%Y%m%d")
        end = pd.Timestamp(end_date).strftime("%Y%m%d")
        adjust_arg = "" if adjust in {"none", "raw", ""} else adjust

        for symbol in symbols:
            fetchers = (
                (self._fetch_eastmoney, self._fetch_daily)
                if self.prefer_eastmoney
                else (self._fetch_daily, self._fetch_eastmoney)
            )
            frame = pd.DataFrame()
            for fetcher in fetchers:
                try:
                    frame = fetcher(symbol, start, end, adjust_arg)
                    break
                except Exception as exc:  # pragma: no cover - depends on network/API
                    LOGGER.warning("AKShare %s failed for %s: %s", fetcher.__name__, symbol, exc)
                    continue
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ProviderUnavailable("AKShare returned no usable bars.")

        return validate_bars(pd.concat(frames, ignore_index=True))

    def enrich_bars(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Recompute tradability fields and attach real AKShare metadata where available."""
        if bars.empty:
            return bars.copy()

        data = bars.sort_values(["symbol", "date"]).copy()
        data["date"] = pd.to_datetime(data["date"])

        if "adj_factor" not in data.columns:
            data["adj_factor"] = 1.0
        data["is_paused"] = (pd.to_numeric(data["volume"], errors="coerce").fillna(0) <= 0) | (
            pd.to_numeric(data["amount"], errors="coerce").fillna(0) <= 0
        )

        metadata = pd.DataFrame([self._metadata_row(symbol) for symbol in data["symbol"].astype(str).unique()])
        data = data.merge(metadata, on="symbol", how="left")

        existing_is_st = (
            data["is_st"].fillna(False).astype(bool)
            if "is_st" in data.columns
            else pd.Series(False, index=data.index)
        )
        metadata_seen = data["metadata_seen"].fillna(False).astype(bool)
        metadata_is_st = data["metadata_is_st"].fillna(False).astype(bool)
        data["is_st"] = metadata_is_st.where(metadata_seen, existing_is_st)

        existing_list_date = (
            pd.to_datetime(data["list_date"], errors="coerce")
            if "list_date" in data.columns
            else pd.Series(pd.NaT, index=data.index)
        )
        existing_list_fallback = (
            data["list_date_fallback"].fillna(True).astype(bool)
            if "list_date_fallback" in data.columns
            else pd.Series(True, index=data.index)
        )
        metadata_list_date = pd.to_datetime(data["metadata_list_date"], errors="coerce")
        data["list_date"] = metadata_list_date.combine_first(existing_list_date)
        data["list_date_fallback"] = metadata_list_date.isna() & existing_list_fallback

        existing_industry = (
            data["industry"].fillna("").astype(str)
            if "industry" in data.columns
            else pd.Series("", index=data.index)
        )
        existing_industry_fallback = (
            data["industry_fallback"].fillna(True).astype(bool)
            if "industry_fallback" in data.columns
            else pd.Series(True, index=data.index)
        )
        metadata_industry = data["metadata_industry"].fillna("").astype(str)
        has_metadata_industry = metadata_industry.str.len() > 0
        data["industry"] = metadata_industry.where(has_metadata_industry, existing_industry)
        data["industry_fallback"] = ~has_metadata_industry & existing_industry_fallback

        prev_close = data.groupby("symbol")["close"].shift(1).fillna(data["close"])
        limit_rates = [_limit_rate(symbol, is_st) for symbol, is_st in zip(data["symbol"], data["is_st"])]
        data["limit_up"] = prev_close * (1.0 + pd.Series(limit_rates, index=data.index))
        data["limit_down"] = prev_close * (1.0 - pd.Series(limit_rates, index=data.index))

        data = data.drop(
            columns=["metadata_seen", "metadata_is_st", "metadata_industry", "metadata_list_date"],
            errors="ignore",
        )
        return validate_bars(data)

    def _fetch_eastmoney(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        code = symbol.split(".")[0]
        raw = self._ak.stock_zh_a_hist(
            symbol=code,
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

    def _fetch_daily(self, symbol: str, start: str, end: str, adjust_arg: str) -> pd.DataFrame:
        ak_symbol = _to_ak_daily_symbol(symbol)
        raw = self._ak.stock_zh_a_daily(
            symbol=ak_symbol,
            start_date=start,
            end_date=end,
            adjust=adjust_arg,
        )
        return self._standardize_frame(raw, symbol)

    def _standardize_frame(self, raw: pd.DataFrame, symbol: str) -> pd.DataFrame:
        if raw.empty:
            return pd.DataFrame()
        required = ["date", "open", "high", "low", "close", "volume", "amount"]
        missing = [col for col in required if col not in raw.columns]
        if missing:
            raise ValueError(f"AKShare data for {symbol} missing columns: {missing}")
        frame = raw[required].copy()
        frame["symbol"] = symbol
        return self.enrich_bars(frame)

    def _load_metadata(self) -> dict[str, dict[str, object]]:
        metadata: dict[str, dict[str, object]] = {}
        self._merge_code_name_metadata(metadata)
        self._merge_exchange_metadata(metadata)
        return metadata

    def _merge_code_name_metadata(self, metadata: dict[str, dict[str, object]]) -> None:
        try:
            raw = self._ak.stock_info_a_code_name()
        except Exception as exc:  # pragma: no cover - depends on network/API
            LOGGER.warning("AKShare code-name metadata unavailable: %s", exc)
            return

        code_col = "code" if "code" in raw.columns else raw.columns[0]
        name_col = "name" if "name" in raw.columns else (raw.columns[1] if len(raw.columns) > 1 else None)
        for _, row in raw.iterrows():
            code = _normalize_code(row[code_col])
            if not code:
                continue
            symbol = _symbol_from_code(code)
            name = str(row[name_col]) if name_col is not None else ""
            entry = metadata.setdefault(symbol, {})
            entry["name"] = name
            entry["is_st"] = _is_st_name(name)

    def _merge_exchange_metadata(self, metadata: dict[str, dict[str, object]]) -> None:
        exchange_calls = [
            ("SH", lambda: self._ak.stock_info_sh_name_code(), 0, 1, 5, None),
            ("SH", lambda: self._ak.stock_info_sh_name_code(symbol="\u79d1\u521b\u677f"), 0, 1, 5, None),
            ("SZ", lambda: self._ak.stock_info_sz_name_code(), 1, 2, 3, 6),
        ]
        for market, loader, code_idx, name_idx, list_idx, industry_idx in exchange_calls:
            try:
                frame = loader()
            except Exception as exc:  # pragma: no cover - depends on network/API
                LOGGER.warning("AKShare %s exchange metadata unavailable: %s", market, exc)
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
            code = _normalize_code(row[code_col])
            if not code:
                continue
            symbol = _symbol_from_code(code)
            entry = metadata.setdefault(symbol, {})
            if name_col is not None:
                name = str(row[name_col])
                entry["name"] = name
                entry["is_st"] = _is_st_name(name)
            if list_col is not None:
                list_date = pd.to_datetime(row[list_col], errors="coerce")
                if pd.notna(list_date):
                    entry["list_date"] = list_date.normalize()
            if industry_col is not None:
                industry = str(row[industry_col]).strip()
                if industry and industry.lower() != "nan":
                    entry["industry"] = industry

    def _metadata_row(self, symbol: str) -> dict[str, object]:
        metadata = self._metadata.get(symbol, {})
        return {
            "symbol": symbol,
            "metadata_seen": symbol in self._metadata,
            "metadata_is_st": bool(metadata.get("is_st", False)),
            "metadata_industry": metadata.get("industry", ""),
            "metadata_list_date": metadata.get("list_date"),
        }


def enrich_bars_with_akshare_metadata(bars: pd.DataFrame) -> pd.DataFrame:
    """Attach AKShare metadata to already cached real bars."""
    return AKShareProvider().enrich_bars(bars)


def _find_column(frame: pd.DataFrame, keywords: list[str], fallback_index: int | None) -> str | None:
    for column in frame.columns:
        text = str(column)
        if all(keyword in text for keyword in keywords):
            return str(column)
    if fallback_index is not None and fallback_index < len(frame.columns):
        return str(frame.columns[fallback_index])
    return None


def _normalize_code(value: object) -> str:
    text = str(value).strip().split(".")[0]
    if text.lower() in {"nan", "none", ""}:
        return ""
    return text.zfill(6)


def _is_st_name(name: str) -> bool:
    upper = str(name).upper()
    return "ST" in upper


def _symbol_from_code(code: str) -> str:
    if code.startswith(("8", "4", "920")):
        return f"{code}.BJ"
    if code.startswith("6"):
        return f"{code}.SH"
    return f"{code}.SZ"


def _to_ak_daily_symbol(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    market = market.upper()
    if market == "BJ":
        return f"bj{code}"
    prefix = "sz" if market == "SZ" else "sh"
    return f"{prefix}{code}"


def _limit_rate(symbol: str, is_st: bool) -> float:
    code = symbol.split(".")[0]
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("8", "4", "920")):
        return 0.30
    return 0.10
