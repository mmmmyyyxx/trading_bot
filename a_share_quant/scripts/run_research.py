"""Run research diagnostics for the A-share quant MVP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ashare_quant.config import load_config
from ashare_quant.logger import setup_logging
from ashare_quant.research.pipeline import run_research_pipeline


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--refresh-data", action="store_true")
    args = parser.parse_args()

    config = load_config(args.config, args.overrides)
    setup_logging(config.logging.level)
    outputs = run_research_pipeline(config, refresh_data=args.refresh_data)
    print("research_outputs=" + ",".join(f"{name}:{len(frame)}" for name, frame in outputs.items()))


if __name__ == "__main__":
    main()

