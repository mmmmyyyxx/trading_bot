"""Incrementally backfill missing historical bars and persist each chunk."""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ashare_quant.config import load_config
from ashare_quant.data.storage import SQLiteStorage
from ashare_quant.logger import setup_logging
from ashare_quant.pipeline import _load_candidate_symbols_file


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--batch-size", type=int, default=25)
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--workers", type=int, default=None)
    parser.add_argument("--symbol-timeout", type=float, default=90.0)
    parser.add_argument("--progress-file", default="data/cache/history_backfill_progress.json")
    parser.add_argument("--failures-file", default="data/cache/history_backfill_failures.json")
    args = parser.parse_args()

    config = load_config(args.config, args.overrides)
    config.data.download_batch_size = args.batch_size
    if args.workers is not None:
        config.data.download_workers = args.workers
    setup_logging(config.logging.level)

    storage = SQLiteStorage(config.data.cache_path)
    existing = _load_existing_cache(storage, config.data.start_date, config.data.end_date)
    symbols = _resolve_symbols(storage, config)
    if not symbols:
        raise SystemExit("No candidate symbols available for backfill.")

    existing_symbols = set(existing["symbol"].astype(str).unique()) if not existing.empty and "symbol" in existing.columns else set()
    missing_symbols = [symbol for symbol in symbols if symbol not in existing_symbols]
    present_symbols = [symbol for symbol in symbols if symbol in existing_symbols]
    ranges = _missing_ranges(existing, config.data.start_date, config.data.end_date)
    progress_path = Path(args.progress_file)
    failures_path = Path(args.failures_file)
    done = _load_progress(progress_path)

    worker_count = max(1, int(config.data.download_workers or 1))
    chunk_size = args.chunk_size or max(args.batch_size, args.batch_size * worker_count)
    fetch_plan: list[tuple[str, str, list[str]]] = []
    if missing_symbols:
        fetch_plan.extend(
            ("symbols", f"{start}:{end}", chunk)
            for start, end, chunk in _chunked_plan(missing_symbols, chunk_size, config.data.start_date, config.data.end_date)
        )
    if ranges and present_symbols:
        for start_date, end_date in ranges:
            fetch_plan.extend(
                ("dates", f"{start_date}:{end_date}", chunk)
                for _, _, chunk in _chunked_plan(present_symbols, chunk_size, start_date, end_date)
            )

    for kind, range_key, batch in fetch_plan:
        key = f"{kind}:{range_key}:{batch[0]}:{batch[-1]}"
        if key in done:
            continue
        start_date, end_date = range_key.split(":", 1)
        fetched, failures = _fetch_symbols_in_processes(
            provider_name=config.data.provider,
            prefer_eastmoney=bool(config.data.prefer_eastmoney),
            symbols=batch,
            start_date=start_date,
            end_date=end_date,
            adjust=config.data.adjust,
            workers=worker_count,
            symbol_timeout=args.symbol_timeout,
        )
        if failures:
            _append_failures(failures_path, key, failures)

        if fetched.empty:
            print(f"batch_failed={key} reason=no_usable_symbol_frames failures={len(failures)}")
            continue

        storage.upsert_bars(fetched)
        fetched_symbols = set(fetched["symbol"].astype(str).unique())
        if fetched_symbols.issuperset(set(batch)):
            done.add(key)
        _save_progress(progress_path, done)
        stats = storage.bar_stats()
        print(f"saved_batch={key} fetched_rows={len(fetched)} failures={len(failures)} total_rows={stats['rows']}")

    final = storage.load_bars(start_date=config.data.start_date, end_date=config.data.end_date)
    print(
        "final="
        + json.dumps(
            {
                "rows": int(len(final)),
                "symbols": int(final["symbol"].nunique()),
                "start": str(final["date"].min().date()) if not final.empty else None,
                "end": str(final["date"].max().date()) if not final.empty else None,
            },
            ensure_ascii=False,
        )
    )


def _load_existing_cache(storage: SQLiteStorage, start_date: str, end_date: str) -> pd.DataFrame:
    try:
        return storage.load_bars(start_date=start_date, end_date=end_date)
    except Exception:
        return pd.DataFrame()


def _resolve_symbols(storage: SQLiteStorage, config) -> list[str]:
    symbols = _load_candidate_symbols_file(Path(config.data.candidate_symbols_path), config)
    if symbols:
        return symbols[: config.data.max_symbols]
    try:
        cached = storage.load_bars(start_date=config.data.start_date, end_date=config.data.end_date)
    except Exception:
        return []
    if cached.empty or "symbol" not in cached.columns:
        return []
    return sorted(cached["symbol"].astype(str).unique())[: config.data.max_symbols]


def _missing_ranges(existing: pd.DataFrame, start_date: str, end_date: str) -> list[tuple[str, str]]:
    if existing.empty:
        return [(start_date, end_date)]
    dates = pd.to_datetime(existing["date"])
    requested_start = pd.Timestamp(start_date)
    requested_end = pd.Timestamp(end_date)
    cached_start = dates.min()
    cached_end = dates.max()
    ranges: list[tuple[str, str]] = []
    if requested_start < cached_start and (cached_start - requested_start).days > 7:
        ranges.append((requested_start.strftime("%Y-%m-%d"), (cached_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")))
    if requested_end > cached_end and (requested_end - cached_end).days > 7:
        ranges.append(((cached_end + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), requested_end.strftime("%Y-%m-%d")))
    return ranges


def _chunked_plan(symbols: list[str], chunk_size: int, start_date: str, end_date: str) -> list[tuple[str, str, list[str]]]:
    chunks: list[tuple[str, str, list[str]]] = []
    effective_chunk = max(1, int(chunk_size))
    for start in range(0, len(symbols), effective_chunk):
        chunk = symbols[start : start + effective_chunk]
        if chunk:
            chunks.append((start_date, end_date, chunk))
    return chunks


def _fetch_symbols_in_processes(
    provider_name: str,
    prefer_eastmoney: bool,
    symbols: list[str],
    start_date: str,
    end_date: str,
    adjust: str,
    workers: int,
    symbol_timeout: float,
) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    if not symbols:
        return pd.DataFrame(), []
    frames: list[pd.DataFrame] = []
    failures: list[dict[str, object]] = []
    max_workers = min(max(1, workers), len(symbols))
    with TemporaryDirectory(prefix="ashare_symbol_fetch_") as temp_dir:
        output_dir = Path(temp_dir)
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_symbol = {
                executor.submit(
                    _run_symbol_fetch_subprocess,
                    provider_name,
                    prefer_eastmoney,
                    symbol,
                    start_date,
                    end_date,
                    adjust,
                    output_dir / f"{symbol.replace('.', '_')}.parquet",
                    symbol_timeout,
                ): symbol
                for symbol in symbols
            }
            for future in concurrent.futures.as_completed(future_to_symbol):
                symbol = future_to_symbol[future]
                try:
                    output_path = future.result()
                except subprocess.TimeoutExpired:
                    failures.append({"symbol": symbol, "status": "symbol_timeout", "reason": f">{symbol_timeout}s"})
                    continue
                except Exception as exc:
                    failures.append({"symbol": symbol, "status": "error", "reason": str(exc)})
                    continue
                frame = pd.read_parquet(output_path, engine="pyarrow")
                if frame.empty:
                    failures.append({"symbol": symbol, "status": "empty", "reason": ""})
                    continue
                frames.append(frame)
                print(f"symbol_done={symbol} rows={len(frame)}")
    if not frames:
        return pd.DataFrame(), failures
    return pd.concat(frames, ignore_index=True), failures


def _run_symbol_fetch_subprocess(
    provider_name: str,
    prefer_eastmoney: bool,
    symbol: str,
    start_date: str,
    end_date: str,
    adjust: str,
    output_path: Path,
    timeout: float,
) -> Path:
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "scripts" / "fetch_one_symbol.py"),
        "--provider",
        provider_name,
        "--symbol",
        symbol,
        "--start-date",
        start_date,
        "--end-date",
        end_date,
        "--adjust",
        adjust,
        "--output",
        str(output_path),
    ]
    if prefer_eastmoney:
        cmd.append("--prefer-eastmoney")
    completed = subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(stderr or f"fetch_one_symbol exited with {completed.returncode}")
    if not output_path.exists():
        raise RuntimeError("fetch subprocess did not write an output file")
    return output_path


def _load_progress(path: Path) -> set[str]:
    if not path.exists():
        return set()
    try:
        return set(json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def _save_progress(path: Path, done: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(done), ensure_ascii=False, indent=2), encoding="utf-8")


def _append_failures(path: Path, batch_key: str, failures: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, object]]
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    else:
        existing = []
    for failure in failures:
        existing.append({"batch": batch_key, **failure})
    path.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
