"""Export the latest Qlib Alpha158 run into report files."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.result_export import export_alpha158_results


def main() -> None:
    args = parse_args()
    requested_symbols = _read_symbols(args.symbols_file)
    summary = export_alpha158_results(
        run_dir=args.run_dir,
        output_dir=args.output_dir,
        mlruns_dir=args.mlruns_dir,
        bars_path=args.bars_path,
        benchmarks_path=args.benchmarks_path,
        qrun_log=args.qrun_log,
        requested_symbols=requested_symbols,
    )
    print(f"Exported Alpha158 summary: {summary['outputs']['summary_md']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--mlruns-dir", default="mlruns")
    parser.add_argument("--output-dir", default="reports/alpha158_hs300")
    parser.add_argument("--bars-path", default="data/alpha158_hs300_bars.parquet")
    parser.add_argument("--benchmarks-path", default="data/benchmarks.parquet")
    parser.add_argument("--qrun-log", default="reports/alpha158_hs300/qrun_alpha158.log")
    parser.add_argument("--symbols-file", default=None)
    return parser.parse_args()


def _read_symbols(path: str | None) -> list[str]:
    if not path:
        return []
    from ashare_adapter.metadata import normalize_symbol

    return [
        normalize_symbol(line.strip())
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


if __name__ == "__main__":
    main()
