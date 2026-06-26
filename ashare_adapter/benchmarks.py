"""AKShare benchmark loaders for HS300, CSI500, and CSI1000."""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

LOGGER = logging.getLogger(__name__)

BENCHMARKS = {
    "hs300": ("HS300", "sh000300"),
    "csi500": ("CSI500", "sh000905"),
    "csi1000": ("CSI1000", "sh000852"),
}

QLIB_BENCHMARK_SYMBOLS = {
    "hs300": "SH000300",
    "csi500": "SH000905",
    "csi1000": "SH000852",
}


def load_akshare_benchmarks(start_date: str, end_date: str, keys: list[str] | None = None) -> pd.DataFrame:
    """Load index benchmarks through AKShare."""

    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("akshare is not installed. Install with `pip install akshare`.") from exc

    selected = keys or list(BENCHMARKS)
    frames: list[pd.DataFrame] = []
    for key in selected:
        name, symbol = BENCHMARKS[key]
        try:
            raw = ak.stock_zh_index_daily_em(symbol=symbol)
        except Exception:
            raw = ak.stock_zh_index_daily(symbol=symbol)
        frame = normalize_index_frame(raw, key, name)
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        frame = frame[(frame["date"] >= start) & (frame["date"] <= end)]
        if frame.empty:
            LOGGER.warning("Benchmark %s returned no rows in requested range.", key)
        else:
            frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["date", "benchmark", "benchmark_name", "source", "close", "return", "equity"])
    return pd.concat(frames, ignore_index=True).sort_values(["benchmark", "date"]).reset_index(drop=True)


def normalize_index_frame(raw: pd.DataFrame, key: str, name: str) -> pd.DataFrame:
    """Normalize AKShare Chinese index columns."""

    renamed = raw.rename(
        columns={
            "\u65e5\u671f": "date",
            "\u6536\u76d8": "close",
            "date": "date",
            "close": "close",
        }
    )
    if "date" not in renamed.columns or "close" not in renamed.columns:
        raise ValueError("AKShare index data does not contain date/close columns.")
    frame = renamed[["date", "close"]].copy()
    frame["date"] = pd.to_datetime(frame["date"])
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    frame = frame.dropna(subset=["date", "close"]).sort_values("date")
    frame["benchmark"] = key
    frame["benchmark_name"] = name
    frame["source"] = "akshare"
    frame["return"] = frame["close"].pct_change().fillna(0.0)
    frame["equity"] = (1.0 + frame["return"]).cumprod()
    return frame[["date", "benchmark", "benchmark_name", "source", "close", "return", "equity"]]


def read_benchmarks(path: str | Path) -> pd.DataFrame:
    """Read benchmark data from parquet or CSV."""

    source = Path(path)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source, parse_dates=["date"])


def write_benchmarks(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write benchmark data to parquet or CSV."""

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


def benchmark_summary(benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Summarize cumulative benchmark returns."""

    if benchmarks.empty:
        return pd.DataFrame(columns=["benchmark", "benchmark_name", "source", "start_date", "end_date", "benchmark_return"])
    data = benchmarks.copy()
    data["date"] = pd.to_datetime(data["date"])
    rows = []
    for key, frame in data.sort_values("date").groupby("benchmark"):
        rows.append(
            {
                "benchmark": key,
                "benchmark_name": frame["benchmark_name"].iloc[0],
                "source": frame["source"].iloc[0],
                "start_date": frame["date"].iloc[0],
                "end_date": frame["date"].iloc[-1],
                "benchmark_return": float(frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1.0),
            }
        )
    return pd.DataFrame(rows)


def dump_benchmarks_to_qlib(benchmarks: pd.DataFrame, qlib_dir: str | Path, market: str = "benchmarks") -> Path:
    """Write benchmark close/return/equity series into a Qlib binary dataset."""

    if benchmarks.empty:
        raise ValueError("No benchmark rows to dump.")

    root = Path(qlib_dir)
    calendars_dir = root / "calendars"
    instruments_dir = root / "instruments"
    features_dir = root / "features"
    for directory in [calendars_dir, instruments_dir, features_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    data = benchmarks.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["qlib_symbol"] = data["benchmark"].map(QLIB_BENCHMARK_SYMBOLS)
    data = data.dropna(subset=["qlib_symbol"])

    existing_calendar = _read_existing_calendar(calendars_dir / "day.txt")
    calendar = existing_calendar or sorted(pd.Timestamp(date) for date in data["date"].unique())
    calendar_index = {date: idx for idx, date in enumerate(calendar)}
    _write_calendar(calendars_dir / "day.txt", calendar)

    benchmark_rows: list[tuple[str, str, str]] = []
    for qlib_symbol, frame in data.groupby("qlib_symbol"):
        frame = frame.sort_values("date").drop_duplicates("date")
        frame = frame[frame["date"].isin(calendar)]
        if frame.empty:
            LOGGER.warning("Benchmark %s has no rows on the Qlib calendar.", qlib_symbol)
            continue
        start = pd.Timestamp(frame["date"].min())
        end = pd.Timestamp(frame["date"].max())
        row = (str(qlib_symbol), start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        benchmark_rows.append(row)

        symbol_dir = features_dir / str(qlib_symbol).lower()
        symbol_dir.mkdir(parents=True, exist_ok=True)
        aligned = frame.set_index("date").reindex([date for date in calendar if start <= date <= end])
        for field in ["close", "return", "equity"]:
            values = pd.to_numeric(aligned[field], errors="coerce").to_numpy(dtype="<f4", copy=True)
            payload = np.hstack([[float(calendar_index[start])], values]).astype("<f4")
            payload.tofile(symbol_dir / f"{field}.day.bin")

    _write_instruments(instruments_dir / f"{market}.txt", benchmark_rows)
    return root


def _read_existing_calendar(path: Path) -> list[pd.Timestamp]:
    if not path.exists():
        return []
    values = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [pd.Timestamp(value) for value in values]


def _write_calendar(path: Path, calendar: list[pd.Timestamp]) -> None:
    lines = [pd.Timestamp(date).strftime("%Y-%m-%d") for date in calendar]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def _write_instruments(path: Path, rows: list[tuple[str, str, str]]) -> None:
    lines = [f"{symbol}\t{start}\t{end}" for symbol, start, end in sorted(rows)]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
