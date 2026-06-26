"""Dump enriched A-share bars to Qlib CSV and binary format."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.config import UniverseConfig
from ashare_adapter.qlib_converter import dump_qlib_bin, dump_qlib_csv, read_bars


def main() -> None:
    args = parse_args()
    bars = read_bars(args.input)
    universe_config = UniverseConfig(
        exclude_st=args.exclude_st,
        exclude_paused=args.exclude_paused,
        exclude_limit_buy=args.exclude_limit_buy,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
    )
    if args.csv_dir:
        csv_dir = dump_qlib_csv(bars, args.csv_dir, universe_config)
        print(f"Wrote Qlib CSV files: {csv_dir}")
    qlib_dir = dump_qlib_bin(bars, args.qlib_dir, universe_config, market=args.market)
    print(f"Wrote Qlib binary dataset: {qlib_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Enriched bars parquet/csv.")
    parser.add_argument("--qlib-dir", default="data/qlib_cn_ashare")
    parser.add_argument("--csv-dir", default=None)
    parser.add_argument("--market", default="all")
    parser.add_argument("--exclude-st", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-paused", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-limit-buy", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
