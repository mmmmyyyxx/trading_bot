"""Run an Alpha158 baseline for one expanded A-share universe."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.benchmarks import QLIB_BENCHMARK_SYMBOLS, dump_benchmarks_to_qlib, load_akshare_benchmarks, write_benchmarks
from ashare_adapter.config import UniverseConfig
from ashare_adapter.data_quality import write_data_quality_report, write_qlib_quality_sidecars
from ashare_adapter.diagnostics import benchmark_comparison
from ashare_adapter.exposure import write_exposure_diagnostics
from ashare_adapter.industry_metadata import write_industry_coverage_report
from ashare_adapter.manifest import build_run_manifest
from ashare_adapter.qlib_converter import dump_qlib_bin, ensure_future_calendar, read_bars
from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers
from ashare_adapter.result_export import export_alpha158_results
from ashare_adapter.active_exposure import write_active_attribution
from scripts.build_expanded_universe import build_universe
from scripts.export_qlib_records import export_records
from scripts.run_alpha158_pipeline import run_qrun, write_runtime_config
from scripts.run_rolling_baselines import parse_qrun_log, resolve_run_dir
from scripts.update_2018_2026_cache import update_cache


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    qlib_dir = Path(args.qlib_dir)
    bars_path = Path(args.bars_path)

    if args.symbols_file:
        symbols_file = Path(args.symbols_file)
        symbols = _read_symbols(symbols_file)
        universe_meta = {
            "universe_name": args.universe_name,
            "universe_mode": args.universe_mode,
            "selected_mode": args.selected_mode,
            "candidate_pool_size": args.candidate_pool_size,
            "dynamic_liquidity_top_n": args.dynamic_liquidity_top_n,
            "requested_symbols": len(symbols),
            "symbols_file": str(symbols_file),
            "metadata_file": None,
            "caveats": ["Symbols were supplied from an existing file; verify its construction separately."],
        }
    else:
        universe_meta = build_universe(
            universe_name=args.universe_name,
            output_dir=args.universe_output_dir,
            cache_dir=args.cache_dir,
            metadata_cache=args.metadata_cache,
            refresh_constituents=args.refresh_constituents,
            candidate_pool_size=args.candidate_pool_size,
            max_symbols=args.max_symbols,
        )
        symbols_file = Path(universe_meta["symbols_file"])

    cache_summary = update_cache(
        symbols_file=symbols_file,
        output_bars=bars_path,
        existing_bars=args.existing_bars,
        start_date=args.start_date,
        end_date=args.end_date,
        universe_name=args.universe_name,
        metadata_cache=args.metadata_cache,
        refresh_metadata=args.refresh_metadata,
        refresh_bars=args.refresh_bars,
        adjust=args.adjust,
        workers=args.workers,
        retry=args.retry,
        sleep=args.sleep,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
        download_summary=output_dir / "download_summary.json",
        missing_symbols=output_dir / "missing_symbols.csv",
    )
    bars = read_bars(bars_path)
    _write_universe_diagnostics(bars, output_dir / "universe_diagnostics.csv", args.dynamic_liquidity_top_n)

    data_quality_summary = write_data_quality_report(
        bars,
        output_dir=output_dir / "data_quality",
        selected_col="selected",
        fail_on_error=False,
    )
    if data_quality_summary.get("quality_status") == "failed" and not args.allow_low_quality_data:
        _write_failure_report(
            output_dir,
            "data_quality_failed",
            f"Data quality audit failed: {data_quality_summary.get('failure_reason', 'unknown')}",
            extra={"data_quality": data_quality_summary, "download_summary": cache_summary},
        )
        raise RuntimeError(
            "Data quality audit failed; refusing to generate Qlib data or formal reports. "
            "Use --allow-low-quality-data only for explicitly caveated diagnostics."
        )

    industry_quality_summary = write_industry_coverage_report(
        bars,
        output_dir=output_dir / "industry",
        positions=None,
        selected_col="selected",
    )

    if args.refresh_qlib and qlib_dir.exists():
        _remove_dir_checked(qlib_dir)
    universe_config = UniverseConfig(
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
    )
    if args.refresh_qlib or not (qlib_dir / "features").exists():
        dump_qlib_bin(bars, qlib_dir, universe_config, market=args.market)
        write_qlib_quality_sidecars(
            qlib_dir,
            bars,
            data_quality_summary=data_quality_summary,
            industry_quality_summary=industry_quality_summary,
        )
    ensure_future_calendar(qlib_dir)

    benchmarks_path = Path(args.benchmarks_path)
    if benchmarks_path.exists() and not args.refresh_benchmarks:
        benchmarks = pd.read_parquet(benchmarks_path) if benchmarks_path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(benchmarks_path)
        _validate_real_benchmarks(benchmarks, args.benchmark_keys)
    else:
        benchmarks = load_akshare_benchmarks(args.start_date, args.end_date, keys=args.benchmark_keys)
        _validate_real_benchmarks(benchmarks, args.benchmark_keys)
        write_benchmarks(benchmarks, benchmarks_path)
    dump_benchmarks_to_qlib(benchmarks, qlib_dir, market="benchmarks")

    runtime_config = output_dir / "alpha158_lgb_runtime.yaml"
    qrun_log = output_dir / "qrun_alpha158.log"
    runtime_args = _runtime_args(args, qlib_dir)
    write_runtime_config(runtime_args, runtime_config)
    if args.execute:
        run_qrun(runtime_config, qrun_log)
        run_info = parse_qrun_log(qrun_log.read_text(encoding="utf-8", errors="ignore"))
        run_dir = resolve_run_dir("mlruns", run_info)
        summary = export_alpha158_results(
            run_dir=run_dir,
            output_dir=output_dir,
            bars_path=bars_path,
            benchmarks_path=benchmarks_path,
            qrun_log=qrun_log,
            universe_diagnostics_path=output_dir / "universe_diagnostics.csv",
            requested_symbols=_read_symbols(symbols_file),
            data_quality_summary=data_quality_summary,
            industry_quality_summary=industry_quality_summary,
            **real_data_markers(),
        )
        manifest = build_run_manifest(
            summary_path=output_dir / "summary.json",
            runtime_config_path=runtime_config,
            universe_diagnostics_path=output_dir / "universe_diagnostics.csv",
            symbols_file=symbols_file,
            output_path=output_dir / "run_manifest.json",
            data_quality_summary=data_quality_summary,
            industry_quality_summary=industry_quality_summary,
        )
        records_dir = output_dir / "qlib_records"
        exported = export_records(summary["run"]["run_dir"], records_dir)
        exposure_dir = output_dir / "exposure"
        if {"equity", "positions"}.issubset(exported):
            equity = pd.read_csv(exported["equity"])
            positions = pd.read_csv(exported["positions"])
            industry_quality_summary = write_industry_coverage_report(
                bars,
                output_dir=output_dir / "industry",
                positions=positions,
                selected_col="selected",
            )
            summary = _refresh_quality_sections(output_dir / "summary.json", data_quality_summary, industry_quality_summary)
            manifest = build_run_manifest(
                summary_path=output_dir / "summary.json",
                runtime_config_path=runtime_config,
                universe_diagnostics_path=output_dir / "universe_diagnostics.csv",
                symbols_file=symbols_file,
                output_path=output_dir / "run_manifest.json",
                data_quality_summary=data_quality_summary,
                industry_quality_summary=industry_quality_summary,
            )
            write_qlib_quality_sidecars(
                qlib_dir,
                bars,
                data_quality_summary=data_quality_summary,
                industry_quality_summary=industry_quality_summary,
            )
            benchmark_comparison(equity, benchmarks).to_csv(output_dir / "benchmark_comparison.csv", index=False)
            write_exposure_diagnostics(
                output_dir=exposure_dir,
                bars=bars,
                equity=equity,
                positions=positions,
                benchmarks=benchmarks,
                benchmark_symbols=_read_symbols(symbols_file),
            )
            if args.run_active_attribution:
                write_active_attribution(
                    output_dir=output_dir / "active_attribution",
                    bars=bars,
                    equity=equity,
                    positions=positions,
                    benchmarks=benchmarks,
                    benchmark_symbols=_read_symbols(symbols_file),
                )
        _write_experiment_metadata(output_dir, args, universe_meta, cache_summary, manifest, data_quality_summary, industry_quality_summary)
        _update_universe_comparison(args, output_dir, summary, manifest)
    else:
        _write_experiment_metadata(output_dir, args, universe_meta, cache_summary, None, data_quality_summary, industry_quality_summary)
    print(f"Wrote universe expansion output: {output_dir}")


def _runtime_args(args: argparse.Namespace, qlib_dir: Path) -> argparse.Namespace:
    values = vars(args).copy()
    values.update(
        {
            "qlib_dir": str(qlib_dir),
            "benchmark": args.benchmark or QLIB_BENCHMARK_SYMBOLS[args.benchmark_key],
            "fit_start_date": args.train_start_date,
            "fit_end_date": args.train_end_date,
            "use_selected_filter": True,
            "qlib_kernels": args.qlib_kernels,
            "joblib_backend": args.joblib_backend,
            "learning_rate": args.learning_rate,
        }
    )
    return argparse.Namespace(**values)


def _write_universe_diagnostics(bars: pd.DataFrame, path: Path, configured_top_n: int | None) -> pd.DataFrame:
    from ashare_adapter.universe import build_universe_diagnostics

    diagnostics = build_universe_diagnostics(bars, configured_top_n)
    path.parent.mkdir(parents=True, exist_ok=True)
    diagnostics.to_csv(path, index=False)
    return diagnostics


def _write_experiment_metadata(
    output_dir: Path,
    args: argparse.Namespace,
    universe_meta: dict,
    cache_summary: dict,
    manifest: dict | None,
    data_quality_summary: dict | None = None,
    industry_quality_summary: dict | None = None,
) -> None:
    payload = {
        **real_data_markers(),
        "universe": universe_meta,
        "cache": cache_summary,
        "manifest": manifest,
        "data_quality": data_quality_summary or {},
        "industry_quality": industry_quality_summary or {},
        "run": {
            "execute": bool(args.execute),
            "model": "Alpha158 + LightGBM",
            "scenario": args.scenario_name,
            "benchmark_key": args.benchmark_key,
            "benchmark_symbol": args.benchmark or QLIB_BENCHMARK_SYMBOLS[args.benchmark_key],
            "topk": args.topk,
            "n_drop": args.n_drop,
            "rebalance_step": args.rebalance_step,
            "exchange_mode": "ashare_exchange" if args.use_ashare_exchange else "uniform_limit_threshold",
            "limit_price_buffer": args.limit_price_buffer if args.use_ashare_exchange else None,
        },
        "caveats": [
            "Do not interpret current-constituent experiments as historical constituent backtests.",
            "Do not interpret eligible_only as dynamic liquidity top-N.",
            "Qlib uses a simplified uniform limit_threshold, not full A-share trading constraints.",
            "Industry metadata coverage must be checked before industry attribution is trusted.",
        ],
    }
    (output_dir / "experiment_metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _refresh_quality_sections(
    summary_path: Path,
    data_quality_summary: dict,
    industry_quality_summary: dict,
) -> dict:
    from ashare_adapter.result_export import _render_markdown, _sanitize

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["data_quality"] = data_quality_summary
    summary["industry_quality"] = industry_quality_summary
    sanitized = _sanitize(summary)
    summary_path.write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    summary_path.with_suffix(".md").write_text(_render_markdown(sanitized), encoding="utf-8")
    return sanitized


def _validate_real_benchmarks(benchmarks: pd.DataFrame, required_keys: list[str]) -> None:
    if benchmarks.empty:
        raise RuntimeError("AKShare benchmark download returned no rows; refusing to continue.")
    if "benchmark" not in benchmarks.columns:
        raise RuntimeError("Benchmark data is missing the benchmark column; refusing to continue.")
    missing = sorted(set(required_keys) - set(benchmarks["benchmark"].dropna().astype(str)))
    if missing:
        raise RuntimeError(f"AKShare benchmark data missing required keys {missing}; refusing to continue.")
    if "source" not in benchmarks.columns or not benchmarks["source"].dropna().astype(str).str.lower().eq("akshare").all():
        raise RuntimeError("Benchmark data is not fully tagged as source=akshare; refusing to continue.")


def _write_failure_report(output_dir: Path, status: str, reason: str, extra: dict | None = None) -> None:
    payload = {
        **real_data_markers(),
        "status": status,
        "failure_reason": reason,
        "extra": extra or {},
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "failure_report.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_universe_comparison(
    args: argparse.Namespace,
    output_dir: Path,
    summary: dict,
    manifest: dict,
) -> None:
    row = _comparison_row(args, output_dir, summary, manifest)
    csv_path = Path(args.comparison_csv)
    md_path = Path(args.comparison_md)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if csv_path.exists():
        comparison = pd.read_csv(csv_path)
        key_cols = ["universe_name", "model", "benchmark", "test_start", "test_end"]
        if "scenario" in comparison.columns and row.get("scenario") is not None:
            key_cols.append("scenario")
        mask = pd.Series(False, index=comparison.index)
        if set(key_cols).issubset(comparison.columns):
            mask = (
                (comparison["universe_name"] == row["universe_name"])
                & (comparison["model"] == row["model"])
                & (comparison["benchmark"] == row["benchmark"])
                & (comparison["test_start"] == row["test_start"])
                & (comparison["test_end"] == row["test_end"])
            )
        comparison = comparison.loc[~mask].copy()
        comparison = pd.concat([comparison, pd.DataFrame([row])], ignore_index=True)
    else:
        comparison = pd.DataFrame([row])
    comparison.to_csv(csv_path, index=False)
    md_path.write_text("# Universe Expansion Comparison\n\n" + comparison.to_markdown(index=False) + "\n", encoding="utf-8")


def _comparison_row(args: argparse.Namespace, output_dir: Path, summary: dict, manifest: dict) -> dict[str, object]:
    signal = summary.get("signal", {})
    portfolio = summary.get("portfolio", {})
    data = manifest.get("data", {})
    data_quality = manifest.get("data_quality", {})
    industry_quality = manifest.get("industry_quality", {})
    universe = manifest.get("universe", {})
    segments = manifest.get("segments", {})
    beta = _read_beta(output_dir / "exposure" / "beta_exposure.csv")
    unknown_weight = _read_unknown_weight(output_dir / "exposure" / "industry_exposure_summary.csv")
    missing = universe.get("missing_symbols") or []
    sufficiency = manifest.get("data_sufficiency", {})
    test = segments.get("test") or [None, None]
    return {
        "universe_name": args.universe_name,
        "scenario": args.scenario_name,
        "data_type": data.get("data_type"),
        "synthetic_data": data.get("synthetic_data"),
        "mock_data": data.get("mock_data"),
        "universe_mode": args.universe_mode,
        "selected_mode": universe.get("selected_mode", args.selected_mode),
        "dynamic_liquidity_top_n": universe.get("dynamic_liquidity_top_n", args.dynamic_liquidity_top_n),
        "candidate_pool_size": args.candidate_pool_size,
        "requested_symbols": universe.get("requested_symbols"),
        "actual_symbols": universe.get("actual_symbols"),
        "missing_symbols_count": len(missing),
        "avg_selected_universe_count": universe.get("avg_selected_universe_count"),
        "min_selected_universe_count": universe.get("min_selected_universe_count"),
        "max_selected_universe_count": universe.get("max_selected_universe_count"),
        "candidate_symbol_coverage": sufficiency.get("candidate_symbol_coverage"),
        "selected_top_n_reached": sufficiency.get("selected_top_n_reached"),
        "data_sufficient_for_dynamic_top_n": sufficiency.get("data_sufficient_for_dynamic_top_n"),
        "model": _model_name(summary, args.scenario_name),
        "benchmark": manifest.get("portfolio", {}).get("benchmark"),
        "topk": args.topk,
        "n_drop": args.n_drop,
        "rebalance_step": args.rebalance_step,
        "exchange_mode": "ashare_exchange" if args.use_ashare_exchange else "uniform_limit_threshold",
        "limit_price_buffer": args.limit_price_buffer if args.use_ashare_exchange else None,
        "train_start": (segments.get("train") or [None, None])[0],
        "train_end": (segments.get("train") or [None, None])[1],
        "valid_start": (segments.get("valid") or [None, None])[0],
        "valid_end": (segments.get("valid") or [None, None])[1],
        "test_start": test[0],
        "test_end": test[1],
        "is_ytd": bool(test[1] and str(test[1]).startswith("2026-") and not str(test[1]).endswith("12-31")),
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
        "data_quality_status": data_quality.get("quality_status"),
        "industry_quality_status": industry_quality.get("industry_quality_status", industry_quality.get("quality_status")),
        "beta_hs300": beta.get("hs300"),
        "beta_csi500": beta.get("csi500"),
        "beta_csi1000": beta.get("csi1000"),
        "industry_unknown_weight": unknown_weight,
        "caveats": "; ".join(manifest.get("caveats", [])),
        "summary_path": str(output_dir / "summary.md"),
        "manifest_path": str(output_dir / "run_manifest.json"),
    }


def _model_name(summary: dict, scenario_name: str | None) -> str:
    base = summary.get("model", {}).get("name", "Alpha158 + LightGBM")
    return f"{base} ({scenario_name})" if scenario_name else base


def _read_beta(path: Path) -> dict[str, float]:
    if not path.exists():
        return {}
    frame = pd.read_csv(path)
    if not {"benchmark", "beta"}.issubset(frame.columns):
        return {}
    return dict(zip(frame["benchmark"].astype(str), pd.to_numeric(frame["beta"], errors="coerce")))


def _read_unknown_weight(path: Path) -> float | None:
    if not path.exists():
        return None
    frame = pd.read_csv(path)
    if not {"industry", "avg_weight"}.issubset(frame.columns):
        return None
    unknown = frame[frame["industry"].fillna("").astype(str).str.lower() == "unknown"]
    if unknown.empty:
        return 0.0
    return float(pd.to_numeric(unknown["avg_weight"], errors="coerce").fillna(0.0).iloc[0])


def _read_symbols(path: str | Path) -> list[str]:
    return [
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _remove_dir_checked(path: Path) -> None:
    root = ROOT.resolve()
    target = path.resolve()
    if not str(target).lower().startswith(str(root).lower()) or target == root:
        raise RuntimeError(f"Refusing to remove unsafe path: {target}")
    import shutil

    shutil.rmtree(target)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-name", required=True)
    parser.add_argument("--scenario-name", default=None)
    parser.add_argument("--universe-mode", default="current_constituent")
    parser.add_argument("--selected-mode", default="eligible_only")
    parser.add_argument("--symbols-file", default=None)
    parser.add_argument("--index-symbols", nargs="*", default=None)
    parser.add_argument("--candidate-pool-size", type=int, default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default="2026-06-24")
    parser.add_argument("--train-start-date", default="2018-01-01")
    parser.add_argument("--train-end-date", default="2022-12-31")
    parser.add_argument("--valid-start-date", default="2023-01-01")
    parser.add_argument("--valid-end-date", default="2024-12-31")
    parser.add_argument("--test-start-date", default="2025-01-01")
    parser.add_argument("--benchmark-key", choices=sorted(QLIB_BENCHMARK_SYMBOLS), default="hs300")
    parser.add_argument("--benchmark", default=None)
    parser.add_argument("--benchmark-keys", nargs="+", choices=sorted(QLIB_BENCHMARK_SYMBOLS), default=["hs300", "csi500", "csi1000"])
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--qlib-dir", required=True)
    parser.add_argument("--bars-path", required=True)
    parser.add_argument("--existing-bars", default=None)
    parser.add_argument("--benchmarks-path", default="data/benchmarks_2018_2026.parquet")
    parser.add_argument("--universe-output-dir", default="data/cache/expanded_universes")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--market", default="all")
    parser.add_argument("--refresh-constituents", action="store_true")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--refresh-bars", action="store_true")
    parser.add_argument("--refresh-qlib", action="store_true")
    parser.add_argument("--refresh-benchmarks", action="store_true")
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--n-drop", type=int, default=10)
    parser.add_argument("--account", type=float, default=100_000_000)
    parser.add_argument("--open-cost", type=float, default=0.00031)
    parser.add_argument("--close-cost", type=float, default=0.00081)
    parser.add_argument("--min-cost", type=float, default=5.0)
    parser.add_argument("--limit-threshold", type=float, default=0.095)
    parser.add_argument("--use-ashare-exchange", action="store_true")
    parser.add_argument("--limit-price-buffer", type=float, default=0.001)
    parser.add_argument("--rebalance-step", type=int, default=1)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--qlib-kernels", type=int, default=1)
    parser.add_argument("--joblib-backend", default="threading")
    parser.add_argument("--execute", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--run-active-attribution", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--allow-low-quality-data", action="store_true")
    parser.add_argument("--comparison-csv", default="reports/universe_expansion_comparison.csv")
    parser.add_argument("--comparison-md", default="reports/universe_expansion_comparison.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
