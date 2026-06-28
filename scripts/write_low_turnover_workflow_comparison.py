"""Collect completed low-turnover Alpha158 workflow summaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


def main() -> None:
    args = parse_args()
    rows = [row for row in (_read_run(Path(path)) for path in args.run_dirs) if row]
    comparison = pd.DataFrame(rows)
    csv_path = Path(args.output_csv)
    md_path = Path(args.output_md)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    comparison.to_csv(csv_path, index=False)
    md_path.write_text(_render_markdown(comparison), encoding="utf-8")
    print(f"Wrote low-turnover workflow comparison: {csv_path}")


def _read_run(run_dir: Path) -> dict[str, Any] | None:
    summary_path = run_dir / "summary.json"
    manifest_path = run_dir / "run_manifest.json"
    if not summary_path.exists() or not manifest_path.exists():
        return None
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    data = summary.get("data", {})
    if data.get("data_type") != "real_akshare" or data.get("synthetic_data") or data.get("mock_data"):
        raise ValueError(f"Refusing non-real summary: {summary_path}")
    portfolio = summary.get("portfolio", {})
    signal = summary.get("signal", {})
    run_meta = _read_json(run_dir / "experiment_metadata.json").get("run", {})
    manifest_portfolio = manifest.get("portfolio", {})
    scenario = run_meta.get("scenario") or _infer_scenario(run_dir)
    return {
        **real_data_markers(),
        "scenario": scenario,
        "universe_name": _universe_name(manifest, summary),
        "model": "Alpha158 + LightGBM",
        "benchmark": manifest_portfolio.get("benchmark"),
        "topk": run_meta.get("topk", manifest_portfolio.get("topk")),
        "n_drop": run_meta.get("n_drop", manifest_portfolio.get("n_drop")),
        "rebalance_step": run_meta.get("rebalance_step", manifest_portfolio.get("rebalance_step", 1)),
        "exchange_mode": run_meta.get("exchange_mode", manifest_portfolio.get("exchange_mode")),
        "limit_price_buffer": run_meta.get("limit_price_buffer", manifest_portfolio.get("limit_price_buffer")),
        "train_start": _segment(manifest, "train", 0),
        "train_end": _segment(manifest, "train", 1),
        "valid_start": _segment(manifest, "valid", 0),
        "valid_end": _segment(manifest, "valid", 1),
        "test_start": _segment(manifest, "test", 0),
        "test_end": _segment(manifest, "test", 1),
        "is_ytd": _is_ytd(_segment(manifest, "test", 1)),
        "IC": signal.get("IC"),
        "RankIC": signal.get("Rank IC"),
        "ICIR": signal.get("ICIR"),
        "RankICIR": signal.get("Rank ICIR"),
        "excess_annualized_return_with_cost": portfolio.get("excess_with_cost_annualized_return"),
        "excess_information_ratio_with_cost": portfolio.get("excess_with_cost_information_ratio"),
        "excess_max_drawdown_with_cost": portfolio.get("excess_with_cost_max_drawdown"),
        "account_total_return": portfolio.get("account_total_return"),
        "benchmark_total_return": portfolio.get("benchmark_total_return"),
        "turnover": portfolio.get("avg_daily_turnover"),
        "cost": portfolio.get("total_cost_sum"),
        "data_quality_status": manifest.get("data_quality", {}).get("quality_status"),
        "industry_quality_status": manifest.get("industry_quality", {}).get(
            "industry_quality_status", manifest.get("industry_quality", {}).get("quality_status")
        ),
        "summary_path": str(summary_path),
        "manifest_path": str(manifest_path),
        "caveats": "; ".join(manifest.get("caveats", [])),
    }


def _render_markdown(comparison: pd.DataFrame) -> str:
    note = "Completed Qlib Alpha158 workflows on real AKShare data; these are not portfolio-layer sensitivity reruns."
    return "# Low-Turnover Workflow Comparison Real AKShare\n\n" + note + "\n\n" + comparison.to_markdown(index=False) + "\n"


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _infer_scenario(path: Path) -> str:
    return path.name.replace("alpha158_dynamic_candidate1000_top300_", "").replace("_2018_2026", "")


def _universe_name(manifest: dict[str, Any], summary: dict[str, Any]) -> str:
    bars_path = str(summary.get("data", {}).get("bars_path") or "")
    if "dynamic_candidate1000_top300" in bars_path:
        return "dynamic_candidate1000_top300_2018_2026"
    return str(manifest.get("universe", {}).get("symbols_file") or "")


def _segment(manifest: dict[str, Any], key: str, idx: int) -> Any:
    values = manifest.get("segments", {}).get(key) or []
    return values[idx] if len(values) > idx else None


def _is_ytd(end_date: Any) -> bool:
    text = str(end_date or "")
    return text.startswith("2026-") and not text.endswith("12-31")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dirs", nargs="+", required=True)
    parser.add_argument("--output-csv", default="reports/low_turnover_workflow_comparison_real.csv")
    parser.add_argument("--output-md", default="reports/low_turnover_workflow_comparison_real.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
