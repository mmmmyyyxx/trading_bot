"""Incrementally update A-share bar caches with per-batch checkpoints."""

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
from ashare_adapter.metadata import normalize_symbol
from ashare_adapter.qlib_converter import read_bars, write_bars
from ashare_adapter.universe import build_dynamic_universe


def main() -> None:
    args = parse_args()
    summary = update_cache_incremental(
        symbols_file=args.symbols_file,
        output_bars=args.output_bars,
        existing_bars=args.existing_bars,
        start_date=args.start_date,
        end_date=args.end_date,
        universe_name=args.universe_name,
        metadata_cache=args.metadata_cache,
        refresh_metadata=args.refresh_metadata,
        adjust=args.adjust,
        workers=args.workers,
        retry=args.retry,
        sleep=args.sleep,
        batch_size=args.batch_size,
        max_batches=args.max_batches,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
        download_summary=args.download_summary,
        missing_symbols=args.missing_symbols,
    )
    print(f"Wrote bars: {summary['output_bars']}")
    print(f"Actual symbols: {summary['actual_symbols']} / {summary['requested_symbols']}")
    print(f"Missing symbols: {len(summary['missing_symbols'])}")


def update_cache_incremental(
    symbols_file: str | Path,
    output_bars: str | Path,
    existing_bars: str | Path | None = None,
    start_date: str = "2018-01-01",
    end_date: str = "2026-06-24",
    universe_name: str = "",
    metadata_cache: str | Path = "data/cache/akshare_metadata.parquet",
    refresh_metadata: bool = False,
    adjust: str = "qfq",
    workers: int = 4,
    retry: int = 1,
    sleep: float = 0.2,
    batch_size: int = 50,
    max_batches: int | None = None,
    min_listed_days: int = 120,
    min_amount: float = 10_000_000.0,
    liquidity_window: int = 20,
    dynamic_liquidity_top_n: int | None = None,
    download_summary: str | Path | None = None,
    missing_symbols: str | Path | None = None,
) -> dict[str, Any]:
    """Fetch missing symbols in small batches and checkpoint after each batch."""

    symbols = _read_symbols(symbols_file)
    start = pd.Timestamp(start_date)
    end = pd.Timestamp(end_date)
    output = Path(output_bars)
    existing = _read_existing(existing_bars, output_bars, symbols, start, end)
    config = UniverseConfig(
        min_listed_days=min_listed_days,
        min_amount=min_amount,
        liquidity_window=liquidity_window,
        dynamic_liquidity_top_n=dynamic_liquidity_top_n,
    )
    actual_symbols = set(existing["symbol"].dropna().astype(str).unique()) if not existing.empty else set()
    pending = sorted(set(symbols) - actual_symbols)
    batches = _chunk(pending, max(1, int(batch_size)))
    if max_batches is not None:
        batches = batches[: max(0, int(max_batches))]

    downloader = AKShareDownloader(
        metadata_cache_path=metadata_cache,
        refresh_metadata=refresh_metadata,
        load_metadata=True,
    )
    batch_records: list[dict[str, Any]] = []
    combined = existing.copy()
    for batch_index, batch_symbols in enumerate(batches, start=1):
        record: dict[str, Any] = {
            "batch_index": batch_index,
            "requested_symbols": batch_symbols,
            "requested_count": len(batch_symbols),
        }
        try:
            fetched = downloader.fetch_bars(
                symbols=batch_symbols,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
                workers=workers,
                retry=retry,
                sleep=sleep,
            )
        except Exception as exc:
            fetched = pd.DataFrame()
            record["error"] = str(exc)

        if not fetched.empty:
            combined = pd.concat([combined, fetched], ignore_index=True)
            combined = _normalize_combined(combined, start, end)
            enriched = build_dynamic_universe(combined, config)
            write_bars(enriched, output)
            combined = enriched
            record["downloaded_rows"] = int(len(fetched))
            record["downloaded_symbols"] = int(fetched["symbol"].nunique())
            record["downloaded_symbol_list"] = sorted(fetched["symbol"].dropna().astype(str).unique().tolist())
        else:
            record["downloaded_rows"] = 0
            record["downloaded_symbols"] = 0
            record["downloaded_symbol_list"] = []

        summary = _summary(
            universe_name=universe_name,
            symbols_file=symbols_file,
            output_bars=output,
            existing_bars=existing_bars,
            start=start,
            end=end,
            symbols=symbols,
            bars=combined,
            batch_records=[*batch_records, record],
            config=config,
        )
        _write_outputs(summary, download_summary, missing_symbols)
        batch_records.append(record)
        print(
            f"Batch {batch_index}/{len(batches)}: "
            f"{record['downloaded_symbols']}/{record['requested_count']} symbols, "
            f"actual {summary['actual_symbols']}/{summary['requested_symbols']}, "
            f"missing {len(summary['missing_symbols'])}",
            flush=True,
        )

    if combined.empty:
        raise RuntimeError("No bar rows available after incremental cache update.")
    final_summary = _summary(
        universe_name=universe_name,
        symbols_file=symbols_file,
        output_bars=output,
        existing_bars=existing_bars,
        start=start,
        end=end,
        symbols=symbols,
        bars=combined,
        batch_records=batch_records,
        config=config,
    )
    _write_outputs(final_summary, download_summary, missing_symbols)
    return final_summary


def _summary(
    universe_name: str,
    symbols_file: str | Path,
    output_bars: Path,
    existing_bars: str | Path | None,
    start: pd.Timestamp,
    end: pd.Timestamp,
    symbols: list[str],
    bars: pd.DataFrame,
    batch_records: list[dict[str, Any]],
    config: UniverseConfig,
) -> dict[str, Any]:
    actual = sorted(bars["symbol"].dropna().astype(str).unique().tolist()) if not bars.empty else []
    missing = sorted(set(symbols) - set(actual))
    return {
        "universe_name": universe_name,
        "symbols_file": str(symbols_file),
        "output_bars": str(output_bars),
        "existing_bars": str(existing_bars) if existing_bars else None,
        "start_date": start.strftime("%Y-%m-%d"),
        "end_date": end.strftime("%Y-%m-%d"),
        "requested_symbols": len(symbols),
        "actual_symbols": len(actual),
        "missing_symbols": missing,
        "rows": int(len(bars)),
        "data_start": str(pd.to_datetime(bars["date"]).min().date()) if not bars.empty else None,
        "data_end": str(pd.to_datetime(bars["date"]).max().date()) if not bars.empty else None,
        "data_sources": _value_counts(bars, "data_source"),
        "amount_estimated_rows": _bool_column_sum(bars, "amount_estimated"),
        "batch_records": batch_records,
        "universe": {
            "min_listed_days": config.min_listed_days,
            "min_amount": config.min_amount,
            "liquidity_window": config.liquidity_window,
            "dynamic_liquidity_top_n": config.dynamic_liquidity_top_n,
            "selected_mode": f"dynamic_liquidity_top{config.dynamic_liquidity_top_n}"
            if config.dynamic_liquidity_top_n
            else "eligible_only",
        },
        "caveats": [
            "Current universe symbols are used historically unless historical membership data is supplied.",
            "Incremental updates checkpoint after each batch; inspect batch_records for partial failures.",
        ],
    }


def _write_outputs(
    summary: dict[str, Any],
    download_summary: str | Path | None,
    missing_symbols: str | Path | None,
) -> None:
    if download_summary:
        target = Path(download_summary)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    if missing_symbols:
        target = Path(missing_symbols)
        target.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame({"symbol": summary["missing_symbols"], "reason": "no_bars_after_incremental_update"}).to_csv(
            target, index=False
        )


def _read_existing(
    existing_bars: str | Path | None,
    output_bars: str | Path,
    symbols: list[str],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    for candidate in [existing_bars, output_bars]:
        if candidate and Path(candidate).exists():
            return _slice_existing(read_bars(candidate), symbols, start, end)
    return pd.DataFrame()


def _slice_existing(existing: pd.DataFrame, symbols: list[str], start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if existing.empty:
        return existing
    data = existing.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    return data[(data["symbol"].isin(set(symbols))) & (data["date"] >= start) & (data["date"] <= end)].copy()


def _normalize_combined(data: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    combined = data.copy()
    combined["date"] = pd.to_datetime(combined["date"])
    combined["symbol"] = combined["symbol"].map(normalize_symbol)
    combined = combined[(combined["date"] >= start) & (combined["date"] <= end)]
    return combined.drop_duplicates(["date", "symbol"], keep="last")


def _value_counts(frame: pd.DataFrame, column: str) -> dict[str, int]:
    if frame.empty or column not in frame.columns:
        return {}
    return {
        str(key): int(value)
        for key, value in frame[column].fillna("unknown").astype(str).value_counts().sort_index().items()
    }


def _bool_column_sum(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].astype("boolean").fillna(False).astype(bool).sum())


def _read_symbols(path: str | Path) -> list[str]:
    values = [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    return [normalize_symbol(symbol) for symbol in values]


def _chunk(values: list[str], size: int) -> list[list[str]]:
    return [values[index : index + size] for index in range(0, len(values), size)]


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
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry", type=int, default=1)
    parser.add_argument("--sleep", type=float, default=0.2)
    parser.add_argument("--batch-size", type=int, default=50)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--download-summary", default=None)
    parser.add_argument("--missing-symbols", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
