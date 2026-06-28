"""Build exchange rolling comparison with uniform and AShareExchange scenarios."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


def main() -> None:
    args = parse_args()
    frames = [_uniform_rows(args.uniform_csv), _ashare_rows(args.ashare_csv)]
    comparison = pd.concat(frames, ignore_index=True)
    comparison = comparison.sort_values(["exchange_mode", "limit_price_buffer", "test_start"], kind="stable").reset_index(drop=True)
    csv_path = Path(args.output_csv)
    md_path = Path(args.output_md)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    comparison.to_csv(csv_path, index=False)
    md_path.write_text(_render_markdown(comparison), encoding="utf-8")
    print(f"Wrote exchange rolling comparison: {csv_path}")


def _uniform_rows(path: str) -> pd.DataFrame:
    rows = pd.read_csv(path)
    rows = rows[
        (rows["universe_name"].astype(str) == "dynamic_candidate1000_top300_2018_2026")
        & (rows["model_key"].astype(str) == "alpha158_lgb")
    ].copy()
    if rows.empty:
        raise ValueError(f"No dynamic1000 alpha158 rows found in {path}")
    rows["exchange_mode"] = "uniform_limit_threshold"
    rows["limit_price_buffer"] = pd.NA
    rows["exchange_scenario"] = "uniform_limit_threshold_0.095"
    return rows


def _ashare_rows(path: str) -> pd.DataFrame:
    rows = pd.read_csv(path)
    rows = rows[rows["exchange_mode"].astype(str).eq("ashare_exchange")].copy()
    if rows.empty:
        raise ValueError(f"No AShareExchange rows found in {path}")
    rows["exchange_scenario"] = rows["limit_price_buffer"].map(lambda value: f"ashare_exchange_buffer_{float(value):.3f}")
    return rows


def _render_markdown(comparison: pd.DataFrame) -> str:
    note = (
        "Real AKShare rolling comparison. Uniform rows reuse the existing real dynamic1000 top300 rolling OOS; "
        "AShareExchange rows are full Qlib rolling workflows using per-stock limit fields."
    )
    return "# Exchange Rolling Comparison Real AKShare\n\n" + note + "\n\n" + comparison.to_markdown(index=False) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uniform-csv", default="reports/rolling_baseline_comparison_2018_2026_real.csv")
    parser.add_argument("--ashare-csv", default="reports/exchange_rolling_comparison_real.csv")
    parser.add_argument("--output-csv", default="reports/exchange_rolling_comparison_real.csv")
    parser.add_argument("--output-md", default="reports/exchange_rolling_comparison_real.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
