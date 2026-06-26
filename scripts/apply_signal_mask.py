"""Apply an A-share selected/eligible universe mask to prediction scores."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.signal_mask import mask_prediction_file


def main() -> None:
    args = parse_args()
    paths = mask_prediction_file(
        predictions_path=args.predictions,
        bars_path=args.bars,
        output_csv=args.output_csv,
        output_pkl=args.output_pkl,
        score_col=args.score_col,
        mask_col=args.mask_col,
    )
    for name, path in paths.items():
        print(f"Wrote {name}: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--bars", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--output-pkl", default=None)
    parser.add_argument("--score-col", default="score")
    parser.add_argument("--mask-col", default="selected")
    return parser.parse_args()


if __name__ == "__main__":
    main()
