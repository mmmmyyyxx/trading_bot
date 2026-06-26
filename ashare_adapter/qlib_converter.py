"""Convert enriched A-share bars into Qlib CSV and binary datasets."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from ashare_adapter.akshare_downloader import validate_bars
from ashare_adapter.config import UniverseConfig
from ashare_adapter.filters import add_filter_columns
from ashare_adapter.metadata import to_qlib_symbol, write_metadata_sidecar

DEFAULT_QLIB_FIELDS = [
    "open",
    "high",
    "low",
    "close",
    "vwap",
    "volume",
    "amount",
    "factor",
    "is_st",
    "is_paused",
    "limit_up",
    "limit_down",
    "listed_days",
    "avg_amount",
    "eligible",
    "selected",
]


def read_bars(path: str | Path) -> pd.DataFrame:
    """Read bars from parquet or CSV."""

    source = Path(path)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source)


def write_bars(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write bars to parquet, falling back to CSV if parquet support is missing."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix.lower() in {".parquet", ".pq"}:
        try:
            frame.to_parquet(target, index=False)
            return target
        except Exception:
            target = target.with_suffix(".csv")
    frame.to_csv(target, index=False)
    return target


def prepare_qlib_frame(bars: pd.DataFrame, universe_config: UniverseConfig | None = None) -> pd.DataFrame:
    """Normalize enriched bars to a Qlib-friendly numeric feature frame."""

    data = validate_bars(bars)
    if universe_config is not None:
        data = add_filter_columns(data, universe_config)
    else:
        data = _ensure_basic_filter_columns(data)

    data["symbol"] = data["symbol"].astype(str)
    data["qlib_symbol"] = data["symbol"].map(to_qlib_symbol)
    if "vwap" not in data.columns:
        volume = pd.to_numeric(data["volume"], errors="coerce").replace(0.0, np.nan)
        data["vwap"] = pd.to_numeric(data["amount"], errors="coerce") / volume
        data["vwap"] = data["vwap"].replace([np.inf, -np.inf], np.nan).fillna(data["close"])
    for column in ["is_st", "is_paused", "eligible", "selected"]:
        if column in data.columns:
            data[column] = data[column].fillna(False).astype(float)
    for column in DEFAULT_QLIB_FIELDS:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")
    return data.sort_values(["qlib_symbol", "date"]).reset_index(drop=True)


def dump_qlib_csv(
    bars: pd.DataFrame,
    output_dir: str | Path,
    universe_config: UniverseConfig | None = None,
    fields: Iterable[str] = DEFAULT_QLIB_FIELDS,
) -> Path:
    """Write one Qlib-compatible CSV per instrument."""

    data = prepare_qlib_frame(bars, universe_config)
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    field_list = list(fields)
    for qlib_symbol, frame in data.groupby("qlib_symbol"):
        columns = ["date", "symbol", *field_list]
        export = frame.assign(symbol=qlib_symbol)[columns].copy()
        export["date"] = pd.to_datetime(export["date"]).dt.strftime("%Y-%m-%d")
        export.to_csv(out_dir / f"{qlib_symbol.lower()}.csv", index=False)
    return out_dir


def dump_qlib_bin(
    bars: pd.DataFrame,
    qlib_dir: str | Path,
    universe_config: UniverseConfig | None = None,
    market: str = "all",
    fields: Iterable[str] = DEFAULT_QLIB_FIELDS,
) -> Path:
    """Write Qlib native daily binary data.

    The file format mirrors Qlib's official `scripts/dump_bin.py`: each feature
    file starts with a float32 calendar offset followed by aligned float32
    feature values.
    """

    data = prepare_qlib_frame(bars, universe_config)
    root = Path(qlib_dir)
    calendars_dir = root / "calendars"
    instruments_dir = root / "instruments"
    features_dir = root / "features"
    metadata_dir = root / "metadata"
    for directory in [calendars_dir, instruments_dir, features_dir, metadata_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    calendar = sorted(pd.to_datetime(data["date"]).dropna().unique())
    calendar_index = {pd.Timestamp(date): idx for idx, date in enumerate(calendar)}
    _write_calendar(calendars_dir / "day.txt", calendar)
    ensure_future_calendar(root)

    instrument_rows: list[tuple[str, str, str]] = []
    field_list = list(fields)
    for qlib_symbol, frame in data.groupby("qlib_symbol"):
        frame = frame.sort_values("date").drop_duplicates("date")
        start = pd.Timestamp(frame["date"].min())
        end = pd.Timestamp(frame["date"].max())
        instrument_rows.append((qlib_symbol, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")))

        symbol_dir = features_dir / qlib_symbol.lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)
        aligned = _align_to_calendar(frame, calendar, field_list)
        start_index = float(calendar_index[start])
        for field in field_list:
            values = aligned[field].to_numpy(dtype="<f4", copy=True)
            payload = np.hstack([[start_index], values]).astype("<f4")
            payload.tofile(symbol_dir / f"{field.lower()}.day.bin")

    _write_instruments(instruments_dir / f"{market}.txt", instrument_rows)
    if market != "all":
        _write_instruments(instruments_dir / "all.txt", instrument_rows)

    metadata_frame = data[["symbol", "qlib_symbol", "is_st", "list_date", "industry"]].drop_duplicates("symbol")
    write_metadata_sidecar(metadata_frame, metadata_dir)
    return root


def ensure_future_calendar(qlib_dir: str | Path, freq: str = "day") -> Path:
    """Ensure Qlib has a future calendar file for backtest step boundaries."""

    root = Path(qlib_dir)
    calendar_path = root / "calendars" / f"{freq}.txt"
    future_path = root / "calendars" / f"{freq}_future.txt"
    if not calendar_path.exists():
        raise FileNotFoundError(f"Calendar not found: {calendar_path}")
    calendar = _read_calendar(calendar_path)
    if not calendar:
        raise ValueError(f"Calendar is empty: {calendar_path}")
    future_calendar = _read_calendar(future_path) if future_path.exists() else []
    if len(future_calendar) <= len(calendar) or pd.Timestamp(future_calendar[-1]) <= pd.Timestamp(calendar[-1]):
        future_calendar = [*calendar, _next_business_day(pd.Timestamp(calendar[-1]))]
        _write_calendar(future_path, future_calendar)
    return future_path


def _ensure_basic_filter_columns(data: pd.DataFrame) -> pd.DataFrame:
    result = data.sort_values(["symbol", "date"]).copy()
    grouped = result.groupby("symbol", group_keys=False)
    list_date = pd.to_datetime(result.get("list_date"), errors="coerce")
    result["listed_days"] = (result["date"] - list_date).dt.days
    missing = result["listed_days"].isna()
    result.loc[missing, "listed_days"] = grouped.cumcount()[missing] + 1
    result["avg_amount"] = grouped["amount"].transform(lambda series: series.rolling(20, min_periods=1).mean())
    result["eligible"] = True
    result["selected"] = True
    return result


def _align_to_calendar(frame: pd.DataFrame, calendar: list[pd.Timestamp], fields: list[str]) -> pd.DataFrame:
    indexed = frame.copy()
    indexed["date"] = pd.to_datetime(indexed["date"])
    indexed = indexed.set_index("date")
    calendar_slice = [date for date in calendar if indexed.index.min() <= date <= indexed.index.max()]
    aligned = indexed.reindex(calendar_slice)
    for field in fields:
        if field not in aligned.columns:
            aligned[field] = np.nan
        aligned[field] = pd.to_numeric(aligned[field], errors="coerce")
    return aligned[fields]


def _write_calendar(path: Path, calendar: list[pd.Timestamp]) -> None:
    lines = [pd.Timestamp(date).strftime("%Y-%m-%d") for date in calendar]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _read_calendar(path: Path) -> list[pd.Timestamp]:
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [pd.Timestamp(value) for value in values]


def _next_business_day(date: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(date) + pd.offsets.BDay(1)


def _write_instruments(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = [f"{symbol}\t{start}\t{end}" for symbol, start, end in sorted(rows)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
