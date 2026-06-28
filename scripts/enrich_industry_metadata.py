"""Enrich A-share industry metadata cache, bars, and Qlib sidecars."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.industry_metadata import (
    fetch_cninfo_industry_map,
    fetch_eastmoney_industry_map,
    industry_coverage,
    industry_quality_status,
    industry_unknown_by_date,
    industry_unknown_by_position,
    merge_industry_map,
    missing_industry_symbols,
    update_bars_industry,
)
from ashare_adapter.metadata import normalize_metadata_frame, normalize_symbol, write_metadata_sidecar


def main() -> None:
    args = parse_args()
    if os.environ.get("ASHARE_USE_SYSTEM_PROXY", "").strip() not in {"1", "true", "TRUE", "yes"}:
        os.environ.setdefault("NO_PROXY", "*")
        os.environ.setdefault("no_proxy", "*")

    metadata_path = Path(args.metadata_cache)
    metadata = _read_table(metadata_path) if metadata_path.exists() else pd.DataFrame(columns=["symbol", "name", "is_st", "industry", "list_date"])
    metadata = _prepare_metadata(metadata)
    target_symbols = _target_symbols(args, metadata)
    report_rows = [_coverage_row("metadata_cache", str(metadata_path), "before", metadata)]

    industry_maps: list[pd.DataFrame] = []
    failures = pd.DataFrame(columns=["symbol", "reason"])
    enabled_sources = _parse_sources(args.sources)
    args.refresh_eastmoney = bool(args.refresh_eastmoney or "eastmoney" in enabled_sources)
    args.refresh_cninfo = bool(args.refresh_cninfo or "cninfo" in enabled_sources)
    args.overwrite_industry = bool(args.overwrite_industry or args.overwrite)

    if args.refresh_eastmoney or args.refresh_cninfo:
        import akshare as ak  # type: ignore

        if args.refresh_eastmoney:
            try:
                eastmoney_map = fetch_eastmoney_industry_map(ak, sleep=args.sleep)
                industry_maps.append(eastmoney_map)
                _write_source_cache(eastmoney_map, Path(args.industry_cache_dir) / "eastmoney_industry_map.parquet")
            except Exception as exc:  # pragma: no cover - network/API dependent
                failures = pd.concat(
                    [failures, pd.DataFrame([{"symbol": "*", "reason": f"eastmoney_failed: {exc}"}])],
                    ignore_index=True,
                )
        if args.refresh_cninfo:
            missing = missing_industry_symbols(metadata, target_symbols)
            if args.max_fetch_symbols is not None:
                missing = missing[: args.max_fetch_symbols]
            cninfo_map, cninfo_failures = fetch_cninfo_industry_map(
                ak,
                missing,
                start_date=args.cninfo_start_date,
                end_date=args.cninfo_end_date,
                workers=args.max_workers,
                retry=args.retry,
                sleep=args.sleep,
            )
            industry_maps.append(cninfo_map)
            _write_source_cache(cninfo_map, Path(args.industry_cache_dir) / "cninfo_industry_map.parquet")
            failures = pd.concat([failures, cninfo_failures], ignore_index=True)

    industry_map = _combine_industry_maps(industry_maps)
    if not industry_map.empty:
        metadata = merge_industry_map(metadata, industry_map, overwrite=args.overwrite_industry)
    metadata = _prepare_metadata(metadata)
    _write_table(metadata, metadata_path)
    report_rows.append(_coverage_row("metadata_cache", str(metadata_path), "after", metadata))

    unknown_by_date_frames = []
    unknown_by_position_frames = []
    for bars_path in args.bars:
        before, after = update_bars_industry(bars_path, _industry_metadata_map(metadata), overwrite=args.overwrite_industry)
        report_rows.append({"dataset": "bars", "path": bars_path, "stage": "before", **before})
        report_rows.append({"dataset": "bars", "path": bars_path, "stage": "after", **after})
        bars_frame = _read_table(Path(bars_path))
        unknown_by_date_frames.append(industry_unknown_by_date(bars_frame).assign(path=bars_path))

        report_dir = _infer_report_dir_from_bars(bars_path)
        positions_path = report_dir / "qlib_records" / "positions.csv" if report_dir is not None else None
        if positions_path is not None and positions_path.exists():
            positions = pd.read_csv(positions_path)
            unknown_by_position_frames.append(industry_unknown_by_position(positions, bars_frame).assign(path=bars_path))

    for qlib_dir in args.qlib_dir:
        before, after = _update_qlib_sidecar(Path(qlib_dir), metadata, overwrite=args.overwrite_industry)
        report_rows.append({"dataset": "qlib_metadata", "path": str(Path(qlib_dir) / "metadata"), "stage": "before", **before})
        report_rows.append({"dataset": "qlib_metadata", "path": str(Path(qlib_dir) / "metadata"), "stage": "after", **after})

    report = pd.DataFrame(report_rows)
    report_path = Path(args.output_coverage or args.output_report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report.to_csv(report_path, index=False)

    failure_path = Path(args.failure_report)
    failure_path.parent.mkdir(parents=True, exist_ok=True)
    failures.to_csv(failure_path, index=False)

    unknown_by_date_path = Path(args.unknown_by_date_report)
    unknown_by_date_path.parent.mkdir(parents=True, exist_ok=True)
    _concat_or_empty(unknown_by_date_frames).to_csv(unknown_by_date_path, index=False)

    unknown_by_position_path = Path(args.unknown_by_position_report)
    unknown_by_position_path.parent.mkdir(parents=True, exist_ok=True)
    _concat_or_empty(unknown_by_position_frames).to_csv(unknown_by_position_path, index=False)

    summary = {
        "metadata_cache": str(metadata_path),
        "target_symbols": len(target_symbols),
        "fetched_industry_rows": int(len(industry_map)),
        "failures": int(len(failures)),
        "coverage_report": str(report_path),
        "failure_report": str(failure_path),
        "unknown_by_date_report": str(unknown_by_date_path),
        "unknown_by_position_report": str(unknown_by_position_path),
        "overwrite_industry": bool(args.overwrite_industry),
    }
    quality_summary = _coverage_quality_summary(metadata, report, args)
    summary.update(quality_summary)
    summary_path = Path(args.output_summary)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fail_on_low_coverage and summary.get("quality_status") == "failed":
        raise RuntimeError(
            "Industry metadata coverage failed: "
            f"symbol_level_coverage={summary.get('symbol_level_coverage')}, "
            f"selected_universe_coverage={summary.get('selected_universe_coverage')}, "
            f"unknown_position_weight_avg={summary.get('unknown_position_weight_avg')}"
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--symbols-file", action="append", default=[])
    parser.add_argument("--bars", nargs="*", default=[])
    parser.add_argument("--qlib-dir", action="append", default=[])
    parser.add_argument("--sources", default="")
    parser.add_argument("--refresh-eastmoney", action="store_true")
    parser.add_argument("--refresh-cninfo", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--overwrite-industry", action="store_true")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-workers", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=200)
    parser.add_argument("--retry", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.02)
    parser.add_argument("--max-fetch-symbols", type=int, default=None)
    parser.add_argument("--cninfo-start-date", default="19900101")
    parser.add_argument("--cninfo-end-date", default="20260627")
    parser.add_argument("--industry-cache-dir", default="data/cache/industry")
    parser.add_argument("--output-coverage", default=None)
    parser.add_argument("--output-report", default="reports/industry_metadata_coverage.csv")
    parser.add_argument("--failure-report", default="reports/industry_metadata_failures.csv")
    parser.add_argument("--unknown-by-date-report", default="reports/industry_unknown_by_date.csv")
    parser.add_argument("--unknown-by-position-report", default="reports/industry_unknown_by_position.csv")
    parser.add_argument("--output-summary", default="reports/industry_metadata_summary.json")
    parser.add_argument("--fail-on-low-coverage", action="store_true")
    parser.add_argument("--min-symbol-coverage", type=float, default=0.95)
    parser.add_argument("--min-selected-coverage", type=float, default=0.95)
    parser.add_argument("--max-position-unknown", type=float, default=0.10)
    args = parser.parse_args()
    if args.max_workers is None:
        args.max_workers = args.workers
    else:
        args.workers = args.max_workers
    return args


def _target_symbols(args: argparse.Namespace, metadata: pd.DataFrame) -> list[str]:
    has_explicit_targets = bool(args.symbols_file or args.bars)
    symbols = set() if has_explicit_targets else (set(metadata["symbol"].dropna().map(normalize_symbol)) if "symbol" in metadata.columns else set())
    for path in args.symbols_file:
        symbols.update(
            normalize_symbol(line.strip())
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        )
    for path in args.bars:
        bars = pd.read_parquet(path, columns=["symbol"]) if str(path).lower().endswith((".parquet", ".pq")) else pd.read_csv(path, usecols=["symbol"])
        symbols.update(bars["symbol"].dropna().map(normalize_symbol).unique())
    return sorted(symbols)


def _combine_industry_maps(frames: list[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    if not valid:
        return pd.DataFrame(columns=["symbol", "industry", "industry_source"])
    data = pd.concat(valid, ignore_index=True)
    data["symbol"] = data["symbol"].map(normalize_symbol)
    return data.drop_duplicates("symbol", keep="last")


def _parse_sources(value: str) -> set[str]:
    if not value:
        return set()
    aliases = {"existing": "existing", "akshare": "akshare", "eastmoney": "eastmoney", "cninfo": "cninfo"}
    result = set()
    for item in value.split(","):
        key = item.strip().lower()
        if not key:
            continue
        if key not in aliases:
            raise ValueError(f"Unsupported industry source: {item}")
        result.add(aliases[key])
    return result


def _write_source_cache(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if frame is None or frame.empty:
        pd.DataFrame(columns=["symbol", "industry", "industry_source"]).to_parquet(path, index=False)
        return
    frame.to_parquet(path, index=False)


def _coverage_quality_summary(metadata: pd.DataFrame, report: pd.DataFrame, args: argparse.Namespace) -> dict[str, object]:
    coverage = industry_coverage(metadata)
    symbol_coverage = float(coverage.get("industry_coverage") or 0.0)
    bars_after = report[(report.get("dataset") == "bars") & (report.get("stage") == "after")] if not report.empty else pd.DataFrame()
    selected_coverage = symbol_coverage
    if not bars_after.empty and "industry_coverage" in bars_after.columns:
        selected_coverage = float(pd.to_numeric(bars_after["industry_coverage"], errors="coerce").fillna(0.0).min())
    unknown_position = 0.0
    status = industry_quality_status(
        {
            "symbol_level_coverage": symbol_coverage,
            "selected_universe_coverage": selected_coverage,
            "unknown_position_weight_avg": unknown_position,
        }
    )
    if (
        symbol_coverage < float(args.min_symbol_coverage)
        or selected_coverage < float(args.min_selected_coverage)
        or unknown_position > float(args.max_position_unknown)
    ):
        status = "failed"
    source_dist = (
        metadata.get("industry_source", pd.Series(dtype=str)).fillna("unknown").astype(str).value_counts().to_dict()
        if not metadata.empty
        else {}
    )
    return {
        "symbol_level_coverage": symbol_coverage,
        "selected_universe_coverage": selected_coverage,
        "unknown_position_weight_avg": unknown_position,
        "industry_source_distribution": source_dist,
        "quality_status": status,
    }


def _prepare_metadata(metadata: pd.DataFrame) -> pd.DataFrame:
    data = normalize_metadata_frame(metadata)
    has_industry = data["industry"].fillna("").astype(str).str.strip().ne("")
    missing_source = data["industry_source"].fillna("").astype(str).str.strip().eq("")
    data.loc[has_industry & missing_source, "industry_source"] = "akshare_metadata_cache"
    return data


def _update_qlib_sidecar(qlib_dir: Path, metadata: pd.DataFrame, overwrite: bool) -> tuple[dict[str, object], dict[str, object]]:
    sidecar = qlib_dir / "metadata" / "instruments.parquet"
    if not sidecar.exists():
        sidecar = qlib_dir / "metadata" / "instruments.csv"
    if sidecar.exists():
        current = _read_table(sidecar)
    else:
        current = metadata.copy()
    before = industry_coverage(current)
    updated = merge_industry_map(current, _industry_metadata_map(metadata), overwrite=overwrite)
    after = industry_coverage(updated)
    write_metadata_sidecar(updated, qlib_dir / "metadata")
    return before, after


def _industry_metadata_map(metadata: pd.DataFrame) -> pd.DataFrame:
    columns = [column for column in ["symbol", "industry", "industry_source", "industry_update_date"] if column in metadata.columns]
    return metadata[columns].copy()


def _infer_report_dir_from_bars(bars_path: str) -> Path | None:
    stem = Path(bars_path).stem
    suffix = "_bars"
    if not stem.endswith(suffix):
        return None
    name = stem[: -len(suffix)]
    candidates = [
        Path("reports") / f"alpha158_{name}",
        Path("reports") / name,
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _concat_or_empty(frames: list[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()


def _coverage_row(dataset: str, path: str, stage: str, frame: pd.DataFrame) -> dict[str, object]:
    return {"dataset": dataset, "path": path, "stage": stage, **industry_coverage(frame)}


def _read_table(path: Path) -> pd.DataFrame:
    if path.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    return pd.read_csv(path)


def _write_table(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in {".parquet", ".pq"}:
        frame.to_parquet(path, index=False)
    else:
        frame.to_csv(path, index=False)


if __name__ == "__main__":
    main()
