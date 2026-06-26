"""Download AKShare bars and write enriched A-share data."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.akshare_downloader import AKShareDownloader
from ashare_adapter.config import UniverseConfig
from ashare_adapter.qlib_converter import write_bars
from ashare_adapter.universe import build_dynamic_universe, build_universe_diagnostics


def main() -> None:
    args = parse_args()
    downloader = AKShareDownloader(
        metadata_cache_path=args.metadata_cache,
        refresh_metadata=args.refresh_metadata,
    )
    bars = downloader.fetch_bars(
        symbols=args.symbols,
        start_date=args.start_date,
        end_date=args.end_date,
        adjust=args.adjust,
        workers=args.workers,
        retry=args.retry,
    )
    universe_config = UniverseConfig(
        exclude_st=args.exclude_st,
        exclude_paused=args.exclude_paused,
        exclude_limit_buy=args.exclude_limit_buy,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
    )
    enriched = build_dynamic_universe(bars, universe_config)
    output = write_bars(enriched, args.output)
    print(f"Wrote enriched bars: {output}")

    if args.diagnostics_output:
        diagnostics = build_universe_diagnostics(enriched, args.dynamic_liquidity_top_n)
        diag_path = Path(args.diagnostics_output)
        diag_path.parent.mkdir(parents=True, exist_ok=True)
        diagnostics.to_csv(diag_path, index=False)
        print(f"Wrote universe diagnostics: {diag_path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", nargs="+", required=True, help="A-share symbols such as 600000.SH 000001.SZ.")
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--output", default="data/ashare_bars.parquet")
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--exclude-st", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-paused", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-limit-buy", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--diagnostics-output", default="reports/universe_diagnostics.csv")
    return parser.parse_args()


if __name__ == "__main__":
    main()
