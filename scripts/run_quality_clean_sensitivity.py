"""Run HS300 selected-universe quality-clean sensitivity workflows."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.benchmarks import QLIB_BENCHMARK_SYMBOLS, dump_benchmarks_to_qlib, load_akshare_benchmarks, write_benchmarks
from ashare_adapter.data_quality import validate_ashare_bars_quality, write_data_quality_report, write_qlib_quality_sidecars
from ashare_adapter.industry_metadata import write_industry_coverage_report
from ashare_adapter.manifest import build_run_manifest
from ashare_adapter.qlib_converter import dump_qlib_bin, ensure_future_calendar, read_bars, write_bars
from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers
from ashare_adapter.result_export import export_alpha158_results
from ashare_adapter.universe import build_universe_diagnostics
from scripts.run_alpha158_pipeline import run_qrun, write_runtime_config
from scripts.run_rolling_baselines import parse_qrun_log, resolve_run_dir


SCENARIOS = {
    "original": [],
    "exclude_invalid_ohlc_from_selected": ["invalid_ohlc"],
    "exclude_invalid_limit_from_selected": ["invalid_limit"],
    "exclude_all_failed_quality_from_selected": ["quality_status_failed"],
}


def main() -> None:
    args = parse_args()
    base_output = Path(args.output_dir)
    base_output.mkdir(parents=True, exist_ok=True)
    bars = read_bars(args.bars_path)
    _assert_real_bars(bars)
    row_quality, _ = validate_ashare_bars_quality(bars)
    benchmarks = _load_or_download_benchmarks(args)
    rows = []
    for scenario, flags in SCENARIOS.items():
        scenario_output = base_output / scenario
        scenario_qlib = Path(args.qlib_base_dir) / scenario
        scenario_bars = Path(args.bars_output_dir) / f"hs300_quality_clean_{scenario}_bars.parquet"
        scenario_output.mkdir(parents=True, exist_ok=True)
        clean_bars = _apply_scenario(bars, row_quality, flags)
        write_bars(clean_bars, scenario_bars)
        diagnostics_path = scenario_output / "universe_diagnostics.csv"
        build_universe_diagnostics(clean_bars, None).to_csv(diagnostics_path, index=False)
        data_quality = write_data_quality_report(clean_bars, scenario_output / "data_quality", selected_col="selected", fail_on_error=False)
        industry_quality = write_industry_coverage_report(clean_bars, scenario_output / "industry", positions=None, selected_col="selected")
        if args.refresh_qlib and scenario_qlib.exists():
            _remove_dir_checked(scenario_qlib)
        if args.refresh_qlib or not (scenario_qlib / "features").exists():
            dump_qlib_bin(clean_bars, scenario_qlib, None, market=args.market)
            write_qlib_quality_sidecars(scenario_qlib, clean_bars, data_quality, industry_quality)
        ensure_future_calendar(scenario_qlib)
        dump_benchmarks_to_qlib(benchmarks, scenario_qlib, market="benchmarks")

        runtime_config = scenario_output / "alpha158_lgb_runtime.yaml"
        qrun_log = scenario_output / "qrun_alpha158.log"
        runtime_args = _runtime_args(args, scenario_qlib)
        write_runtime_config(runtime_args, runtime_config)
        if args.execute:
            run_qrun(runtime_config, qrun_log)
            run_info = parse_qrun_log(qrun_log.read_text(encoding="utf-8", errors="ignore"))
            run_dir = resolve_run_dir(args.mlruns_dir, run_info)
            summary = export_alpha158_results(
                run_dir=run_dir,
                output_dir=scenario_output,
                bars_path=scenario_bars,
                benchmarks_path=args.benchmarks_path,
                qrun_log=qrun_log,
                universe_diagnostics_path=diagnostics_path,
                requested_symbols=sorted(clean_bars["symbol"].dropna().astype(str).unique().tolist()),
                data_quality_summary=data_quality,
                industry_quality_summary=industry_quality,
                **real_data_markers(),
            )
            manifest = build_run_manifest(
                summary_path=scenario_output / "summary.json",
                runtime_config_path=runtime_config,
                universe_diagnostics_path=diagnostics_path,
                output_path=scenario_output / "run_manifest.json",
                data_quality_summary=data_quality,
                industry_quality_summary=industry_quality,
            )
            rows.append(_comparison_row(scenario, summary, manifest, scenario_output, clean_bars, flags))

    comparison = pd.DataFrame(rows)
    csv_path = Path(args.comparison_csv)
    md_path = Path(args.comparison_md)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    comparison.to_csv(csv_path, index=False)
    md_path.write_text(_render_markdown(comparison), encoding="utf-8")
    print(f"Wrote HS300 quality-clean sensitivity: {csv_path}")


def _apply_scenario(bars: pd.DataFrame, row_quality: pd.DataFrame, flags: list[str]) -> pd.DataFrame:
    data = bars.copy()
    if not flags:
        return data
    quality = row_quality[["date", "symbol", "quality_status", "quality_flags"]].copy()
    quality["date"] = pd.to_datetime(quality["date"], errors="coerce")
    data["date"] = pd.to_datetime(data["date"], errors="coerce")
    merged = data[["date", "symbol"]].merge(quality, on=["date", "symbol"], how="left")
    quality_flags = merged["quality_flags"].fillna("").astype(str)
    mask = pd.Series(False, index=data.index)
    for flag in flags:
        if flag == "quality_status_failed":
            mask = mask | merged["quality_status"].fillna("").astype(str).eq("failed")
        else:
            mask = mask | quality_flags.str.contains(flag, regex=False)
    for column in ["selected", "eligible"]:
        if column in data.columns:
            data.loc[mask, column] = False
    data["quality_clean_scenario"] = ";".join(flags)
    return data


def _comparison_row(
    scenario: str,
    summary: dict[str, Any],
    manifest: dict[str, Any],
    output_dir: Path,
    bars: pd.DataFrame,
    flags: list[str],
) -> dict[str, Any]:
    portfolio = summary.get("portfolio", {})
    signal = summary.get("signal", {})
    universe = manifest.get("universe", {})
    selected = bars.get("selected", pd.Series(False, index=bars.index)).astype(bool)
    return {
        **real_data_markers(),
        "scenario": scenario,
        "removed_flags": ";".join(flags),
        "universe_name": "hs300_current_2018_2026",
        "model": "Alpha158 + LightGBM",
        "benchmark": manifest.get("portfolio", {}).get("benchmark"),
        "selected_rows": int(selected.sum()),
        "avg_selected_universe_count": universe.get("avg_selected_universe_count"),
        "min_selected_universe_count": universe.get("min_selected_universe_count"),
        "max_selected_universe_count": universe.get("max_selected_universe_count"),
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
        "summary_path": str(output_dir / "summary.md"),
        "manifest_path": str(output_dir / "run_manifest.json"),
        "caveats": "; ".join(manifest.get("caveats", [])),
    }


def _runtime_args(args: argparse.Namespace, qlib_dir: Path) -> argparse.Namespace:
    return argparse.Namespace(
        qlib_dir=str(qlib_dir),
        market=args.market,
        benchmark_key=args.benchmark_key,
        benchmark=args.benchmark or QLIB_BENCHMARK_SYMBOLS[args.benchmark_key],
        start_date=args.start_date,
        end_date=args.end_date,
        fit_start_date=args.train_start_date,
        fit_end_date=args.train_end_date,
        train_start_date=args.train_start_date,
        train_end_date=args.train_end_date,
        valid_start_date=args.valid_start_date,
        valid_end_date=args.valid_end_date,
        test_start_date=args.test_start_date,
        use_selected_filter=True,
        qlib_kernels=args.qlib_kernels,
        joblib_backend=args.joblib_backend,
        topk=args.topk,
        n_drop=args.n_drop,
        account=args.account,
        open_cost=args.open_cost,
        close_cost=args.close_cost,
        min_cost=args.min_cost,
        limit_threshold=args.limit_threshold,
        use_ashare_exchange=False,
        limit_price_buffer=0.001,
        rebalance_step=1,
        learning_rate=args.learning_rate,
        num_threads=args.num_threads,
    )


def _load_or_download_benchmarks(args: argparse.Namespace) -> pd.DataFrame:
    path = Path(args.benchmarks_path)
    if path.exists() and not args.refresh_benchmarks:
        benchmarks = pd.read_parquet(path) if path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path)
    else:
        benchmarks = load_akshare_benchmarks(args.start_date, args.end_date, keys=args.benchmark_keys)
        write_benchmarks(benchmarks, path)
    if benchmarks.empty:
        raise RuntimeError("Benchmark data is empty; refusing quality-clean sensitivity run.")
    return benchmarks


def _assert_real_bars(bars: pd.DataFrame) -> None:
    if bars.empty:
        raise RuntimeError("HS300 bars are empty; refusing quality-clean sensitivity run.")
    sources = {str(value).lower() for value in bars.get("data_source", pd.Series(dtype=str)).dropna().unique()}
    if sources & {"synthetic", "mock", "random", "generated", "sample", "fake"}:
        raise RuntimeError("Refusing to run quality-clean sensitivity on synthetic/mock bars.")


def _render_markdown(comparison: pd.DataFrame) -> str:
    note = (
        "Real AKShare HS300 quality-clean sensitivity. Scenarios remove flagged rows from `selected`/`eligible` only; "
        "the original HS300 result is not overwritten."
    )
    return "# HS300 Quality-Clean Sensitivity Real AKShare\n\n" + note + "\n\n" + comparison.to_markdown(index=False) + "\n"


def _remove_dir_checked(path: Path) -> None:
    root = ROOT.resolve()
    target = path.resolve()
    if not str(target).lower().startswith(str(root).lower()) or target == root:
        raise RuntimeError(f"Refusing to remove unsafe path: {target}")
    shutil.rmtree(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bars-path", default="data/hs300_current_2018_2026_bars.parquet")
    parser.add_argument("--bars-output-dir", default="data/quality_clean")
    parser.add_argument("--qlib-base-dir", default="data/qlib_hs300_quality_clean_2018_2026")
    parser.add_argument("--output-dir", default="reports/hs300_quality_clean_sensitivity_2018_2026")
    parser.add_argument("--benchmarks-path", default="data/benchmarks_2018_2026.parquet")
    parser.add_argument("--benchmark-key", choices=sorted(QLIB_BENCHMARK_SYMBOLS), default="hs300")
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--benchmark-keys", nargs="+", choices=sorted(QLIB_BENCHMARK_SYMBOLS), default=["hs300", "csi500", "csi1000"])
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default="2026-06-24")
    parser.add_argument("--train-start-date", default="2018-01-01")
    parser.add_argument("--train-end-date", default="2022-12-31")
    parser.add_argument("--valid-start-date", default="2023-01-01")
    parser.add_argument("--valid-end-date", default="2024-12-31")
    parser.add_argument("--test-start-date", default="2025-01-01")
    parser.add_argument("--market", default="all")
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--n-drop", type=int, default=10)
    parser.add_argument("--account", type=float, default=100_000_000)
    parser.add_argument("--open-cost", type=float, default=0.00031)
    parser.add_argument("--close-cost", type=float, default=0.00081)
    parser.add_argument("--min-cost", type=float, default=5.0)
    parser.add_argument("--limit-threshold", type=float, default=0.095)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--qlib-kernels", type=int, default=1)
    parser.add_argument("--joblib-backend", default="threading")
    parser.add_argument("--mlruns-dir", default="mlruns")
    parser.add_argument("--refresh-qlib", action="store_true")
    parser.add_argument("--refresh-benchmarks", action="store_true")
    parser.add_argument("--execute", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--comparison-csv", default="reports/hs300_quality_clean_sensitivity_real.csv")
    parser.add_argument("--comparison-md", default="reports/hs300_quality_clean_sensitivity_real.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
