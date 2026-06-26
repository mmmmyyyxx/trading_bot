"""Run local diagnostics around Qlib prediction and portfolio outputs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.benchmarks import read_benchmarks
from ashare_adapter.diagnostics import write_diagnostics
from ashare_adapter.qlib_converter import read_bars


def main() -> None:
    args = parse_args()
    bars = read_bars(args.bars)
    scores = _read_frame(args.scores)
    benchmarks = read_benchmarks(args.benchmarks) if args.benchmarks else None
    equity = _read_frame(args.equity) if args.equity else None
    positions = _read_frame(args.positions) if args.positions else None
    trades = _read_frame(args.trades) if args.trades else None
    paths = write_diagnostics(
        output_dir=args.output_dir,
        bars=bars,
        scores=scores,
        benchmarks=benchmarks,
        equity=equity,
        positions=positions,
        trades=trades,
        score_col=args.score_col,
        horizons=args.horizons,
        n_groups=args.n_groups,
        oos_start_date=args.oos_start_date,
    )
    for name, path in paths.items():
        print(f"Wrote {name}: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--scores", required=True)
    parser.add_argument("--benchmarks", default=None)
    parser.add_argument("--equity", default=None)
    parser.add_argument("--positions", default=None)
    parser.add_argument("--trades", default=None)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--score-col", default="score")
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 5, 20])
    parser.add_argument("--n-groups", type=int, default=5)
    parser.add_argument("--oos-start-date", default=None)
    return parser.parse_args()


def _read_frame(path: str) -> pd.DataFrame:
    source = Path(path)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source)


if __name__ == "__main__":
    main()
