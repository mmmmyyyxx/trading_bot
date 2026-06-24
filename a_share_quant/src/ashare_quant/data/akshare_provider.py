"""Best-effort AKShare provider adapter."""

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
            try:
                frame = self._fetch_daily(symbol, start, end, adjust_arg)
            except Exception as exc:  # pragma: no cover - depends on network/API
                LOGGER.warning("AKShare daily failed for %s: %s; trying Eastmoney fallback.", symbol, exc)
                try:
                    frame = self._fetch_eastmoney(symbol, start, end, adjust_arg)
                except Exception as fallback_exc:  # pragma: no cover - depends on network/API
                    LOGGER.warning("AKShare Eastmoney fallback failed for %s: %s", symbol, fallback_exc)
                    continue
            if not frame.empty:
                frames.append(frame)

        if not frames:
            raise ProviderUnavailable("AKShare returned no usable bars.")

        return validate_bars(pd.concat(frames, ignore_index=True))

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
                "日期": "date",
                "开盘": "open",
                "最高": "high",
                "最低": "low",
                "收盘": "close",
                "成交量": "volume",
                "成交额": "amount",
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
        frame["adj_factor"] = 1.0
        frame["is_paused"] = False
        frame["is_st"] = False
        frame["date"] = pd.to_datetime(frame["date"])
        frame = frame.sort_values("date")
        prev_close = frame["close"].shift(1).fillna(frame["close"])
        frame["limit_up"] = prev_close * 1.10
        frame["limit_down"] = prev_close * 0.90
        return frame


def _to_ak_daily_symbol(symbol: str) -> str:
    code, _, market = symbol.partition(".")
    prefix = "sz" if market.upper() == "SZ" else "sh"
    return f"{prefix}{code}"
