"""Update reusable A-share bar caches for 2018-2026 experiments."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.akshare_downloader import AKShareDownloader
from ashare_adapter.config import UniverseConfig
from ashare_adapter.data_quality import normalize_bar_audit_fields
from ashare_adapter.metadata import normalize_symbol
from ashare_adapter.qlib_converter import read_bars, write_bars
from ashare_adapter.universe import build_dynamic_universe


def main() -> None:
    args = parse_args()
    summary = update_cache(
        symbols_file=args.symbols_file,
        output_bars=args.output_bars,
        existing_bars=args.existing_bars,
        start_date=args.start_date,
        end_date=args.end_date,
        universe_name=args.universe_name,
        metadata_cache=args.metadata_cache,
        refresh_metadata=args.refresh_metadata,
        refresh_bars=args.refresh_bars,
        adjust=args.adjust,
        workers=args.workers,
        retry=args.retry,
        sleep=args.sleep,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
        download_summary=args.download_summary,
        missing_symbols=args.missing_symbols,
        download_source_summary=args.download_source_summary,
        download_failure_summary=args.download_failure_summary,
        source_fallback_summary=args.source_fallback_summary,
    )
    print(f"Wrote bars: {summary['output_bars']}")
    print(f"Actual symbols: {summary['actual_symbols']} / {summary['requested_symbols']}")
    print(f"Missing symbols: {len(summary['missing_symbols'])}")


def update_cache(
    symbols_file: str | Path,
    output_bars: str | Path,
    existing_bars: str | Path | None = None,
    start_date: str = "2018-01-01",
    end_date: str = "2026-06-24",
    universe_name: str = "",
    metadata_cache: str | Path = "data/cache/akshare_metadata.parquet",
    refresh_metadata: bool = False,
    refresh_bars: bool = False,
    adjust: str = "qfq",
    workers: int = 8,
    retry: int = 2,
    sleep: float = 0.05,
    min_listed_days: int = 120,
    min_amount: float = 10_000_000.0,
    liquidity_window: int = 20,
    dynamic_liquidity_top_n: int | None = None,
    download_summary: str | Path | None = None,
    missing_symbols: str | Path | None = None,
    download_source_summary: str | Path | None = None,
    download_failure_summary: str | Path | None = None,
    source_fallback_summary: str | Path | None = None,
) -> dict[str, Any]:
    """Update a bar cache by reusing existing rows and fetching missing ranges."""

    symbols = _read_symbols(symbols_file)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    output = Path(output_bars)
    existing_candidates = [Path(path) for path in [existing_bars, output_bars] if path]

    existing = pd.DataFrame()
    if not refresh_bars:
        for candidate in existing_candidates:
            if candidate.exists():
                existing = read_bars(candidate)
                break
    existing = _slice_existing(existing, symbols, start, end)

    fetch_jobs = _missing_fetch_jobs(existing, symbols, start, end)
    fetched_frames = []
    downloader = None
    fetch_attempts: list[dict[str, Any]] = []
    for job in fetch_jobs:
        if not job["symbols"]:
            continue
        if downloader is None:
            downloader = AKShareDownloader(
                metadata_cache_path=metadata_cache,
                refresh_metadata=refresh_metadata,
                load_metadata=True,
            )
        try:
            fetched = downloader.fetch_bars(
                symbols=job["symbols"],
                start_date=job["start"],
                end_date=job["end"],
                adjust=adjust,
                workers=workers,
                retry=retry,
                sleep=sleep,
            )
        except Exception as exc:
            fetched = pd.DataFrame()
            job["error"] = str(exc)
        if not fetched.empty:
            fetched_frames.append(fetched)
            job["downloaded_rows"] = int(len(fetched))
            job["downloaded_symbols"] = int(fetched["symbol"].nunique())
        else:
            job["downloaded_rows"] = 0
            job["downloaded_symbols"] = 0
        if downloader is not None:
            fetch_attempts.extend(getattr(downloader, "fetch_attempts", []))
            downloader.fetch_attempts = []

    available_frames = [frame for frame in [existing, *fetched_frames] if not frame.empty]
    if not available_frames:
        raise RuntimeError("No bar rows available after cache update.")
    combined = pd.concat(available_frames, ignore_index=True)
    if combined.empty:
        raise RuntimeError("No bar rows available after cache update.")
    combined = normalize_bar_audit_fields(combined, price_adjust=adjust)
    combined = _fill_missing_industry_source(combined)
    combined = combined.drop_duplicates(["date", "symbol"], keep="last")
    combined = combined[(combined["date"] >= start) & (combined["date"] <= end)]

    universe_config = UniverseConfig(
        min_listed_days=min_listed_days,
        min_amount=min_amount,
        liquidity_window=liquidity_window,
        dynamic_liquidity_top_n=dynamic_liquidity_top_n,
    )
    enriched = build_dynamic_universe(combined, universe_config)
    written = write_bars(enriched, output)
    actual_symbols = sorted(enriched["symbol"].dropna().astype(str).unique().tolist())
    missing = sorted(set(symbols) - set(actual_symbols))

    summary = {
        "universe_name": universe_name,
        "symbols_file": str(symbols_file),
        "output_bars": str(written),
        "existing_bars": str(existing_bars) if existing_bars else None,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "requested_symbols": len(symbols),
        "actual_symbols": len(actual_symbols),
        "missing_symbols": missing,
        "rows": int(len(enriched)),
        "data_start": str(pd.to_datetime(enriched["date"]).min().date()),
        "data_end": str(pd.to_datetime(enriched["date"]).max().date()),
        "fetch_jobs": fetch_jobs,
        "fetch_attempts": fetch_attempts,
        "universe": {
            "min_listed_days": min_listed_days,
            "min_amount": min_amount,
            "liquidity_window": liquidity_window,
            "dynamic_liquidity_top_n": dynamic_liquidity_top_n,
            "selected_mode": f"dynamic_liquidity_top{dynamic_liquidity_top_n}" if dynamic_liquidity_top_n else "eligible_only",
        },
        "caveats": [
            "Current universe symbols are used historically unless historical membership data is supplied.",
            "Missing or failed symbols are recorded and do not stop the pipeline when usable data remains.",
        ],
        "data_type": "real_akshare",
        "synthetic_data": False,
        "mock_data": False,
        "download_source": "akshare",
    }
    if download_summary:
        target = Path(download_summary)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        base_dir = target.parent
        download_source_summary = download_source_summary or base_dir / "download_source_summary.csv"
        download_failure_summary = download_failure_summary or base_dir / "download_failure_summary.csv"
        source_fallback_summary = source_fallback_summary or base_dir / "source_fallback_summary.csv"
    if missing_symbols:
        target = Path(missing_symbols)
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"symbol": missing, "reason": "no_bars_after_update"}).to_csv(target, index=False)
    if download_source_summary:
        _write_download_source_summary(enriched, Path(download_source_summary))
    if download_failure_summary:
        _write_download_failure_summary(fetch_attempts, missing, Path(download_failure_summary))
    if source_fallback_summary:
        _write_source_fallback_summary(fetch_attempts, Path(source_fallback_summary))
    return summary


def _read_symbols(path: str | Path) -> list[str]:
    values = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return [normalize_symbol(symbol) for symbol in values]


def _slice_existing(existing: pd.DataFrame, symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if existing.empty:
        return existing
    data = existing.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    symbol_set = set(symbols)
    return data[(data["symbol"].isin(symbol_set)) & (data["date"] >= start) & (data["date"] <= end)].copy()


def _missing_fetch_jobs(
    existing: pd.DataFrame,
    symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list[dict[str, Any]]:
    if existing.empty:
        return [{"symbols": symbols, "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "reason": "empty_cache"}]

    jobs: list[dict[str, Any]] = []
    actual_symbols = set(existing["symbol"].dropna().astype(str).unique())
    missing_symbols = sorted(set(symbols) - actual_symbols)
    if missing_symbols:
        jobs.append(
            {
                "symbols": missing_symbols,
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
                "reason": "missing_symbols",
            }
        )

    max_date = pd.to_datetime(existing["date"]).max()
    if pd.notna(max_date) and max_date < end:
        next_date = (pd.Timestamp(max_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        jobs.append({"symbols": symbols, "start": next_date, "end": end.strftime("%Y-%m-%d"), "reason": "extend_end_date"})
    return jobs


def _write_download_source_summary(bars: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = bars.copy()
    if data.empty:
        pd.DataFrame(columns=["data_source", "rows", "symbols", "selected_rows", "amount_estimated_rows", "row_ratio"]).to_csv(path, index=False)
        return
    if "data_source" not in data.columns:
        data["data_source"] = "legacy_unknown"
    if "amount_estimated" not in data.columns:
        data["amount_estimated"] = False
    if "selected" not in data.columns:
        data["selected"] = False
    data["data_source"] = data["data_source"].fillna("legacy_unknown").astype(str)
    summary = data.groupby("data_source", dropna=False).agg(
        rows=("symbol", "count"),
        symbols=("symbol", "nunique"),
        selected_rows=("selected", "sum"),
        amount_estimated_rows=("amount_estimated", "sum"),
    ).reset_index()
    summary["row_ratio"] = summary["rows"] / len(data)
    summary.to_csv(path, index=False)


def _fill_missing_industry_source(bars: pd.DataFrame) -> pd.DataFrame:
    data = bars.copy()
    if "industry" not in data.columns:
        return data
    if "industry_source" not in data.columns:
        data["industry_source"] = ""
    has_industry = data["industry"].fillna("").astype(str).str.strip().ne("")
    missing_source = data["industry_source"].fillna("").astype(str).str.strip().eq("")
    data.loc[has_industry & missing_source, "industry_source"] = "akshare_metadata_cache"
    if "industry_update_date" not in data.columns:
        data["industry_update_date"] = pd.NaT
    return data


def _write_download_failure_summary(fetch_attempts: list[dict[str, Any]], missing: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = pd.DataFrame(fetch_attempts)
    if attempts.empty:
        attempts = pd.DataFrame(columns=["symbol", "source", "attempt_order", "status", "rows", "fallback_used", "error"])
    failures = attempts[attempts["status"].astype(str).isin(["failed", "empty"])].copy() if "status" in attempts.columns else attempts
    missing_rows = pd.DataFrame({"symbol": missing, "source": "", "attempt_order": pd.NA, "status": "missing_after_update", "rows": 0, "fallback_used": False, "error": "no_bars_after_update"})
    pd.concat([failures, missing_rows], ignore_index=True).to_csv(path, index=False)


def _write_source_fallback_summary(fetch_attempts: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    attempts = pd.DataFrame(fetch_attempts)
    if attempts.empty:
        pd.DataFrame(
            columns=[
                "symbol",
                "successful_source",
                "successful_attempt_order",
                "fallback_used",
                "attempted_sources",
                "failed_sources",
                "errors",
            ]
        ).to_csv(path, index=False)
        return
    rows = []
    for symbol, frame in attempts.groupby("symbol", dropna=False):
        frame = frame.sort_values("attempt_order")
        successes = frame[frame["status"].astype(str).eq("success")]
        first_success = successes.iloc[0] if not successes.empty else None
        failed = frame[frame["status"].astype(str).isin(["failed", "empty"])]
        rows.append(
            {
                "symbol": symbol,
                "successful_source": "" if first_success is None else first_success.get("source", ""),
                "successful_attempt_order": None if first_success is None else first_success.get("attempt_order"),
                "fallback_used": bool(False if first_success is None else first_success.get("fallback_used", False)),
                "attempted_sources": ";".join(frame["source"].fillna("").astype(str).tolist()) if "source" in frame else "",
                "failed_sources": ";".join(failed["source"].fillna("").astype(str).tolist()) if "source" in failed else "",
                "errors": "; ".join(failed["error"].fillna("").astype(str).tolist()) if "error" in failed else "",
            }
        )
    pd.DataFrame(rows).to_csv(path, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols-file", required=True)
    parser.add_argument("--output-bars", required=True)
    parser.add_argument("--existing-bars", default=None)
    parser.add_argument("--universe-name", default="")
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default="2026-06-24")
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-bars", action="store_true")
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--download-summary", default=None)
    parser.add_argument("--missing-symbols", default=None)
    parser.add_argument("--download-source-summary", default=None)
    parser.add_argument("--download-failure-summary", default=None)
    parser.add_argument("--source-fallback-summary", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
