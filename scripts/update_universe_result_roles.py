"""Update universe expansion result-role labels for real-data reports."""

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
    csv_path = Path(args.input_csv)
    md_path = Path(args.input_md)
    table = pd.read_csv(csv_path)
    table = update_result_roles(table)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    table.to_csv(csv_path, index=False)
    md_path.write_text("# Universe Expansion Comparison\n\n" + table.to_markdown(index=False) + "\n", encoding="utf-8")
    print(f"Updated universe expansion result roles: {csv_path}")


def update_result_roles(table: pd.DataFrame) -> pd.DataFrame:
    data = table.copy()
    if "result_role" not in data.columns:
        insert_at = list(data.columns).index("model") if "model" in data.columns else len(data.columns)
        data.insert(insert_at, "result_role", "")
    data["result_role"] = data.apply(_role_for_row, axis=1)
    return data


def _role_for_row(row: pd.Series) -> str:
    universe = str(row.get("universe_name", ""))
    selected = str(row.get("selected_mode", ""))
    if selected.startswith("dynamic_liquidity"):
        sufficient = _truthy(row.get("data_sufficient_for_dynamic_top_n"))
        if not sufficient:
            return "supplementary_insufficient_topn"
        if "candidate2000" in universe and "top450" in universe:
            return "primary_dynamic_large_candidate"
        return "primary_dynamic_candidate"
    return "primary_current_constituent"


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"true", "1", "1.0", "yes"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", default="reports/universe_expansion_comparison.csv")
    parser.add_argument("--input-md", default="reports/universe_expansion_comparison.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
