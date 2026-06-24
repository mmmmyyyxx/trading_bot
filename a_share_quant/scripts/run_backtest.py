"""Run the full A-share multi-factor backtest pipeline."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ashare_quant.config import load_config
from ashare_quant.logger import setup_logging
from ashare_quant.pipeline import run_backtest_pipeline


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--refresh-data", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config, args.overrides)
    setup_logging(config.logging.level)
    result = run_backtest_pipeline(config, refresh_data=args.refresh_data, write_outputs=True)
    print(json.dumps(result.metrics, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()

