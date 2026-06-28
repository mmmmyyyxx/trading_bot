"""Run A-share bar data quality audits."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.data_quality import write_data_quality_report
from ashare_adapter.qlib_converter import read_bars


def main() -> None:
    args = parse_args()
    bars = read_bars(args.bars)
    positions = _read_optional_positions(args.positions)
    if positions is not None:
        # Positions are accepted for CLI symmetry with industry audits; bar quality
        # itself is independent of holdings.
        _ = positions
    summary = write_data_quality_report(
        bars,
        output_dir=args.output_dir,
        selected_col=args.selected_col,
        positions=positions,
        fail_on_error=args.fail_on_error,
    )
    print(f"Data quality status: {summary.get('quality_status')}")
    print(f"Wrote data quality report: {Path(args.output_dir) / 'data_quality_summary.json'}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--positions", default=None)
    parser.add_argument("--universe-name", default="")
    parser.add_argument("--selected-col", default="selected")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fail-on-error", action="store_true")
    return parser.parse_args()


def _read_optional_positions(path: str | None) -> pd.DataFrame | None:
    if not path:
        return None
    source = Path(path)
    if not source.exists():
        return None
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source)


if __name__ == "__main__":
    main()
