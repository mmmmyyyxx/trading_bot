"""Run active attribution diagnostics from exported Qlib records."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.active_exposure import write_active_attribution
from ashare_adapter.benchmarks import read_benchmarks
from ashare_adapter.qlib_converter import read_bars


def main() -> None:
    args = parse_args()
    paths = write_active_attribution(
        output_dir=args.output_dir,
        bars=read_bars(args.bars),
        equity=_read_frame(args.equity),
        positions=_read_frame(args.positions),
        benchmarks=read_benchmarks(args.benchmarks),
        benchmark_symbols=_read_symbols(args.benchmark_symbols_file),
    )
    for name, path in paths.items():
        print(f"Wrote {name}: {path}")


def _read_frame(path: str) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source)


def _read_symbols(path: str) -> list[str]:
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--equity", required=True)
    parser.add_argument("--positions", required=True)
    parser.add_argument("--benchmarks", required=True)
    parser.add_argument("--benchmark-symbols-file", required=True)
    parser.add_argument("--output-dir", default="reports/active_attribution")
    return parser.parse_args()


if __name__ == "__main__":
    main()
