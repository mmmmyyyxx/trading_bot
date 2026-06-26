"""A-share symbol and metadata helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class InstrumentMetadata:
    """Static metadata used by filters and sidecar exports."""

    symbol: str
    qlib_symbol: str
    name: str = ""
    is_st: bool = False
    list_date: pd.Timestamp | None = None
    industry: str = ""


def normalize_symbol(value: object) -> str:
    """Normalize a code to the local `000001.SZ` style."""

    text = str(value).strip()
    if not text or text.lower() in {"nan", "none"}:
        raise ValueError("Empty A-share symbol.")
    text = text.replace("_", ".")
    lowered = text.lower()

    if "." in text:
        code, market = text.split(".", 1)
        code = _normalize_code(code)
        market = market.upper()
        if market in {"XSHE", "SZE"}:
            market = "SZ"
        elif market in {"XSHG", "SSE"}:
            market = "SH"
        elif market in {"BSE"}:
            market = "BJ"
        return f"{code}.{market}"

    if lowered.startswith(("sh", "sz", "bj")) and len(text) >= 8:
        market = text[:2].upper()
        code = _normalize_code(text[2:])
        return f"{code}.{market}"

    code = _normalize_code(text)
    return symbol_from_code(code)


def symbol_from_code(code: object) -> str:
    """Infer exchange suffix from a six-digit A-share code."""

    code_text = _normalize_code(code)
    if code_text.startswith(("8", "4", "920")):
        return f"{code_text}.BJ"
    if code_text.startswith("6"):
        return f"{code_text}.SH"
    return f"{code_text}.SZ"


def to_qlib_symbol(symbol: object) -> str:
    """Convert `000001.SZ` to Qlib's `SZ000001` style."""

    normalized = normalize_symbol(symbol)
    code, market = normalized.split(".", 1)
    return f"{market}{code}"


def from_qlib_symbol(symbol: object) -> str:
    """Convert Qlib's `SZ000001` style to `000001.SZ`."""

    text = str(symbol).strip()
    if len(text) >= 8 and text[:2].upper() in {"SH", "SZ", "BJ"}:
        return f"{_normalize_code(text[2:])}.{text[:2].upper()}"
    return normalize_symbol(text)


def to_ak_daily_symbol(symbol: object) -> str:
    """Convert a symbol to the AKShare `stock_zh_a_daily` format."""

    normalized = normalize_symbol(symbol)
    code, market = normalized.split(".", 1)
    return f"{market.lower()}{code}"


def to_plain_code(symbol: object) -> str:
    """Return the six-digit code part."""

    return normalize_symbol(symbol).split(".", 1)[0]


def is_st_name(name: object) -> bool:
    """Return whether a Chinese A-share name should be treated as ST."""

    text = str(name).strip().upper()
    return "ST" in text


def limit_rate(symbol: object, is_st: bool = False) -> float:
    """Return the daily price-limit rate for an A-share symbol."""

    code = normalize_symbol(symbol).split(".", 1)[0]
    if is_st:
        return 0.05
    if code.startswith(("300", "301", "688")):
        return 0.20
    if code.startswith(("8", "4", "920")):
        return 0.30
    return 0.10


def normalize_metadata_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Normalize metadata columns for sidecar storage."""

    if frame.empty:
        return pd.DataFrame(columns=["symbol", "qlib_symbol", "name", "is_st", "list_date", "industry"])
    data = frame.copy()
    if "symbol" not in data.columns and "code" in data.columns:
        data["symbol"] = data["code"].map(symbol_from_code)
    data["symbol"] = data["symbol"].map(normalize_symbol)
    data["qlib_symbol"] = data["symbol"].map(to_qlib_symbol)
    if "name" not in data.columns:
        data["name"] = ""
    if "is_st" not in data.columns:
        data["is_st"] = data["name"].map(is_st_name)
    if "list_date" in data.columns:
        data["list_date"] = pd.to_datetime(data["list_date"], errors="coerce")
    else:
        data["list_date"] = pd.NaT
    if "industry" not in data.columns:
        data["industry"] = ""
    return data[["symbol", "qlib_symbol", "name", "is_st", "list_date", "industry"]].drop_duplicates("symbol")


def write_metadata_sidecar(frame: pd.DataFrame, output_dir: str | Path) -> Path:
    """Write instrument metadata as parquet, falling back to CSV."""

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    data = normalize_metadata_frame(frame)
    parquet_path = out_dir / "instruments.parquet"
    try:
        data.to_parquet(parquet_path, index=False)
        return parquet_path
    except Exception:
        csv_path = out_dir / "instruments.csv"
        data.to_csv(csv_path, index=False)
        return csv_path


def _normalize_code(value: object) -> str:
    text = str(value).strip().split(".", 1)[0]
    if text.lower() in {"nan", "none", ""}:
        raise ValueError("Empty A-share code.")
    if not text.isdigit():
        raise ValueError(f"Invalid A-share code: {value!r}")
    return text.zfill(6)
