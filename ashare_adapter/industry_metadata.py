"""Industry metadata enrichment helpers."""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable

import pandas as pd

from ashare_adapter.metadata import normalize_symbol, symbol_from_code
from ashare_adapter.qlib_converter import read_bars, write_bars

LOGGER = logging.getLogger(__name__)

EMPTY_TEXT = {"", "nan", "none", "null", "--", "-", "na", "n/a"}


def industry_coverage(frame: pd.DataFrame, industry_col: str = "industry") -> dict[str, object]:
    """Return symbol-level industry coverage for a metadata or bars frame."""

    if frame.empty or "symbol" not in frame.columns:
        return {"symbols": 0, "industry_nonempty": 0, "industry_coverage": 0.0}
    data = frame[["symbol", industry_col]].copy() if industry_col in frame.columns else frame[["symbol"]].copy()
    if industry_col not in data.columns:
        data[industry_col] = ""
    data["symbol"] = data["symbol"].map(normalize_symbol)
    data[industry_col] = data[industry_col].map(_clean_text)
    by_symbol = data.groupby("symbol", as_index=False)[industry_col].agg(lambda values: next((v for v in values if v), ""))
    nonempty = int((by_symbol[industry_col] != "").sum())
    total = int(len(by_symbol))
    return {"symbols": total, "industry_nonempty": nonempty, "industry_coverage": nonempty / total if total else 0.0}


def merge_industry_map(
    frame: pd.DataFrame,
    industry_map: pd.DataFrame,
    overwrite: bool = False,
    industry_col: str = "industry",
) -> pd.DataFrame:
    """Merge a symbol -> industry map into a metadata or bars frame."""

    if frame.empty or industry_map.empty:
        return frame.copy()
    data = frame.copy()
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if industry_col not in data.columns:
        data[industry_col] = ""
    mapping = industry_map.copy()
    mapping["symbol"] = mapping["symbol"].map(normalize_symbol)
    mapping[industry_col] = mapping[industry_col].map(_clean_text)
    mapping = mapping[mapping[industry_col] != ""].drop_duplicates("symbol", keep="last")
    industry_by_symbol = mapping.set_index("symbol")[industry_col]
    incoming = data["symbol"].map(industry_by_symbol).fillna("")
    existing = data[industry_col].map(_clean_text)
    should_update = incoming.ne("") & (overwrite | existing.eq(""))
    data.loc[should_update, industry_col] = incoming[should_update]
    if "industry_source" in mapping.columns:
        if "industry_source" not in data.columns:
            data["industry_source"] = ""
        source_by_symbol = mapping.set_index("symbol")["industry_source"].fillna("").astype(str)
        incoming_source = data["symbol"].map(source_by_symbol).fillna("")
        data.loc[should_update, "industry_source"] = incoming_source[should_update]
    return data


def missing_industry_symbols(frame: pd.DataFrame, symbols: Iterable[str] | None = None) -> list[str]:
    """Return normalized symbols without a non-empty industry."""

    if frame.empty:
        return sorted({normalize_symbol(symbol) for symbol in symbols or []})
    data = frame.copy()
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if "industry" not in data.columns:
        data["industry"] = ""
    if symbols is not None:
        target = {normalize_symbol(symbol) for symbol in symbols}
        data = data[data["symbol"].isin(target)]
        present = set(data["symbol"])
        missing_rows = target - present
    else:
        missing_rows = set()
    data["industry"] = data["industry"].map(_clean_text)
    missing = set(data.loc[data["industry"] == "", "symbol"]) | missing_rows
    return sorted(missing)


def fetch_eastmoney_industry_map(ak_module, sleep: float = 0.05) -> pd.DataFrame:
    """Fetch Eastmoney industry-board constituents as a symbol -> industry map."""

    industry_names = ak_module.stock_board_industry_name_em()
    if industry_names.empty:
        return _empty_map()
    name_col = _find_column(industry_names, ["board", "name"], fallback_idx=1)
    rows: list[dict[str, object]] = []
    for industry in industry_names[name_col].dropna().astype(str).map(_clean_text):
        if not industry:
            continue
        try:
            cons = ak_module.stock_board_industry_cons_em(symbol=industry)
        except Exception as exc:  # pragma: no cover - network/API dependent
            LOGGER.warning("Eastmoney industry constituents unavailable for %s: %s", industry, exc)
            continue
        code_col = _find_column(cons, ["code"], fallback_idx=1)
        name_col_cons = _find_column(cons, ["name"], fallback_idx=2)
        for _, row in cons.iterrows():
            try:
                symbol = symbol_from_code(row[code_col])
            except (KeyError, ValueError):
                continue
            rows.append(
                {
                    "symbol": symbol,
                    "industry": industry,
                    "industry_source": "eastmoney_board_industry",
                    "name": "" if name_col_cons is None or pd.isna(row[name_col_cons]) else str(row[name_col_cons]),
                }
            )
        if sleep > 0:
            time.sleep(float(sleep))
    return pd.DataFrame(rows).drop_duplicates("symbol", keep="last") if rows else _empty_map()


def fetch_cninfo_industry_map(
    ak_module,
    symbols: Iterable[str],
    start_date: str = "19900101",
    end_date: str = "20260627",
    workers: int = 4,
    retry: int = 1,
    sleep: float = 0.02,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch latest CNINFO industry classification for symbols."""

    symbol_list = sorted({normalize_symbol(symbol) for symbol in symbols})

    def fetch_one(symbol: str) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        code = symbol.split(".", 1)[0]
        last_exc: Exception | None = None
        for attempt in range(max(1, int(retry) + 1)):
            try:
                raw = ak_module.stock_industry_change_cninfo(symbol=code, start_date=start_date, end_date=end_date)
                industry = parse_cninfo_industry(raw)
                if industry:
                    return (
                        {
                            "symbol": symbol,
                            "industry": industry,
                            "industry_source": "cninfo_industry_change",
                        },
                        None,
                    )
                return None, {"symbol": symbol, "reason": "empty_industry"}
            except Exception as exc:  # pragma: no cover - network/API dependent
                last_exc = exc
                if sleep > 0 and attempt < retry:
                    time.sleep(float(sleep))
        return None, {"symbol": symbol, "reason": str(last_exc) if last_exc else "unknown_error"}

    max_workers = min(max(1, int(workers or 1)), max(1, len(symbol_list)))
    if max_workers == 1:
        results = [fetch_one(symbol) for symbol in symbol_list]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            results = list(executor.map(fetch_one, symbol_list))
    rows = [row for row, _ in results if row is not None]
    failures = [failure for _, failure in results if failure is not None]
    return (
        pd.DataFrame(rows).drop_duplicates("symbol", keep="last") if rows else _empty_map(),
        pd.DataFrame(failures, columns=["symbol", "reason"]) if failures else pd.DataFrame(columns=["symbol", "reason"]),
    )


def parse_cninfo_industry(raw: pd.DataFrame) -> str:
    """Parse one CNINFO industry-change response into the latest detailed industry."""

    if raw.empty:
        return ""
    data = raw.copy()
    date_col = data.columns[-1]
    data["_parsed_date"] = pd.to_datetime(data[date_col], errors="coerce")
    data = data.sort_values("_parsed_date", ascending=False, na_position="last")
    candidate_positions = [idx for idx in [4, 3, 2, 1] if idx < len(raw.columns)]
    for _, row in data.iterrows():
        for idx in candidate_positions:
            value = _clean_text(row.iloc[idx])
            if value:
                return value
    return ""


def update_bars_industry(path: str | Path, industry_map: pd.DataFrame, overwrite: bool = False) -> tuple[dict[str, object], dict[str, object]]:
    """Update the industry column in a bars file in place."""

    bars_path = Path(path)
    bars = read_bars(bars_path)
    before = industry_coverage(bars)
    updated = merge_industry_map(bars, industry_map, overwrite=overwrite)
    after = industry_coverage(updated)
    write_bars(updated, bars_path)
    return before, after


def _find_column(frame: pd.DataFrame, keywords: list[str], fallback_idx: int | None = None) -> str | None:
    if frame.empty:
        return None
    lowered = {str(column).lower(): column for column in frame.columns}
    for keyword in keywords:
        for lowered_name, column in lowered.items():
            if keyword.lower() in lowered_name:
                return str(column)
    if fallback_idx is not None and fallback_idx < len(frame.columns):
        return str(frame.columns[fallback_idx])
    return str(frame.columns[0])


def _clean_text(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in EMPTY_TEXT else text


def _empty_map() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "industry", "industry_source"])
