"""A-share bar data quality audits for real-data research runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

UNKNOWN_SOURCES = {"", "unknown", "nan", "none", "null", "legacy_unknown"}
REQUIRED_BAR_FIELDS = ["date", "symbol", "open", "high", "low", "close", "volume", "amount"]


def normalize_bar_audit_fields(
    bars: pd.DataFrame,
    *,
    price_adjust: str | None = None,
    source_priority: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Ensure audit-only fields exist without adding them to Qlib numeric features."""

    data = bars.copy()
    if data.empty:
        return data
    flags = _split_flags(data.get("quality_flags", pd.Series("", index=data.index)))

    if "data_source" not in data.columns:
        data["data_source"] = "legacy_unknown"
        flags = _append_flag(flags, "legacy_missing_data_source")
    else:
        source = data["data_source"].fillna("").astype(str).str.strip()
        missing = source.eq("") | source.str.lower().isin({"nan", "none", "null"})
        source = source.mask(missing, "legacy_unknown")
        data["data_source"] = source
        flags = _append_flag(flags, "legacy_missing_data_source", missing)

    if "amount_estimated" not in data.columns:
        data["amount_estimated"] = False
    data["amount_estimated"] = data["amount_estimated"].astype("boolean").fillna(False).astype(bool)

    if "price_adjust" not in data.columns:
        data["price_adjust"] = price_adjust or ""
    if "source_fetch_time" not in data.columns:
        data["source_fetch_time"] = ""
    if "source_error" not in data.columns:
        data["source_error"] = ""

    priorities = source_priority or {"eastmoney": 1, "tencent_tx": 2, "ak_daily": 3, "legacy_unknown": 99, "unknown": 99}
    if "source_priority" not in data.columns:
        data["source_priority"] = data["data_source"].map(lambda value: priorities.get(str(value), 50))
    data["source_priority"] = pd.to_numeric(data["source_priority"], errors="coerce").fillna(50).astype(int)

    data["quality_flags"] = _join_flags(flags)
    return data


def validate_ashare_bars_quality(bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return row-level quality flags and a one-row summary frame."""

    data = normalize_bar_audit_fields(bars)
    if data.empty:
        row_quality = pd.DataFrame(columns=["date", "symbol", "quality_status", "quality_flags"])
        summary = _summary_frame({"rows": 0, "symbols": 0, "quality_status": "failed", "failure_reason": "empty_bars"})
        return row_quality, summary

    missing_fields = [field for field in REQUIRED_BAR_FIELDS if field not in data.columns]
    for field in missing_fields:
        data[field] = np.nan
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    data["symbol"] = data["symbol"].fillna("").astype(str)
    for column in ["open", "high", "low", "close", "volume", "amount", "limit_up", "limit_down"]:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")
    for column in ["is_paused", "is_st", "selected", "eligible"]:
        if column not in data.columns:
            data[column] = False if column in {"is_paused", "is_st"} else True
        data[column] = data[column].astype("boolean").fillna(False).astype(bool)
    if "list_date" not in data.columns:
        data["list_date"] = pd.NaT
    data["list_date"] = pd.to_datetime(data["list_date"], errors="coerce")
    if "industry" not in data.columns:
        data["industry"] = ""
    data["industry"] = data["industry"].fillna("").astype(str)

    duplicate_mask = data.duplicated(["date", "symbol"], keep=False)
    unknown_source = _is_unknown_source(data["data_source"])
    valid_ohlc = (
        data[["open", "high", "low", "close"]].notna().all(axis=1)
        & data[["open", "high", "low", "close"]].gt(0).all(axis=1)
        & data["high"].ge(data[["open", "low", "close"]].max(axis=1))
        & data["low"].le(data[["open", "high", "close"]].min(axis=1))
    )
    valid_volume = data["volume"].notna() & data["volume"].ge(0)
    valid_amount = data["amount"].notna() & data["amount"].ge(0) & (data["is_paused"] | data["amount"].gt(0))
    valid_limit = (
        data[["limit_up", "limit_down", "close"]].notna().all(axis=1)
        & data["limit_up"].gt(data["limit_down"])
        & data["limit_up"].ge(data["close"])
        & data["limit_down"].le(data["close"])
    )
    valid_list_date = data["list_date"].isna() | data["list_date"].le(data["date"])
    valid_industry = data["industry"].str.strip().ne("")

    pause_mismatch = (data["volume"].fillna(0).le(0) | data["amount"].fillna(0).le(0)) & ~data["is_paused"]
    vwap = data["amount"] / data["volume"].replace(0, np.nan)
    vwap_ratio = vwap / data["close"].replace(0, np.nan)
    invalid_vwap = data["volume"].gt(0) & data["amount"].gt(0) & (vwap_ratio.lt(0.2) | vwap_ratio.gt(5.0))
    sorted_data = data.sort_values(["symbol", "date"])
    returns = sorted_data.groupby("symbol")["close"].pct_change()
    extreme_return = returns.abs().gt(0.35)
    amount_change = sorted_data.groupby("symbol")["amount"].pct_change()
    valid_amount_jump_base = sorted_data.groupby("symbol")["amount"].shift(1).gt(0) & sorted_data["amount"].gt(0)
    extreme_amount_jump_sorted = valid_amount_jump_base & amount_change.abs().gt(20.0)
    extreme_amount_jump = extreme_amount_jump_sorted.reindex(data.index).fillna(False)

    flag_map = {
        "missing_required_field": pd.Series(bool(missing_fields), index=data.index),
        "unknown_source": unknown_source,
        "invalid_ohlc": ~valid_ohlc,
        "invalid_volume": ~valid_volume,
        "invalid_amount": ~valid_amount,
        "invalid_limit": ~valid_limit,
        "invalid_list_date": ~valid_list_date,
        "missing_industry": ~valid_industry,
        "duplicate_date_symbol": duplicate_mask,
        "pause_flag_mismatch": pause_mismatch,
        "vwap_unit_outlier": invalid_vwap,
        "extreme_return": extreme_return.fillna(False),
        "extreme_amount_jump": extreme_amount_jump,
        "amount_estimated": data["amount_estimated"],
    }
    row_flags = _split_flags(data.get("quality_flags", pd.Series("", index=data.index)))
    for flag, mask in flag_map.items():
        row_flags = _append_flag(row_flags, flag, mask)

    blocking = (
        flag_map["missing_required_field"]
        | flag_map["unknown_source"]
        | flag_map["invalid_ohlc"]
        | flag_map["invalid_amount"]
        | flag_map["invalid_limit"]
        | flag_map["duplicate_date_symbol"]
    )
    warning = (
        flag_map["invalid_volume"]
        | flag_map["invalid_list_date"]
        | flag_map["pause_flag_mismatch"]
        | flag_map["vwap_unit_outlier"]
        | flag_map["extreme_return"].fillna(False)
        | flag_map["extreme_amount_jump"].fillna(False)
        | flag_map["amount_estimated"]
    )
    row_quality = pd.DataFrame(
        {
            "date": data["date"],
            "symbol": data["symbol"],
            "data_source": data["data_source"],
            "is_selected": data["selected"],
            "is_paused": data["is_paused"],
            "is_st": data["is_st"],
            "has_valid_ohlc": valid_ohlc,
            "has_valid_volume": valid_volume,
            "has_valid_amount": valid_amount,
            "has_valid_limit": valid_limit,
            "has_valid_list_date": valid_list_date,
            "has_valid_industry": valid_industry,
            "quality_status": np.where(blocking, "failed", np.where(warning, "warning", "passed")),
            "quality_flags": _join_flags(row_flags),
        }
    )

    selected = data["selected"]
    selected_denominator = int(selected.sum())
    duplicate_count = int(duplicate_mask.sum())
    metrics: dict[str, Any] = {
        "rows": int(len(data)),
        "symbols": int(data["symbol"].replace("", np.nan).dropna().nunique()),
        "start_date": _date_or_empty(data["date"].min()),
        "end_date": _date_or_empty(data["date"].max()),
        "unknown_source_ratio": _ratio(unknown_source.sum(), len(data)),
        "selected_unknown_source_ratio": _ratio((unknown_source & selected).sum(), selected_denominator),
        "amount_estimated_ratio": _ratio(data["amount_estimated"].sum(), len(data)),
        "invalid_ohlc_ratio": _ratio((~valid_ohlc).sum(), len(data)),
        "invalid_amount_ratio": _ratio((~valid_amount).sum(), len(data)),
        "invalid_limit_ratio": _ratio((~valid_limit).sum(), len(data)),
        "invalid_volume_ratio": _ratio((~valid_volume).sum(), len(data)),
        "pause_flag_mismatch_ratio": _ratio(pause_mismatch.sum(), len(data)),
        "vwap_unit_outlier_ratio": _ratio(invalid_vwap.sum(), len(data)),
        "extreme_amount_jump_ratio": _ratio(extreme_amount_jump.sum(), len(data)),
        "duplicate_rows": duplicate_count,
        "missing_required_fields": missing_fields,
        "missing_bars_estimate": int(_missing_bars_by_symbol(data)["missing_bar_count"].sum()),
    }
    metrics["quality_status"] = quality_status_from_metrics(metrics)
    if metrics["quality_status"] == "failed":
        metrics["failure_reason"] = _failure_reason(metrics)

    return row_quality.sort_values(["date", "symbol"]).reset_index(drop=True), _summary_frame(metrics)


def quality_status_from_metrics(metrics: dict[str, Any]) -> str:
    """Classify bar quality from summary metrics."""

    if int(metrics.get("rows") or 0) <= 0:
        return "failed"
    if int(metrics.get("duplicate_rows") or 0) > 0:
        return "failed"
    if (
        float(metrics.get("unknown_source_ratio") or 0) <= 0.05
        and float(metrics.get("selected_unknown_source_ratio") or 0) <= 0.03
        and float(metrics.get("invalid_ohlc_ratio") or 0) <= 0.001
        and float(metrics.get("invalid_amount_ratio") or 0) <= 0.005
        and float(metrics.get("invalid_limit_ratio") or 0) <= 0.02
        and float(metrics.get("vwap_unit_outlier_ratio") or 0) <= 0.05
    ):
        return "passed"
    if (
        float(metrics.get("unknown_source_ratio") or 0) <= 0.20
        and float(metrics.get("selected_unknown_source_ratio") or 0) <= 0.10
        and float(metrics.get("invalid_ohlc_ratio") or 0) <= 0.01
        and float(metrics.get("invalid_amount_ratio") or 0) <= 0.02
        and float(metrics.get("invalid_limit_ratio") or 0) <= 0.05
        and float(metrics.get("vwap_unit_outlier_ratio") or 0) <= 0.20
    ):
        return "warning"
    return "failed"


def selected_universe_quality(bars: pd.DataFrame, selected_col: str = "selected") -> pd.DataFrame:
    """Summarize quality of the selected universe by date."""

    row_quality, _ = validate_ashare_bars_quality(bars)
    if row_quality.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "selected_count",
                "unknown_source_count",
                "unknown_source_ratio",
                "amount_estimated_count",
                "amount_estimated_ratio",
                "invalid_amount_count",
                "invalid_limit_count",
                "median_amount",
                "min_amount",
                "max_amount",
            ]
        )
    data = normalize_bar_audit_fields(bars).copy()
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    if selected_col not in data.columns:
        selected_col = "selected" if "selected" in data.columns else "eligible"
    if selected_col not in data.columns:
        data[selected_col] = True
    data["_selected"] = data[selected_col].astype("boolean").fillna(False).astype(bool)
    data["amount"] = pd.to_numeric(data.get("amount"), errors="coerce")
    data = data.merge(
        row_quality[["date", "symbol", "data_source", "has_valid_amount", "has_valid_limit"]],
        on=["date", "symbol"],
        how="left",
        suffixes=("", "_quality"),
    )
    data["_unknown_source"] = _is_unknown_source(data["data_source"])
    data["_amount_estimated"] = data["amount_estimated"].astype("boolean").fillna(False).astype(bool)
    selected = data[data["_selected"]].copy()
    if selected.empty:
        return pd.DataFrame(columns=["date", "selected_count"])
    grouped = selected.groupby("date")
    result = grouped.agg(
        selected_count=("symbol", "count"),
        unknown_source_count=("_unknown_source", "sum"),
        amount_estimated_count=("_amount_estimated", "sum"),
        invalid_amount_count=("has_valid_amount", lambda values: int((~values.fillna(False).astype(bool)).sum())),
        invalid_limit_count=("has_valid_limit", lambda values: int((~values.fillna(False).astype(bool)).sum())),
        median_amount=("amount", "median"),
        min_amount=("amount", "min"),
        max_amount=("amount", "max"),
    ).reset_index()
    result["unknown_source_ratio"] = result["unknown_source_count"] / result["selected_count"].where(result["selected_count"] != 0)
    result["amount_estimated_ratio"] = result["amount_estimated_count"] / result["selected_count"].where(result["selected_count"] != 0)
    return result.sort_values("date").reset_index(drop=True)


def build_data_quality_report(bars: pd.DataFrame, selected_col: str = "selected") -> dict[str, pd.DataFrame | dict[str, Any]]:
    """Build all tabular data-quality reports."""

    data = normalize_bar_audit_fields(bars)
    row_quality, summary_frame = validate_ashare_bars_quality(data)
    summary = summary_frame.iloc[0].to_dict() if not summary_frame.empty else {}
    data["date"] = pd.to_datetime(data.get("date"), errors="coerce")
    for column in ["open", "high", "low", "close", "volume", "amount", "limit_up", "limit_down"]:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")

    merged = row_quality.copy()
    if not merged.empty:
        by_source = merged.groupby("data_source", dropna=False).agg(
            rows=("symbol", "count"),
            symbols=("symbol", "nunique"),
            failed_rows=("quality_status", lambda values: int((values == "failed").sum())),
            warning_rows=("quality_status", lambda values: int((values == "warning").sum())),
            selected_rows=("is_selected", "sum"),
        ).reset_index()
        by_source["row_ratio"] = by_source["rows"] / len(merged)
        by_date = merged.groupby("date").agg(
            rows=("symbol", "count"),
            selected_rows=("is_selected", "sum"),
            failed_rows=("quality_status", lambda values: int((values == "failed").sum())),
            unknown_source_rows=("data_source", lambda values: int(_is_unknown_source(values).sum())),
        ).reset_index()
        by_symbol = merged.groupby("symbol").agg(
            rows=("date", "count"),
            failed_rows=("quality_status", lambda values: int((values == "failed").sum())),
            warning_rows=("quality_status", lambda values: int((values == "warning").sum())),
            unknown_source_rows=("data_source", lambda values: int(_is_unknown_source(values).sum())),
        ).reset_index()
    else:
        by_source = pd.DataFrame()
        by_date = pd.DataFrame()
        by_symbol = pd.DataFrame()

    missing_fields = pd.DataFrame(
        [{"field": field, "missing": field not in bars.columns} for field in REQUIRED_BAR_FIELDS + ["data_source", "amount_estimated", "limit_up", "limit_down", "is_paused", "is_st"]]
    )
    vwap = data["amount"] / data["volume"].replace(0, np.nan)
    amount_vwap = pd.DataFrame(
        {
            "date": data.get("date"),
            "symbol": data.get("symbol"),
            "data_source": data.get("data_source"),
            "close": data["close"],
            "vwap": vwap,
            "vwap_to_close": vwap / data["close"].replace(0, np.nan),
        }
    )
    amount_vwap["is_outlier"] = amount_vwap["vwap_to_close"].lt(0.2) | amount_vwap["vwap_to_close"].gt(5.0)
    limit_coverage = pd.DataFrame(
        [
            {
                "rows": int(len(data)),
                "limit_up_non_null_ratio": _ratio(data["limit_up"].notna().sum(), len(data)),
                "limit_down_non_null_ratio": _ratio(data["limit_down"].notna().sum(), len(data)),
                "invalid_limit_ratio": summary.get("invalid_limit_ratio"),
            }
        ]
    )
    pause_st = pd.DataFrame(
        [
            {
                "rows": int(len(data)),
                "is_paused_coverage": float("is_paused" in data.columns),
                "is_st_coverage": float("is_st" in data.columns),
                "paused_rows": int(data.get("is_paused", pd.Series(False, index=data.index)).astype("boolean").fillna(False).sum()),
                "st_rows": int(data.get("is_st", pd.Series(False, index=data.index)).astype("boolean").fillna(False).sum()),
            }
        ]
    )
    duplicate_rows = data.loc[data.duplicated(["date", "symbol"], keep=False)].copy()
    sorted_data = data.sort_values(["symbol", "date"])
    returns = sorted_data.groupby("symbol")["close"].pct_change()
    extreme_rows = sorted_data.loc[returns.abs().gt(0.35).fillna(False)].copy()
    previous_amount = sorted_data.groupby("symbol")["amount"].shift(1)
    amount_change = sorted_data.groupby("symbol")["amount"].pct_change()
    amount_jump_mask = previous_amount.gt(0) & sorted_data["amount"].gt(0) & amount_change.abs().gt(20.0)
    extreme_amount_jump_rows = sorted_data.loc[amount_jump_mask.fillna(False)].copy()
    if not extreme_amount_jump_rows.empty:
        extreme_amount_jump_rows["previous_amount"] = previous_amount.loc[extreme_amount_jump_rows.index]
        extreme_amount_jump_rows["amount_pct_change"] = amount_change.loc[extreme_amount_jump_rows.index]

    return {
        "summary": summary,
        "row_quality": row_quality,
        "data_quality_by_source": by_source,
        "data_quality_by_date": by_date,
        "data_quality_by_symbol": by_symbol,
        "selected_universe_quality": selected_universe_quality(data, selected_col=selected_col),
        "missing_fields_summary": missing_fields,
        "amount_vwap_unit_check": amount_vwap,
        "limit_field_coverage": limit_coverage,
        "pause_st_coverage": pause_st,
        "duplicate_rows": duplicate_rows,
        "extreme_return_rows": extreme_rows,
        "extreme_amount_jump_rows": extreme_amount_jump_rows,
    }


def write_data_quality_report(
    bars: pd.DataFrame,
    output_dir: str | Path,
    *,
    selected_col: str = "selected",
    fail_on_error: bool = False,
) -> dict[str, Any]:
    """Write data quality reports and optionally raise on failed status."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = build_data_quality_report(bars, selected_col=selected_col)
    summary = dict(report["summary"])
    summary["reports"] = {}

    file_map = {
        "row_quality": "row_quality.csv",
        "data_quality_by_source": "data_quality_by_source.csv",
        "data_quality_by_date": "data_quality_by_date.csv",
        "data_quality_by_symbol": "data_quality_by_symbol.csv",
        "selected_universe_quality": "selected_universe_quality.csv",
        "missing_fields_summary": "missing_fields_summary.csv",
        "amount_vwap_unit_check": "amount_vwap_unit_check.csv",
        "limit_field_coverage": "limit_field_coverage.csv",
        "pause_st_coverage": "pause_st_coverage.csv",
        "duplicate_rows": "duplicate_rows.csv",
        "extreme_return_rows": "extreme_return_rows.csv",
        "extreme_amount_jump_rows": "extreme_amount_jump_rows.csv",
    }
    for key, filename in file_map.items():
        frame = report[key]
        path = out / filename
        assert isinstance(frame, pd.DataFrame)
        frame.to_csv(path, index=False)
        summary["reports"][key] = str(path)

    summary_path = out / "data_quality_summary.json"
    summary["reports"]["summary"] = str(summary_path)
    summary_path.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    if fail_on_error and summary.get("quality_status") == "failed":
        raise RuntimeError(f"Data quality audit failed: {summary.get('failure_reason', 'unknown')}")
    return summary


def write_qlib_quality_sidecars(
    qlib_dir: str | Path,
    bars: pd.DataFrame,
    data_quality_summary: dict[str, Any] | None = None,
    industry_quality_summary: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write audit sidecars under a Qlib metadata directory."""

    metadata_dir = Path(qlib_dir) / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    report = build_data_quality_report(bars)
    paths: dict[str, str] = {}

    row_quality = report["row_quality"]
    assert isinstance(row_quality, pd.DataFrame)
    data_quality_path = metadata_dir / "data_quality.parquet"
    try:
        row_quality.to_parquet(data_quality_path, index=False)
    except Exception:
        data_quality_path = metadata_dir / "data_quality.csv"
        row_quality.to_csv(data_quality_path, index=False)
    paths["data_quality"] = str(data_quality_path)

    source_summary = report["data_quality_by_source"]
    assert isinstance(source_summary, pd.DataFrame)
    source_path = metadata_dir / "source_summary.csv"
    source_summary.to_csv(source_path, index=False)
    paths["source_summary"] = str(source_path)

    bar_summary = data_quality_summary or dict(report["summary"])
    bar_path = metadata_dir / "bar_quality_summary.json"
    bar_path.write_text(json.dumps(_json_safe(bar_summary), ensure_ascii=False, indent=2), encoding="utf-8")
    paths["bar_quality_summary"] = str(bar_path)

    if industry_quality_summary is not None:
        industry_path = metadata_dir / "industry_coverage_summary.json"
        industry_path.write_text(json.dumps(_json_safe(industry_quality_summary), ensure_ascii=False, indent=2), encoding="utf-8")
        paths["industry_coverage_summary"] = str(industry_path)
    return paths


def _missing_bars_by_symbol(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty or "date" not in data.columns or "symbol" not in data.columns:
        return pd.DataFrame(columns=["symbol", "observed_bars", "expected_calendar_bars", "missing_bar_count"])
    calendar = sorted(pd.to_datetime(data["date"], errors="coerce").dropna().unique())
    rows = []
    for symbol, frame in data.groupby("symbol"):
        dates = set(pd.to_datetime(frame["date"], errors="coerce").dropna().unique())
        if not dates:
            rows.append({"symbol": symbol, "observed_bars": 0, "expected_calendar_bars": 0, "missing_bar_count": 0})
            continue
        start, end = min(dates), max(dates)
        expected = [date for date in calendar if start <= date <= end]
        rows.append(
            {
                "symbol": symbol,
                "observed_bars": int(len(dates)),
                "expected_calendar_bars": int(len(expected)),
                "missing_bar_count": int(max(0, len(expected) - len(dates))),
            }
        )
    return pd.DataFrame(rows)


def _failure_reason(metrics: dict[str, Any]) -> str:
    reasons = []
    for key in ["unknown_source_ratio", "selected_unknown_source_ratio", "invalid_ohlc_ratio", "invalid_amount_ratio", "invalid_limit_ratio"]:
        value = float(metrics.get(key) or 0)
        if value > 0:
            reasons.append(f"{key}={value:.6f}")
    if int(metrics.get("duplicate_rows") or 0) > 0:
        reasons.append(f"duplicate_rows={metrics['duplicate_rows']}")
    return "; ".join(reasons) if reasons else "quality gates failed"


def _is_unknown_source(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.strip().str.lower().isin(UNKNOWN_SOURCES)


def _split_flags(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).map(lambda text: {part for part in text.split(";") if part})


def _append_flag(flags: pd.Series, flag: str, mask: pd.Series | bool = True) -> pd.Series:
    if isinstance(mask, bool):
        mask = pd.Series(mask, index=flags.index)
    mask = mask.fillna(False).astype(bool)
    result = flags.copy()
    for idx in result.index[mask]:
        result.at[idx] = set(result.at[idx]) | {flag}
    return result


def _join_flags(flags: pd.Series) -> pd.Series:
    return flags.map(lambda values: ";".join(sorted(values)))


def _summary_frame(values: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame([values])


def _ratio(numerator: Any, denominator: Any) -> float:
    denominator = int(denominator or 0)
    if denominator <= 0:
        return 0.0
    return float(numerator or 0) / float(denominator)


def _date_or_empty(value: Any) -> str:
    if pd.isna(value):
        return ""
    return pd.Timestamp(value).date().isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and np.isnan(value):
        return None
    return value
