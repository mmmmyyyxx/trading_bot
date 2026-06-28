"""Write a compact real-data research status summary."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


def main() -> None:
    args = parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    assert_formal_report_uses_real_data(output, {"data": real_data_markers()})
    output.write_text(render_status(args), encoding="utf-8")
    print(f"Wrote research status summary: {output}")


def render_status(args: argparse.Namespace) -> str:
    universe = _read_csv(args.universe)
    rolling = _read_csv(args.rolling_stability)
    low_workflow = _read_csv(args.low_workflow)
    low_rolling = _read_csv(args.low_rolling_stability)
    exchange = _read_csv(args.exchange_stability)
    quality = _read_csv(args.quality)
    historical = _read_json(args.historical_coverage_json)

    sections = [
        "# Research Status Summary Real AKShare",
        "",
        "All formal tables referenced here use `data_type=real_akshare`, `synthetic_data=False`, and `mock_data=False`.",
        "",
        "## Current Real-Data Experiment Scope",
        _scope_text(universe),
        "",
        "## Universe Expansion Main Results",
        _table(universe, ["universe_name", "result_role", "selected_mode", "data_sufficient_for_dynamic_top_n", "excess_annualized_return_with_cost", "excess_information_ratio_with_cost", "data_quality_status", "industry_quality_status"]),
        "",
        "## Rolling OOS Stability",
        _table(rolling, ["universe_name", "positive_excess_windows", "positive_excess_ratio", "min_excess_annualized", "y2026_excess", "y2026_IR", "conclusion_tag"]),
        "",
        "## Low-Turnover Workflow Results",
        _table(low_workflow, ["scenario", "excess_annualized_return_with_cost", "excess_information_ratio_with_cost", "turnover", "cost", "data_quality_status", "industry_quality_status"]),
        "",
        "## Low-Turnover Rolling Stability",
        _table(low_rolling, ["scenario", "positive_excess_windows", "positive_excess_ratio", "mean_excess_annualized", "y2026_excess", "mean_turnover", "conclusion_tag"]),
        "",
        "## AShareExchange Rolling Stability",
        _table(exchange, ["exchange_scenario", "positive_excess_windows", "positive_excess_ratio", "mean_excess_annualized", "min_excess_annualized", "y2026_excess", "mean_turnover", "conclusion_tag"]),
        "",
        "## Data Quality And Industry Quality",
        _table(quality, ["universe_name", "data_quality_status", "industry_quality_status", "unknown_source_ratio", "invalid_limit_ratio", "industry_position_weighted_unknown"]),
        "",
        "## Historical Constituents Preparation",
        _historical_text(historical),
        "",
        "## Caveats",
        "- Current-constituent and current-listed candidate bias remain unless historical membership is supplied.",
        "- Dynamic top500 is supplementary because the selected universe did not fully reach the intended top-N target.",
        "- 2026 windows are YTD and should not be interpreted as complete calendar-year tests.",
        "- Uniform Qlib limit thresholds remain a simplification; AShareExchange rolling improves realism but is still part of the research validation stack.",
        "- IC, beta, industry exposure, and rolling diagnostics should be read together before making strategy conclusions.",
        "",
        "## Next Steps",
        "- Prioritize historical index constituent coverage for HS300, then CSI500 and CSI1000.",
        "- Promote top450 and low-turnover rolling results into the main narrative only after reviewing 2026YTD weakness.",
        "- Continue improving A-share exchange/order constraints and compare against the uniform-limit baseline.",
        "",
    ]
    return "\n".join(sections)


def _scope_text(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "No universe expansion table found."
    universes = ", ".join(frame["universe_name"].dropna().astype(str).tolist())
    return f"Formal universe expansion currently covers {len(frame)} rows: {universes}."


def _historical_text(payload: dict) -> str:
    if not payload:
        return "Historical constituent coverage report has not been generated yet."
    status = payload.get("coverage_status", "unknown")
    available = payload.get("historical_membership_available")
    symbols = payload.get("current_snapshot_symbols")
    reason = payload.get("reason", "")
    return (
        f"HS300 historical membership coverage status: `{status}`. "
        f"Historical membership available: `{available}`. Current snapshot symbols: `{symbols}`. {reason}"
    )


def _table(frame: pd.DataFrame, columns: list[str]) -> str:
    if frame.empty:
        return "No data."
    available = [column for column in columns if column in frame.columns]
    if not available:
        return "No requested columns available."
    return frame[available].to_markdown(index=False)


def _read_csv(path: str) -> pd.DataFrame:
    source = Path(path)
    return pd.read_csv(source) if source.exists() else pd.DataFrame()


def _read_json(path: str) -> dict:
    source = Path(path)
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="reports/research_status_summary_real.md")
    parser.add_argument("--universe", default="reports/universe_expansion_comparison.csv")
    parser.add_argument("--rolling-stability", default="reports/rolling_oos_stability_summary_real.csv")
    parser.add_argument("--low-workflow", default="reports/low_turnover_workflow_comparison_real.csv")
    parser.add_argument("--low-rolling-stability", default="reports/low_turnover_rolling_stability_summary_real.csv")
    parser.add_argument("--exchange-stability", default="reports/exchange_rolling_stability_summary_real.csv")
    parser.add_argument("--quality", default="reports/quality_universe_comparison_real.csv")
    parser.add_argument(
        "--historical-coverage-json",
        default="reports/historical_constituents/hs300/coverage_report.json",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
