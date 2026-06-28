"""Prepare historical index constituent coverage reports without silent current-member fallback."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.indexes import load_index_constituents
from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


INDEX_SYMBOLS = {"hs300": "000300"}


def main() -> None:
    args = parse_args()
    if args.index_key not in INDEX_SYMBOLS:
        raise ValueError(f"Unsupported index_key={args.index_key!r}; supported keys: {sorted(INDEX_SYMBOLS)}")
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    current = pd.DataFrame()
    error = None
    try:
        current = load_index_constituents(
            index_symbol=INDEX_SYMBOLS[args.index_key],
            cache_path=Path(args.cache_dir) / f"{args.index_key}_constituents.parquet",
            refresh=args.refresh_current,
        )
        _with_real_markers(current).to_csv(output_dir / "current_snapshot.csv", index=False)
    except Exception as exc:  # pragma: no cover - network/API dependent
        error = str(exc)

    report = build_coverage_report(args, current, error=error)
    csv_path = output_dir / "coverage_report.csv"
    json_path = output_dir / "coverage_report.json"
    md_path = output_dir / "coverage_report.md"
    for path in [csv_path, json_path, md_path]:
        assert_formal_report_uses_real_data(path, {"data": real_data_markers()})
    pd.DataFrame([report]).to_csv(csv_path, index=False)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote historical constituent coverage report: {json_path}")


def build_coverage_report(args: argparse.Namespace, current: pd.DataFrame, error: str | None = None) -> dict[str, Any]:
    current_count = int(len(current)) if current is not None else 0
    current_available = current_count > 0
    historical_available = False
    status = "failed_current_snapshot" if error else "insufficient_historical_membership"
    reason = (
        f"Unable to fetch current snapshot: {error}"
        if error
        else "Project AKShare helpers expose current constituents only; no complete historical membership endpoint is available here."
    )
    return {
        **real_data_markers(),
        "index_key": args.index_key,
        "index_symbol": INDEX_SYMBOLS[args.index_key],
        "requested_start_date": args.start_date,
        "requested_end_date": args.end_date,
        "report_time": datetime.now().isoformat(timespec="seconds"),
        "current_snapshot_available": current_available,
        "current_snapshot_symbols": current_count,
        "historical_membership_available": historical_available,
        "coverage_status": status,
        "source": "akshare_current_constituent_snapshot" if current_available else "akshare_attempt_failed",
        "reason": reason,
        "caveat": (
            "Current constituent snapshots must not be used as historical membership. "
            "Strategy reports should keep current-constituent bias caveats until historical membership is available."
        ),
    }


def render_markdown(report: dict[str, Any]) -> str:
    return (
        "# HS300 Historical Constituent Coverage Report\n\n"
        "This report intentionally does not silently backfill historical membership with current constituents.\n\n"
        + pd.DataFrame([report]).to_markdown(index=False)
        + "\n"
    )


def _with_real_markers(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    markers = real_data_markers()
    for column, value in reversed(list(markers.items())):
        data.insert(0, column, value)
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index-key", default="hs300", choices=sorted(INDEX_SYMBOLS))
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default="2026-06-24")
    parser.add_argument("--output-dir", default="reports/historical_constituents/hs300")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--refresh-current", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
