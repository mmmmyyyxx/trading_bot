"""Write a lightweight manifest for a completed Qlib baseline run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.manifest import build_run_manifest


def main() -> None:
    args = parse_args()
    manifest = build_run_manifest(
        summary_path=args.summary,
        runtime_config_path=args.runtime_config,
        universe_diagnostics_path=args.universe_diagnostics,
        symbols_file=args.symbols_file,
        output_path=args.output,
    )
    print(f"Wrote run manifest: {args.output}")
    print(f"selected_mode={manifest['universe']['selected_mode']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--summary", default="reports/alpha158_hs300_full/summary.json")
    parser.add_argument("--runtime-config", default="reports/alpha158_hs300_full/alpha158_lgb_runtime.yaml")
    parser.add_argument("--universe-diagnostics", default="reports/alpha158_hs300_full/universe_diagnostics.csv")
    parser.add_argument("--symbols-file", default="data/cache/hs300_symbols_full.txt")
    parser.add_argument("--output", default="reports/run_manifest.json")
    return parser.parse_args()


if __name__ == "__main__":
    main()
