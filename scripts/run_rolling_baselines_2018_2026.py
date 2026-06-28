"""Run or generate 2018-2026 rolling OOS baseline workflows."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.run_rolling_baselines import (
    MODEL_SPECS,
    build_workflow_config,
    read_run_metrics,
    resolve_run_dir,
    run_qrun,
)

ROLLING_WINDOWS_2018_2026 = [
    {
        "name": "2018_2022",
        "train": ["2018-01-01", "2020-12-31"],
        "valid": ["2021-01-01", "2021-12-31"],
        "test": ["2022-01-01", "2022-12-31"],
        "is_ytd": False,
    },
    {
        "name": "2019_2023",
        "train": ["2019-01-01", "2021-12-31"],
        "valid": ["2022-01-01", "2022-12-31"],
        "test": ["2023-01-01", "2023-12-31"],
        "is_ytd": False,
    },
    {
        "name": "2020_2024",
        "train": ["2020-01-01", "2022-12-31"],
        "valid": ["2023-01-01", "2023-12-31"],
        "test": ["2024-01-01", "2024-12-31"],
        "is_ytd": False,
    },
    {
        "name": "2021_2025",
        "train": ["2021-01-01", "2023-12-31"],
        "valid": ["2024-01-01", "2024-12-31"],
        "test": ["2025-01-01", "2025-12-31"],
        "is_ytd": False,
    },
    {
        "name": "2022_2026_ytd",
        "train": ["2022-01-01", "2024-12-31"],
        "valid": ["2025-01-01", "2025-12-31"],
        "test": ["2026-01-01", "2026-06-24"],
        "is_ytd": True,
    },
]


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    universe_summary = _summarize_universe(args.universe_diagnostics)
    rows = []
    for window in _windows(args.end_date):
        for model_name in args.models:
            spec = MODEL_SPECS[model_name]
            run_dir = output_dir / args.universe_name / window["name"] / model_name
            run_dir.mkdir(parents=True, exist_ok=True)
            config_path = run_dir / "workflow.yaml"
            log_path = run_dir / "qrun.log"
            config = build_workflow_config(
                provider_uri=args.provider_uri,
                market=args.market,
                benchmark=args.benchmark,
                window=window,
                spec=spec,
                topk=args.topk,
                n_drop=args.n_drop,
                account=args.account,
                open_cost=args.open_cost,
                close_cost=args.close_cost,
                min_cost=args.min_cost,
                limit_threshold=args.limit_threshold,
                num_threads=args.num_threads,
                use_ashare_exchange=args.use_ashare_exchange,
                limit_price_buffer=args.limit_price_buffer,
            )
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            row = {
                "universe_name": args.universe_name,
                "universe_mode": args.universe_mode,
                "selected_mode": args.selected_mode,
                "dynamic_liquidity_top_n": args.dynamic_liquidity_top_n,
                "candidate_pool_size": args.candidate_pool_size,
                "requested_symbols": args.requested_symbols,
                "actual_symbols": args.actual_symbols,
                "missing_symbols_count": args.missing_symbols_count,
                "candidate_symbol_coverage": _coverage(args.requested_symbols, args.actual_symbols),
                "selected_top_n_reached": _selected_top_n_reached(args.dynamic_liquidity_top_n, universe_summary),
                "data_sufficient_for_dynamic_top_n": _data_sufficient_for_dynamic_top_n(
                    args.requested_symbols,
                    args.actual_symbols,
                    args.dynamic_liquidity_top_n,
                    universe_summary,
                ),
                **universe_summary,
                "model": spec["display"],
                "model_key": model_name,
                "benchmark": args.benchmark,
                "train_start": window["train"][0],
                "train_end": window["train"][1],
                "valid_start": window["valid"][0],
                "valid_end": window["valid"][1],
                "test_start": window["test"][0],
                "test_end": window["test"][1],
                "is_ytd": bool(window["is_ytd"]),
                "config_path": str(config_path),
                "log_path": str(log_path),
                "caveats": _caveats(args, window),
            }
            if args.execute:
                run_info = run_qrun(config_path, log_path)
                qlib_run_dir = resolve_run_dir(args.mlruns_dir, run_info)
                row.update(read_run_metrics(qlib_run_dir))
                row.update(run_info)
            rows.append(row)

    comparison_path = Path(args.comparison_csv)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison = _merge_comparison(comparison_path, rows)
    comparison.to_csv(comparison_path, index=False)
    Path(args.comparison_md).write_text(_render_markdown(comparison, args.execute), encoding="utf-8")
    print(f"Wrote rolling comparison: {comparison_path}")
    print(f"Wrote rolling comparison md: {args.comparison_md}")


def _windows(end_date: str) -> list[dict[str, Any]]:
    windows = []
    final_end = pd.Timestamp(end_date)
    for window in ROLLING_WINDOWS_2018_2026:
        item = {key: value for key, value in window.items()}
        if item["is_ytd"]:
            item["test"] = [item["test"][0], final_end.strftime("%Y-%m-%d")]
        windows.append(item)
    return windows


def _merge_comparison(path: Path, rows: list[dict[str, Any]]) -> pd.DataFrame:
    new_rows = pd.DataFrame(rows)
    if not path.exists():
        return new_rows
    existing = pd.read_csv(path)
    key_cols = [
        "universe_name",
        "model_key",
        "benchmark",
        "train_start",
        "train_end",
        "valid_start",
        "valid_end",
        "test_start",
        "test_end",
    ]
    if existing.empty or new_rows.empty or not set(key_cols).issubset(existing.columns) or not set(key_cols).issubset(new_rows.columns):
        return new_rows
    old_keys = existing[key_cols].astype(str).agg("\x1f".join, axis=1)
    new_keys = set(new_rows[key_cols].astype(str).agg("\x1f".join, axis=1))
    kept = existing.loc[~old_keys.isin(new_keys)].copy()
    merged = pd.concat([kept, new_rows], ignore_index=True)
    sort_cols = [column for column in ["universe_name", "model_key", "test_start"] if column in merged.columns]
    return merged.sort_values(sort_cols, kind="stable").reset_index(drop=True) if sort_cols else merged


def _summarize_universe(path: str | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {
            "avg_selected_universe_count": None,
            "min_selected_universe_count": None,
            "max_selected_universe_count": None,
        }
    data = pd.read_csv(path)
    selected = pd.to_numeric(data.get("selected_universe_count", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "avg_selected_universe_count": float(selected.mean()) if not selected.empty else None,
        "min_selected_universe_count": int(selected.min()) if not selected.empty else None,
        "max_selected_universe_count": int(selected.max()) if not selected.empty else None,
    }


def _coverage(requested_symbols: int | None, actual_symbols: int | None) -> float | None:
    if not requested_symbols or actual_symbols is None:
        return None
    return float(actual_symbols) / float(requested_symbols)


def _selected_top_n_reached(dynamic_top_n: int | None, universe_summary: dict[str, Any]) -> bool | None:
    if not dynamic_top_n:
        return None
    max_selected = universe_summary.get("max_selected_universe_count")
    if max_selected is None:
        return None
    return int(max_selected) >= int(dynamic_top_n)


def _data_sufficient_for_dynamic_top_n(
    requested_symbols: int | None,
    actual_symbols: int | None,
    dynamic_top_n: int | None,
    universe_summary: dict[str, Any],
) -> bool | None:
    if not dynamic_top_n:
        return None
    selected_ok = _selected_top_n_reached(dynamic_top_n, universe_summary)
    coverage = _coverage(requested_symbols, actual_symbols)
    coverage_ok = coverage is None or coverage >= 0.8
    return bool(selected_ok) and coverage_ok


def _caveats(args: argparse.Namespace, window: dict[str, Any]) -> str:
    caveats = [
        "current_constituent_bias" if args.universe_mode == "current_constituent" else "current_listed_candidate_bias",
        args.selected_mode,
        "2026_ytd_window" if window.get("is_ytd") else "complete_calendar_test_window",
        (
            f"ashare_exchange_limit_up_down_buffer_{getattr(args, 'limit_price_buffer', 0.001)}"
            if getattr(args, "use_ashare_exchange", False)
            else f"qlib_uniform_limit_threshold_{args.limit_threshold}"
        ),
        "industry_metadata_coverage_required",
    ]
    return "; ".join(caveats)


def _render_markdown(comparison: pd.DataFrame, executed: bool) -> str:
    note = "Executed qrun for all rows." if executed else "Dry run: configs generated but qrun was not executed."
    return "# Rolling Baseline Comparison 2018-2026\n\n" + note + "\n\n" + comparison.to_markdown(index=False) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-uri", required=True)
    parser.add_argument("--mlruns-dir", default="mlruns")
    parser.add_argument("--market", default="all")
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--universe-name", required=True)
    parser.add_argument("--universe-mode", default="current_constituent")
    parser.add_argument("--selected-mode", default="eligible_only")
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--candidate-pool-size", type=int, default=None)
    parser.add_argument("--requested-symbols", type=int, default=None)
    parser.add_argument("--actual-symbols", type=int, default=None)
    parser.add_argument("--missing-symbols-count", type=int, default=None)
    parser.add_argument("--universe-diagnostics", default=None)
    parser.add_argument("--end-date", default="2026-06-24")
    parser.add_argument("--output-dir", default="reports/rolling_baselines_2018_2026")
    parser.add_argument("--comparison-csv", default="reports/rolling_baseline_comparison_2018_2026.csv")
    parser.add_argument("--comparison-md", default="reports/rolling_baseline_comparison_2018_2026.md")
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=["alpha158_lgb"])
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--n-drop", type=int, default=10)
    parser.add_argument("--account", type=float, default=100_000_000)
    parser.add_argument("--open-cost", type=float, default=0.00031)
    parser.add_argument("--close-cost", type=float, default=0.00081)
    parser.add_argument("--min-cost", type=float, default=5.0)
    parser.add_argument("--limit-threshold", type=float, default=0.095)
    parser.add_argument("--num-threads", type=int, default=4)
    parser.add_argument("--use-ashare-exchange", action="store_true")
    parser.add_argument("--limit-price-buffer", type=float, default=0.001)
    return parser.parse_args()


if __name__ == "__main__":
    main()
