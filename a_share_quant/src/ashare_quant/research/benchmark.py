"""Benchmark loading with AKShare support."""

from __future__ import annotations

import logging

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.data.base import ProviderUnavailable

LOGGER = logging.getLogger(__name__)

BENCHMARKS = {
    "hs300": ("沪深300", "sh000300"),
    "csi500": ("中证500", "sh000905"),
    "csi1000": ("中证1000", "sh000852"),
}


def _normalize_index_frame(raw: pd.DataFrame, key: str, name: str) -> pd.DataFrame:
    renamed = raw.rename(columns={"日期": "date", "收盘": "close"})
    if "date" not in renamed.columns or "close" not in renamed.columns:
        raise ValueError("AKShare index data does not contain date/close columns.")
    frame = renamed[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["benchmark"] = key
    frame["benchmark_name"] = name
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    frame["return"] = frame["close"].pct_change().fillna(0.0)
    frame["equity"] = (1.0 + frame["return"]).cumprod()
    frame["source"] = "akshare"
    return frame[["date", "benchmark", "benchmark_name", "source", "close", "return", "equity"]]


def _fetch_akshare_index(key: str, name: str, ak_symbol: str, start_date: str, end_date: str) -> pd.DataFrame:
    import akshare as ak  # type: ignore

    try:
        raw = ak.stock_zh_index_daily_em(symbol=ak_symbol)
    except Exception:
        raw = ak.stock_zh_index_daily(symbol=ak_symbol)
    frame = _normalize_index_frame(raw, key, name)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    return frame[(frame["date"] >= start) & (frame["date"] <= end)].reset_index(drop=True)


def load_benchmarks(config: AppConfig, bars: pd.DataFrame) -> pd.DataFrame:
    """Load HS300/CSI500/CSI1000 benchmarks from AKShare only."""
    frames: list[pd.DataFrame] = []
    for key, (name, ak_symbol) in BENCHMARKS.items():
        try:
            frame = _fetch_akshare_index(key, name, ak_symbol, config.data.start_date, config.data.end_date)
            if not frame.empty:
                frames.append(frame)
                continue
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.warning("Benchmark %s unavailable from AKShare: %s", name, exc)
    if len(frames) == len(BENCHMARKS):
        return pd.concat(frames, ignore_index=True)
    raise ProviderUnavailable("AKShare benchmark data is incomplete; synthetic benchmark fallback is disabled.")


def benchmark_summary(benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Summarize cumulative benchmark returns."""
    rows = []
    for key, frame in benchmarks.groupby("benchmark"):
        frame = frame.sort_values("date")
        rows.append(
            {
                "benchmark": key,
                "benchmark_name": frame["benchmark_name"].iloc[0],
                "source": frame["source"].iloc[0],
                "start_date": frame["date"].iloc[0],
                "end_date": frame["date"].iloc[-1],
                "benchmark_return": frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1.0,
            }
        )
    return pd.DataFrame(rows)
