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
INDUSTRY_SCHEMA_COLUMNS = [
    "symbol",
    "industry",
    "industry_level",
    "industry_source",
    "industry_update_date",
    "industry_raw",
    "source_priority",
    "is_point_in_time",
]
INDUSTRY_META_COLUMNS = ["industry", "industry_source", "industry_update_date"]

SOURCE_PRIORITY = {
    "cninfo_industry_change": 1,
    "eastmoney_board_industry": 2,
    "akshare_exchange_metadata": 3,
    "akshare_metadata_cache": 3,
    "existing_cache": 4,
    "unknown": 99,
}


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


def normalize_industry_schema(
    frame: pd.DataFrame,
    *,
    default_source: str = "unknown",
    default_level: str = "",
    is_point_in_time: bool = False,
) -> pd.DataFrame:
    """Normalize any industry map to the project metadata schema."""

    if frame is None or frame.empty:
        return pd.DataFrame(columns=INDUSTRY_SCHEMA_COLUMNS)
    data = frame.copy()
    if "symbol" not in data.columns and "code" in data.columns:
        data["symbol"] = data["code"].map(symbol_from_code)
    if "symbol" not in data.columns:
        raise ValueError("Industry metadata must contain symbol or code.")
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if "industry" not in data.columns:
        data["industry"] = ""
    data["industry_raw"] = data.get("industry_raw", data["industry"])
    data["industry"] = data["industry"].map(_clean_text)
    data["industry_raw"] = data["industry_raw"].map(_clean_text)
    if "industry_source" not in data.columns:
        data["industry_source"] = default_source
    data["industry_source"] = data["industry_source"].fillna("").astype(str).str.strip()
    data.loc[data["industry_source"].eq(""), "industry_source"] = default_source
    if "industry_level" not in data.columns:
        data["industry_level"] = default_level
    if "industry_update_date" in data.columns:
        data["industry_update_date"] = pd.to_datetime(data["industry_update_date"], errors="coerce")
    else:
        data["industry_update_date"] = pd.NaT
    if "source_priority" not in data.columns:
        data["source_priority"] = data["industry_source"].map(lambda value: SOURCE_PRIORITY.get(str(value), 50))
    data["source_priority"] = pd.to_numeric(data["source_priority"], errors="coerce").fillna(50).astype(int)
    if "is_point_in_time" not in data.columns:
        data["is_point_in_time"] = bool(is_point_in_time)
    data["is_point_in_time"] = data["is_point_in_time"].astype("boolean").fillna(False).astype(bool)
    return data[INDUSTRY_SCHEMA_COLUMNS].drop_duplicates("symbol", keep="last")


def resolve_industry_sources(
    existing: pd.DataFrame | None = None,
    cninfo: pd.DataFrame | None = None,
    eastmoney: pd.DataFrame | None = None,
    akshare_meta: pd.DataFrame | None = None,
    overwrite: bool = False,
) -> pd.DataFrame:
    """Resolve multiple industry sources with explicit source priority."""

    frames: list[pd.DataFrame] = []
    if existing is not None and not existing.empty:
        frames.append(normalize_industry_schema(existing, default_source="existing_cache", default_level="existing"))
    if akshare_meta is not None and not akshare_meta.empty:
        frames.append(normalize_industry_schema(akshare_meta, default_source="akshare_exchange_metadata", default_level="akshare"))
    if eastmoney is not None and not eastmoney.empty:
        frames.append(normalize_industry_schema(eastmoney, default_source="eastmoney_board_industry", default_level="eastmoney_board"))
    if cninfo is not None and not cninfo.empty:
        frames.append(normalize_industry_schema(cninfo, default_source="cninfo_industry_change", default_level="cninfo_latest"))
    if not frames:
        return pd.DataFrame(columns=INDUSTRY_SCHEMA_COLUMNS)

    data = pd.concat(frames, ignore_index=True)
    data = data[data["industry"].map(_clean_text).ne("")]
    if data.empty:
        return pd.DataFrame(columns=INDUSTRY_SCHEMA_COLUMNS)
    data = data.sort_values(["symbol", "source_priority", "industry_update_date"], ascending=[True, True, False])
    if overwrite:
        return data.drop_duplicates("symbol", keep="first").reset_index(drop=True)

    existing_norm = normalize_industry_schema(existing, default_source="existing_cache", default_level="existing") if existing is not None and not existing.empty else pd.DataFrame(columns=INDUSTRY_SCHEMA_COLUMNS)
    existing_nonempty = existing_norm[existing_norm["industry"].map(_clean_text).ne("")].drop_duplicates("symbol", keep="last")
    fill_candidates = data[~data["symbol"].isin(set(existing_nonempty["symbol"]))].drop_duplicates("symbol", keep="first")
    return pd.concat([existing_nonempty, fill_candidates], ignore_index=True).drop_duplicates("symbol", keep="first")


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
    same_industry = incoming.ne("") & existing.eq(incoming)
    if "industry_source" in mapping.columns:
        if "industry_source" not in data.columns:
            data["industry_source"] = ""
        source_by_symbol = mapping.set_index("symbol")["industry_source"].fillna("").astype(str)
        incoming_source = data["symbol"].map(source_by_symbol).fillna("")
        missing_source = data["industry_source"].fillna("").astype(str).str.strip().eq("")
        source_update = incoming_source.ne("") & (should_update | (same_industry & missing_source))
        data.loc[source_update, "industry_source"] = incoming_source[source_update]
    if "industry_update_date" in mapping.columns:
        if "industry_update_date" not in data.columns:
            data["industry_update_date"] = pd.NaT
        update_by_symbol = pd.to_datetime(mapping.set_index("symbol")["industry_update_date"], errors="coerce")
        incoming_update = data["symbol"].map(update_by_symbol)
        existing_update = pd.to_datetime(data["industry_update_date"], errors="coerce")
        update_mask = incoming_update.notna() & (should_update | (same_industry & existing_update.isna()))
        data.loc[update_mask, "industry_update_date"] = incoming_update[update_mask]
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
                    "industry_update_date": pd.Timestamp.today().normalize(),
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
                    update_date = parse_cninfo_update_date(raw)
                    return (
                        {
                            "symbol": symbol,
                            "industry": industry,
                            "industry_source": "cninfo_industry_change",
                            "industry_update_date": update_date,
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


def parse_cninfo_update_date(raw: pd.DataFrame) -> pd.Timestamp | None:
    """Parse one CNINFO industry-change response into its latest update date."""

    if raw.empty:
        return None
    parsed = pd.to_datetime(raw.iloc[:, -1], errors="coerce").dropna()
    if parsed.empty:
        return None
    return pd.Timestamp(parsed.max()).normalize()


def update_bars_industry(path: str | Path, industry_map: pd.DataFrame, overwrite: bool = False) -> tuple[dict[str, object], dict[str, object]]:
    """Update the industry column in a bars file in place."""

    bars_path = Path(path)
    bars = read_bars(bars_path)
    before = industry_coverage(bars)
    updated = merge_industry_map(bars, industry_map, overwrite=overwrite)
    after = industry_coverage(updated)
    write_bars(updated, bars_path)
    return before, after


def industry_unknown_by_date(
    bars: pd.DataFrame,
    selected_col: str = "selected",
) -> pd.DataFrame:
    """Summarize unknown industry share by date for a bars/universe frame."""

    if bars.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "rows",
                "selected_count",
                "unknown_rows",
                "unknown_selected_count",
                "unknown_row_ratio",
                "unknown_selected_ratio",
            ]
        )
    data = bars.copy()
    data["date"] = pd.to_datetime(data["date"])
    if "industry" not in data.columns:
        data["industry"] = ""
    if selected_col not in data.columns:
        selected_col = "eligible" if "eligible" in data.columns else selected_col
    if selected_col not in data.columns:
        data[selected_col] = True
    data["industry"] = data["industry"].map(_clean_text)
    unknown = data["industry"].eq("")
    selected = data[selected_col].fillna(False).astype(bool)
    grouped = data.assign(_unknown=unknown, _selected=selected, _unknown_selected=unknown & selected).groupby("date")
    result = grouped.agg(
        rows=("symbol", "count"),
        selected_count=("_selected", "sum"),
        unknown_rows=("_unknown", "sum"),
        unknown_selected_count=("_unknown_selected", "sum"),
    ).reset_index()
    result["unknown_row_ratio"] = result["unknown_rows"] / result["rows"].where(result["rows"] != 0)
    result["unknown_selected_ratio"] = result["unknown_selected_count"] / result["selected_count"].where(result["selected_count"] != 0)
    return result.sort_values("date").reset_index(drop=True)


def industry_unknown_by_position(positions: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Summarize position-weighted unknown industry exposure by date."""

    if positions.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "position_count",
                "unknown_position_count",
                "gross_weight",
                "unknown_weight",
                "unknown_position_ratio",
                "unknown_weight_ratio",
            ]
        )
    pos = positions.copy()
    pos["date"] = pd.to_datetime(pos["date"])
    pos["symbol"] = pos["symbol"].map(normalize_symbol)
    pos["weight"] = pd.to_numeric(pos["weight"], errors="coerce").fillna(0.0)

    meta = bars[["date", "symbol", "industry"]].copy()
    meta["date"] = pd.to_datetime(meta["date"])
    meta["symbol"] = meta["symbol"].map(normalize_symbol)
    meta["industry"] = meta["industry"].map(_clean_text)
    meta = meta.drop_duplicates(["date", "symbol"])
    merged = pos.merge(meta, on=["date", "symbol"], how="left")
    merged["industry"] = merged["industry"].map(_clean_text)
    merged["_unknown"] = merged["industry"].eq("")
    merged["_abs_weight"] = merged["weight"].abs()
    grouped = merged.groupby("date")
    result = grouped.agg(
        position_count=("symbol", "count"),
        unknown_position_count=("_unknown", "sum"),
        gross_weight=("_abs_weight", "sum"),
        unknown_weight=("_abs_weight", lambda values: float(values[merged.loc[values.index, "_unknown"]].sum())),
    ).reset_index()
    result["unknown_position_ratio"] = result["unknown_position_count"] / result["position_count"].where(result["position_count"] != 0)
    result["unknown_weight_ratio"] = result["unknown_weight"] / result["gross_weight"].where(result["gross_weight"] != 0)
    return result.sort_values("date").reset_index(drop=True)


def industry_coverage_report(
    bars: pd.DataFrame,
    positions: pd.DataFrame | None = None,
    selected_col: str = "selected",
) -> dict[str, pd.DataFrame | dict[str, object]]:
    """Build industry metadata coverage reports for bars and optional positions."""

    data = bars.copy()
    if data.empty:
        summary = {
            "symbol_level_coverage": 0.0,
            "row_level_coverage": 0.0,
            "selected_universe_coverage": 0.0,
            "position_weighted_coverage": None,
            "unknown_symbol_count": 0,
            "unknown_selected_avg_ratio": 0.0,
            "unknown_position_weight_avg": None,
            "industry_source_distribution": {},
            "industry_quality_status": "failed",
            "quality_status": "failed",
        }
        return {
            "summary": summary,
            "industry_metadata_coverage": pd.DataFrame(),
            "industry_source_distribution": pd.DataFrame(columns=["industry_source", "rows", "row_ratio"]),
            "industry_unknown_by_date": pd.DataFrame(),
            "industry_unknown_by_selected_universe": pd.DataFrame(),
            "industry_unknown_by_position": pd.DataFrame(),
        }

    data["symbol"] = data["symbol"].map(normalize_symbol)
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if "industry" not in data.columns:
        data["industry"] = ""
    data["industry"] = data["industry"].map(_clean_text)
    if "industry_source" not in data.columns:
        data["industry_source"] = ""
    data["industry_source"] = data["industry_source"].fillna("").astype(str).str.strip()
    data.loc[data["industry_source"].eq("") & data["industry"].ne(""), "industry_source"] = "unknown_source"
    if selected_col not in data.columns:
        selected_col = "eligible" if "eligible" in data.columns else selected_col
    if selected_col not in data.columns:
        data[selected_col] = True
    selected = data[selected_col].astype("boolean").fillna(False).astype(bool)
    known = data["industry"].ne("")

    by_symbol = data.groupby("symbol", as_index=False).agg(
        industry=("industry", lambda values: next((value for value in values if value), "")),
        industry_source=("industry_source", lambda values: next((str(value) for value in values if str(value).strip()), "")),
        rows=("date", "count"),
        selected_rows=(selected_col, lambda values: int(pd.Series(values).astype("boolean").fillna(False).sum())),
    )
    by_symbol["has_industry"] = by_symbol["industry"].ne("")
    by_symbol["is_unknown"] = ~by_symbol["has_industry"]

    source_dist = data.assign(industry_source=data["industry_source"].replace("", "unknown")).groupby("industry_source").agg(rows=("symbol", "count")).reset_index()
    source_dist["row_ratio"] = source_dist["rows"] / len(data)
    unknown_by_date = industry_unknown_by_date(data, selected_col=selected_col)
    selected_unknown = unknown_by_date[
        [
            "date",
            "selected_count",
            "unknown_selected_count",
            "unknown_selected_ratio",
        ]
    ].rename(columns={"unknown_selected_ratio": "unknown_ratio"})

    position_report = (
        industry_unknown_by_position(positions, data)
        if positions is not None and not positions.empty
        else pd.DataFrame(
            columns=[
                "date",
                "position_count",
                "unknown_position_count",
                "gross_weight",
                "unknown_weight",
                "unknown_position_ratio",
                "unknown_weight_ratio",
            ]
        )
    )
    position_unknown = _mean_or_none(position_report.get("unknown_weight_ratio"))
    position_coverage = None if position_unknown is None else 1.0 - position_unknown

    symbol_coverage = float(by_symbol["has_industry"].mean()) if len(by_symbol) else 0.0
    row_coverage = float(known.mean()) if len(data) else 0.0
    selected_coverage = float(known[selected].mean()) if int(selected.sum()) else 0.0
    unknown_selected_avg = _mean_or_zero(unknown_by_date.get("unknown_selected_ratio"))
    summary = {
        "symbol_level_coverage": symbol_coverage,
        "row_level_coverage": row_coverage,
        "selected_universe_coverage": selected_coverage,
        "position_weighted_coverage": position_coverage,
        "unknown_symbol_count": int((~by_symbol["has_industry"]).sum()),
        "unknown_selected_avg_ratio": unknown_selected_avg,
        "unknown_position_weight_avg": position_unknown,
        "industry_source_distribution": {str(row["industry_source"]): int(row["rows"]) for _, row in source_dist.iterrows()},
        "industry_source_top": str(source_dist.sort_values("rows", ascending=False)["industry_source"].iloc[0]) if not source_dist.empty else "",
    }
    status = industry_quality_status(summary)
    summary["industry_quality_status"] = status
    summary["quality_status"] = status
    if status == "failed":
        summary["caveat"] = "Industry attribution is not reliable due to insufficient metadata coverage."

    return {
        "summary": summary,
        "industry_metadata_coverage": by_symbol,
        "industry_source_distribution": source_dist,
        "industry_unknown_by_date": unknown_by_date,
        "industry_unknown_by_selected_universe": selected_unknown,
        "industry_unknown_by_position": position_report,
    }


def industry_quality_status(summary: dict[str, object]) -> str:
    """Classify industry metadata coverage."""

    symbol_cov = float(summary.get("symbol_level_coverage") or 0.0)
    selected_cov = float(summary.get("selected_universe_coverage") or 0.0)
    position_unknown_value = summary.get("unknown_position_weight_avg")
    position_unknown = 0.0 if position_unknown_value is None else float(position_unknown_value)
    if symbol_cov >= 0.95 and selected_cov >= 0.95 and position_unknown <= 0.10:
        return "passed"
    if symbol_cov >= 0.80 and selected_cov >= 0.80 and position_unknown <= 0.30:
        return "warning"
    return "failed"


def write_industry_coverage_report(
    bars: pd.DataFrame,
    output_dir: str | Path,
    positions: pd.DataFrame | None = None,
    selected_col: str = "selected",
) -> dict[str, object]:
    """Write industry coverage reports and return the JSON summary."""

    import json

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = industry_coverage_report(bars, positions=positions, selected_col=selected_col)
    files = {
        "industry_metadata_coverage": "industry_metadata_coverage.csv",
        "industry_source_distribution": "industry_source_distribution.csv",
        "industry_unknown_by_date": "industry_unknown_by_date.csv",
        "industry_unknown_by_selected_universe": "industry_unknown_by_selected_universe.csv",
        "industry_unknown_by_position": "industry_unknown_by_position.csv",
    }
    summary = dict(report["summary"])
    summary["reports"] = {}
    for key, filename in files.items():
        frame = report[key]
        assert isinstance(frame, pd.DataFrame)
        path = out / filename
        frame.to_csv(path, index=False)
        summary["reports"][key] = str(path)
    summary_path = out / "industry_coverage_summary.json"
    summary["reports"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


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


def _mean_or_zero(series: pd.Series | None) -> float:
    value = _mean_or_none(series)
    return 0.0 if value is None else float(value)


def _mean_or_none(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    value = pd.to_numeric(series, errors="coerce").dropna().mean()
    return None if pd.isna(value) else float(value)


def _json_safe(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _empty_map() -> pd.DataFrame:
    return pd.DataFrame(columns=["symbol", "industry", "industry_source"])
