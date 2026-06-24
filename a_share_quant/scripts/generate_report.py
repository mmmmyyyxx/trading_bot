"""Regenerate report files for the configured backtest."""

from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    config = load_config(args.config, args.overrides)
    setup_logging(config.logging.level)
    run_backtest_pipeline(config, refresh_data=False, write_outputs=True)
    print(f"report_dir={config.report.output_dir}")


if __name__ == "__main__":
    main()

