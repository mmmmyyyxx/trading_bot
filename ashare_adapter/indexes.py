"""Index constituent helpers with local caching and AKShare fallbacks."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

import pandas as pd

from ashare_adapter.metadata import normalize_symbol, to_qlib_symbol

LOGGER = logging.getLogger(__name__)

CONSTITUENT_COLUMNS = ["symbol", "qlib_symbol", "name", "weight", "source"]


def load_index_constituents(
    index_symbol: str = "000300",
    cache_path: str | Path | None = None,
    refresh: bool = False,
    max_symbols: int | None = None,
) -> pd.DataFrame:
    """Load index constituents from cache or AKShare.

    AKShare exposes multiple constituent endpoints and their stability varies.
    This helper tries cached data first, then falls back across the currently
    available AKShare endpoints.
    """

    cache = Path(cache_path) if cache_path else None
    if cache is not None and cache.exists() and not refresh:
        frame = read_constituents(cache)
        return _limit_frame(frame, max_symbols)

    frame = fetch_index_constituents(index_symbol)
    if cache is not None:
        write_constituents(frame, cache)
    return _limit_frame(frame, max_symbols)


def fetch_index_constituents(index_symbol: str = "000300") -> pd.DataFrame:
    """Fetch index constituents through AKShare fallback endpoints."""

    try:
        import akshare as ak  # type: ignore
    except ImportError as exc:
        raise RuntimeError("akshare is not installed. Install with `pip install akshare`.") from exc

    loaders: list[tuple[str, Callable[[], pd.DataFrame]]] = [
        ("index_stock_cons_csindex", lambda: ak.index_stock_cons_csindex(symbol=index_symbol)),
        ("index_stock_cons_weight_csindex", lambda: ak.index_stock_cons_weight_csindex(symbol=index_symbol)),
        ("index_stock_cons_sina", lambda: ak.index_stock_cons_sina(symbol=index_symbol)),
        ("index_stock_cons", lambda: ak.index_stock_cons(symbol=index_symbol)),
    ]
    errors: list[str] = []
    for source, loader in loaders:
        try:
            raw = loader()
            frame = normalize_constituent_frame(raw, source=source)
        except Exception as exc:  # pragma: no cover - network/API dependent
            errors.append(f"{source}: {exc}")
            LOGGER.warning("AKShare index constituent loader failed: %s", errors[-1])
            continue
        if not frame.empty:
            return frame
        errors.append(f"{source}: empty")
    joined = "; ".join(errors) if errors else "no endpoint attempted"
    raise RuntimeError(f"Unable to load index constituents for {index_symbol}: {joined}")


def normalize_constituent_frame(frame: pd.DataFrame, source: str = "") -> pd.DataFrame:
    """Normalize a raw AKShare constituent frame."""

    if frame.empty:
        return pd.DataFrame(columns=CONSTITUENT_COLUMNS)
    code_col = find_code_column(frame)
    name_col = _find_optional_column(frame, ["name", "\u540d\u79f0", "\u7b80\u79f0", "\u6210\u5206\u5238\u540d\u79f0"])
    weight_col = _find_optional_column(frame, ["weight", "\u6743\u91cd"])

    rows: list[dict[str, object]] = []
    seen: set[str] = set()
    for _, row in frame.iterrows():
        try:
            symbol = normalize_symbol(row[code_col])
        except (KeyError, ValueError):
            continue
        if symbol in seen:
            continue
        seen.add(symbol)
        weight = pd.to_numeric(row[weight_col], errors="coerce") if weight_col is not None else pd.NA
        rows.append(
            {
                "symbol": symbol,
                "qlib_symbol": to_qlib_symbol(symbol),
                "name": "" if name_col is None or pd.isna(row[name_col]) else str(row[name_col]),
                "weight": weight,
                "source": source,
            }
        )
    if not rows:
        return pd.DataFrame(columns=CONSTITUENT_COLUMNS)
    return pd.DataFrame(rows)[CONSTITUENT_COLUMNS]


def find_code_column(frame: pd.DataFrame) -> str:
    """Find the stock-code column while avoiding index-code columns."""

    preferred = [
        "\u6210\u5206\u5238\u4ee3\u7801",
        "\u54c1\u79cd\u4ee3\u7801",
        "\u8bc1\u5238\u4ee3\u7801",
        "\u80a1\u7968\u4ee3\u7801",
        "con_code",
        "code",
    ]
    for name in preferred:
        if name in frame.columns and _valid_symbol_count(frame[name]) > 0:
            return str(name)

    scored: list[tuple[int, int, str]] = []
    for position, column in enumerate(frame.columns):
        text = str(column).lower()
        valid_count = _valid_symbol_count(frame[column])
        if valid_count == 0:
            continue
        penalty = 1000 if "\u6307\u6570" in str(column) or "index" in text else 0
        scored.append((valid_count - penalty, -position, str(column)))
    if not scored:
        raise ValueError(f"Unable to find a stock-code column in columns: {list(frame.columns)}")
    return max(scored)[2]


def read_constituents(path: str | Path) -> pd.DataFrame:
    """Read cached constituents from text, CSV, or parquet."""

    source = Path(path)
    if source.suffix.lower() in {".txt", ".list"}:
        symbols = [
            line.strip()
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        frame = pd.DataFrame({"symbol": [normalize_symbol(symbol) for symbol in symbols]})
        frame["qlib_symbol"] = frame["symbol"].map(to_qlib_symbol)
        frame["name"] = ""
        frame["weight"] = pd.NA
        frame["source"] = "cache"
        return frame[CONSTITUENT_COLUMNS].drop_duplicates("symbol")
    if source.suffix.lower() in {".parquet", ".pq"}:
        raw = pd.read_parquet(source)
    else:
        raw = pd.read_csv(source)
    return normalize_constituent_frame(raw, source="cache") if "qlib_symbol" not in raw.columns else _normalize_cached_frame(raw)


def write_constituents(frame: pd.DataFrame, path: str | Path) -> Path:
    """Write constituents to text, CSV, or parquet."""

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _normalize_cached_frame(frame)
    if target.suffix.lower() in {".txt", ".list"}:
        target.write_text("\n".join(data["symbol"].astype(str).tolist()) + "\n", encoding="utf-8")
    elif target.suffix.lower() in {".parquet", ".pq"}:
        try:
            data.to_parquet(target, index=False)
        except Exception:
            target = target.with_suffix(".csv")
            data.to_csv(target, index=False)
    else:
        data.to_csv(target, index=False)
    return target


def symbols_from_constituents(frame: pd.DataFrame, max_symbols: int | None = None) -> list[str]:
    """Return constituent symbols in stable frame order."""

    symbols = [normalize_symbol(symbol) for symbol in frame["symbol"].dropna().astype(str)]
    unique = list(dict.fromkeys(symbols))
    return unique[:max_symbols] if max_symbols else unique


def _limit_frame(frame: pd.DataFrame, max_symbols: int | None) -> pd.DataFrame:
    data = _normalize_cached_frame(frame)
    return data.head(max_symbols).reset_index(drop=True) if max_symbols else data.reset_index(drop=True)


def _normalize_cached_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "symbol" not in data.columns:
        data = normalize_constituent_frame(data, source="cache")
    else:
        data["symbol"] = data["symbol"].map(normalize_symbol)
        data["qlib_symbol"] = data["symbol"].map(to_qlib_symbol)
        if "name" not in data.columns:
            data["name"] = ""
        if "weight" not in data.columns:
            data["weight"] = pd.NA
        if "source" not in data.columns:
            data["source"] = "cache"
    return data[CONSTITUENT_COLUMNS].drop_duplicates("symbol").reset_index(drop=True)


def _find_optional_column(frame: pd.DataFrame, names_or_keywords: list[str]) -> str | None:
    lower_map = {str(column).lower(): str(column) for column in frame.columns}
    for name in names_or_keywords:
        if name.lower() in lower_map:
            return lower_map[name.lower()]
    for column in frame.columns:
        text = str(column).lower()
        if any(name.lower() in text for name in names_or_keywords):
            return str(column)
    return None


def _valid_symbol_count(values: pd.Series) -> int:
    count = 0
    for value in values.dropna().head(100).astype(str):
        try:
            normalize_symbol(value)
        except ValueError:
            continue
        count += 1
    return count
