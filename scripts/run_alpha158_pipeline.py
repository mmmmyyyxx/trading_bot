"""Prepare AKShare data, dump Qlib format, and run an Alpha158 baseline."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.akshare_downloader import AKShareDownloader
from ashare_adapter.benchmarks import dump_benchmarks_to_qlib, load_akshare_benchmarks, write_benchmarks
from ashare_adapter.config import UniverseConfig
from ashare_adapter.indexes import load_index_constituents, symbols_from_constituents, write_constituents
from ashare_adapter.metadata import normalize_symbol
from ashare_adapter.qlib_converter import dump_qlib_bin, ensure_future_calendar, read_bars, write_bars
from ashare_adapter.result_export import export_alpha158_results
from ashare_adapter.universe import build_dynamic_universe, build_universe_diagnostics


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    bars_path = Path(args.bars_path)
    qlib_dir = Path(args.qlib_dir)
    config_path = output_dir / "alpha158_lgb_runtime.yaml"
    log_path = output_dir / "qrun_alpha158.log"

    symbols = load_symbols(args)
    print(f"Universe symbols: {len(symbols)}")

    universe_config = UniverseConfig(
        exclude_st=args.exclude_st,
        exclude_paused=args.exclude_paused,
        exclude_limit_buy=args.exclude_limit_buy,
        min_listed_days=args.min_listed_days,
        min_amount=args.min_amount,
        liquidity_window=args.liquidity_window,
        dynamic_liquidity_top_n=args.dynamic_liquidity_top_n,
    )

    if bars_path.exists() and not args.refresh_bars:
        bars = read_bars(bars_path)
        print(f"Reusing bars: {bars_path} rows={len(bars)}")
    else:
        downloader = AKShareDownloader(
            metadata_cache_path=args.metadata_cache,
            refresh_metadata=args.refresh_metadata,
            load_metadata=not args.skip_metadata,
        )
        bars = downloader.fetch_bars(
            symbols=symbols,
            start_date=args.start_date,
            end_date=args.end_date,
            adjust=args.adjust,
            workers=args.workers,
            retry=args.retry,
            sleep=args.sleep,
        )
        bars = build_dynamic_universe(bars, universe_config)
        written = write_bars(bars, bars_path)
        print(f"Wrote bars: {written} rows={len(bars)}")

    diagnostics = build_universe_diagnostics(bars, args.dynamic_liquidity_top_n)
    diagnostics_path = output_dir / "universe_diagnostics.csv"
    diagnostics.to_csv(diagnostics_path, index=False)
    print(f"Wrote universe diagnostics: {diagnostics_path}")

    if qlib_dir.exists() and args.refresh_qlib:
        _remove_dir_checked(qlib_dir)
    if not (qlib_dir / "features").exists() or args.refresh_qlib:
        dump_qlib_bin(bars, qlib_dir, universe_config, market=args.market)
        print(f"Wrote Qlib data: {qlib_dir}")
    else:
        print(f"Reusing Qlib data: {qlib_dir}")
    future_calendar = ensure_future_calendar(qlib_dir)
    print(f"Ensured future calendar: {future_calendar}")

    benchmarks_path = Path(args.benchmarks_path)
    if benchmarks_path.exists() and not args.refresh_benchmarks:
        benchmarks = pd.read_parquet(benchmarks_path) if benchmarks_path.suffix.lower() in {".parquet", ".pq"} else pd.read_csv(benchmarks_path)
        print(f"Reusing benchmarks: {benchmarks_path} rows={len(benchmarks)}")
    else:
        benchmarks = load_akshare_benchmarks(args.start_date, args.end_date, keys=["hs300"])
        written_benchmarks = write_benchmarks(benchmarks, benchmarks_path)
        print(f"Wrote benchmarks: {written_benchmarks} rows={len(benchmarks)}")
    dump_benchmarks_to_qlib(benchmarks, qlib_dir, market="benchmarks")

    write_runtime_config(args, config_path)
    print(f"Wrote workflow config: {config_path}")
    run_qrun(config_path, log_path)
    print(f"Wrote qrun log: {log_path}")
    summary = export_alpha158_results(
        output_dir=output_dir,
        bars_path=bars_path,
        benchmarks_path=benchmarks_path,
        qrun_log=log_path,
        requested_symbols=symbols,
    )
    print(f"Wrote Alpha158 summary: {summary['outputs']['summary_md']}")


def load_symbols(args: argparse.Namespace) -> list[str]:
    if args.symbols:
        return [normalize_symbol(symbol) for symbol in args.symbols[: args.max_symbols]]
    if args.symbols_file:
        values = [
            line.strip()
            for line in Path(args.symbols_file).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return [normalize_symbol(symbol) for symbol in values[: args.max_symbols]]

    constituents = load_index_constituents(
        index_symbol=args.index_symbol,
        cache_path=args.constituents_cache,
        refresh=args.refresh_constituents,
        max_symbols=args.max_symbols,
    )
    if args.constituents_output:
        write_constituents(constituents, args.constituents_output)
    return symbols_from_constituents(constituents, max_symbols=args.max_symbols)


def write_runtime_config(args: argparse.Namespace, output_path: Path) -> None:
    config = {
        "qlib_init": {
            "provider_uri": str(Path(args.qlib_dir).as_posix()),
            "region": "cn",
            "kernels": args.qlib_kernels,
            "joblib_backend": args.joblib_backend,
        },
        "market": args.market,
        "benchmark": "SH000300",
        "data_handler_config": {
            "start_time": args.start_date,
            "end_time": args.end_date,
            "fit_start_time": args.fit_start_date,
            "fit_end_time": args.fit_end_date,
            "instruments": args.market,
        },
    }
    data_handler_config = config["data_handler_config"]
    if args.use_selected_filter:
        data_handler_config["filter_pipe"] = [
            {
                "filter_type": "ExpressionDFilter",
                "rule_expression": "$selected > 0.5",
                "filter_start_time": args.start_date,
                "filter_end_time": args.end_date,
                "keep": False,
            }
        ]
    port_analysis_config = {
        "strategy": {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy",
            "kwargs": {"signal": "<PRED>", "topk": args.topk, "n_drop": args.n_drop},
        },
        "backtest": {
            "start_time": args.test_start_date,
            "end_time": args.end_date,
            "account": args.account,
            "benchmark": "SH000300",
            "exchange_kwargs": {
                "limit_threshold": 0.095,
                "deal_price": "close",
                "open_cost": args.open_cost,
                "close_cost": args.close_cost,
                "min_cost": args.min_cost,
            },
        },
    }
    config["task"] = {
        "model": {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": args.learning_rate,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": args.num_threads,
            },
        },
        "dataset": {
            "class": "DatasetH",
            "module_path": "qlib.data.dataset",
            "kwargs": {
                "handler": {
                    "class": "Alpha158",
                    "module_path": "qlib.contrib.data.handler",
                    "kwargs": data_handler_config,
                },
                "segments": {
                    "train": [args.train_start_date, args.train_end_date],
                    "valid": [args.valid_start_date, args.valid_end_date],
                    "test": [args.test_start_date, args.end_date],
                },
            },
        },
        "record": [
            {"class": "SignalRecord", "module_path": "qlib.workflow.record_temp", "kwargs": {"model": "<MODEL>", "dataset": "<DATASET>"}},
            {"class": "SigAnaRecord", "module_path": "qlib.workflow.record_temp", "kwargs": {"ana_long_short": False, "ann_scaler": 252}},
            {"class": "PortAnaRecord", "module_path": "qlib.workflow.record_temp", "kwargs": {"config": port_analysis_config}},
        ],
    }
    with output_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(config, fh, sort_keys=False)


def run_qrun(config_path: Path, log_path: Path) -> None:
    executable = Path(sys.executable)
    candidates = [
        shutil.which("qrun"),
        str(executable.with_name("qrun.exe")),
        str(executable.parent / "Scripts" / "qrun.exe"),
    ]
    qrun = next((candidate for candidate in candidates if candidate and Path(candidate).exists()), "")
    if not qrun:
        raise RuntimeError("qrun not found on PATH. Run inside the ql conda environment.")
    with log_path.open("w", encoding="utf-8") as log:
        env = dict(**os.environ)
        env.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
        env.setdefault("PYTHONIOENCODING", "utf-8")
        env.setdefault("OPENBLAS_NUM_THREADS", "1")
        env.setdefault("OMP_NUM_THREADS", "1")
        env.setdefault("MKL_NUM_THREADS", "1")
        env.setdefault("NUMEXPR_NUM_THREADS", "1")
        subprocess.run([qrun, str(config_path)], stdout=log, stderr=subprocess.STDOUT, check=True, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2018-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--train-start-date", default="2018-01-01")
    parser.add_argument("--train-end-date", default="2021-12-31")
    parser.add_argument("--valid-start-date", default="2022-01-01")
    parser.add_argument("--valid-end-date", default="2022-12-31")
    parser.add_argument("--test-start-date", default="2023-01-01")
    parser.add_argument("--fit-start-date", default="2018-01-01")
    parser.add_argument("--fit-end-date", default="2021-12-31")
    parser.add_argument("--index-symbol", default="000300")
    parser.add_argument("--symbols", nargs="+", default=None)
    parser.add_argument("--symbols-file", default=None)
    parser.add_argument("--max-symbols", type=int, default=80)
    parser.add_argument("--constituents-cache", default="data/cache/hs300_constituents.parquet")
    parser.add_argument("--constituents-output", default=None)
    parser.add_argument("--refresh-constituents", action="store_true")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--retry", type=int, default=2)
    parser.add_argument("--sleep", type=float, default=0.05)
    parser.add_argument("--adjust", default="qfq")
    parser.add_argument("--bars-path", default="data/alpha158_hs300_bars.parquet")
    parser.add_argument("--benchmarks-path", default="data/benchmarks.parquet")
    parser.add_argument("--qlib-dir", default="data/qlib_alpha158_hs300")
    parser.add_argument("--output-dir", default="reports/alpha158_hs300")
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--market", default="all")
    parser.add_argument("--refresh-metadata", action="store_true")
    parser.add_argument("--skip-metadata", action="store_true")
    parser.add_argument("--refresh-bars", action="store_true")
    parser.add_argument("--refresh-benchmarks", action="store_true")
    parser.add_argument("--refresh-qlib", action="store_true")
    parser.add_argument("--exclude-st", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-paused", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--exclude-limit-buy", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--min-listed-days", type=int, default=120)
    parser.add_argument("--min-amount", type=float, default=10_000_000.0)
    parser.add_argument("--liquidity-window", type=int, default=20)
    parser.add_argument("--dynamic-liquidity-top-n", type=int, default=None)
    parser.add_argument("--use-selected-filter", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--topk", type=int, default=20)
    parser.add_argument("--n-drop", type=int, default=4)
    parser.add_argument("--account", type=float, default=100_000_000)
    parser.add_argument("--open-cost", type=float, default=0.00031)
    parser.add_argument("--close-cost", type=float, default=0.00081)
    parser.add_argument("--min-cost", type=float, default=5.0)
    parser.add_argument("--learning-rate", type=float, default=0.05)
    parser.add_argument("--num-threads", type=int, default=8)
    parser.add_argument("--qlib-kernels", type=int, default=1)
    parser.add_argument("--joblib-backend", default="threading")
    return parser.parse_args()


def _remove_dir_checked(path: Path) -> None:
    root = ROOT.resolve()
    target = path.resolve()
    if not str(target).lower().startswith(str(root).lower()):
        raise RuntimeError(f"Refusing to delete outside project: {target}")
    if target == root:
        raise RuntimeError("Refusing to delete project root.")
    shutil.rmtree(target)


if __name__ == "__main__":
    main()
