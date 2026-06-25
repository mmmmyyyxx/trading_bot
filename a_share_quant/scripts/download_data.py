"""Download or generate normalized daily bars into the local sqlite cache."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from ashare_quant.config import load_config
from ashare_quant.logger import setup_logging
from ashare_quant.pipeline import load_market_data


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="configs/default.yaml")
    parser.add_argument("--set", dest="overrides", action="append", default=[])
    parser.add_argument("--refresh", action="store_true", help="Force a provider refresh and rebuild the cache.")
    parser.add_argument("--batch-size", type=int, help="Number of symbols to fetch per provider batch.")
    args = parser.parse_args()

    config = load_config(args.config, args.overrides)
    if args.batch_size:
        config.data.download_batch_size = args.batch_size
    setup_logging(config.logging.level)
    bars = load_market_data(config, refresh=args.refresh)
    print(f"saved_rows={len(bars)} cache={config.data.cache_path}")


if __name__ == "__main__":
    main()

