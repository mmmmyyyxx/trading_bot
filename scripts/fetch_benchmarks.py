"""Fetch HS300/CSI500/CSI1000 benchmark series through AKShare."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.benchmarks import dump_benchmarks_to_qlib, load_akshare_benchmarks, write_benchmarks


def main() -> None:
    args = parse_args()
    benchmarks = load_akshare_benchmarks(args.start_date, args.end_date, args.keys)
    output = write_benchmarks(benchmarks, args.output)
    print(f"Wrote benchmarks: {output}")
    if args.qlib_dir:
        qlib_dir = dump_benchmarks_to_qlib(benchmarks, args.qlib_dir)
        print(f"Wrote Qlib benchmark features: {qlib_dir}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--keys", nargs="+", choices=["hs300", "csi500", "csi1000"], default=None)
    parser.add_argument("--output", default="data/benchmarks.parquet")
    parser.add_argument("--qlib-dir", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
