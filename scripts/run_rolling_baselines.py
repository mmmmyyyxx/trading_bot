"""Generate and optionally run rolling Qlib baseline validations."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.exchange import ashare_exchange_kwargs


ROLLING_WINDOWS = [
    {
        "name": "2018_2022",
        "train": ["2018-01-01", "2020-12-31"],
        "valid": ["2021-01-01", "2021-12-31"],
        "test": ["2022-01-01", "2022-12-31"],
    },
    {
        "name": "2019_2023",
        "train": ["2019-01-01", "2021-12-31"],
        "valid": ["2022-01-01", "2022-12-31"],
        "test": ["2023-01-01", "2023-12-31"],
    },
    {
        "name": "2020_2024",
        "train": ["2020-01-01", "2022-12-31"],
        "valid": ["2023-01-01", "2023-12-31"],
        "test": ["2024-01-01", "2024-12-31"],
    },
]

MODEL_SPECS = {
    "alpha158_lgb": {"kind": "alpha158", "label_horizon": 1, "display": "Alpha158 + LightGBM"},
    "reversal_lowvol_1d": {"kind": "reversal", "label_horizon": 1, "display": "Reversal + LowVol 1d"},
    "reversal_lowvol_5d": {"kind": "reversal", "label_horizon": 5, "display": "Reversal + LowVol 5d"},
    "reversal_lowvol_20d": {"kind": "reversal", "label_horizon": 20, "display": "Reversal + LowVol 20d"},
}


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for window in ROLLING_WINDOWS:
        for model_name in args.models:
            spec = MODEL_SPECS[model_name]
            run_dir = output_dir / window["name"] / model_name
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
                rebalance_step=args.rebalance_step,
            )
            config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
            row = _base_row(window, model_name, spec, config_path, log_path, args.benchmark, args)
            if args.execute:
                run_info = run_qrun(config_path, log_path)
                run_dir = resolve_run_dir(args.mlruns_dir, run_info)
                row.update(read_run_metrics(run_dir))
                row.update(run_info)
            rows.append(row)

    comparison = pd.DataFrame(rows)
    comparison_path = Path(args.comparison_csv)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    comparison.to_csv(comparison_path, index=False)
    Path(args.comparison_md).write_text(render_markdown(comparison, executed=args.execute), encoding="utf-8")
    print(f"Wrote rolling comparison: {comparison_path}")
    print(f"Wrote rolling comparison md: {args.comparison_md}")


def build_workflow_config(
    provider_uri: str,
    market: str,
    benchmark: str,
    window: dict[str, Any],
    spec: dict[str, Any],
    topk: int,
    n_drop: int,
    account: float,
    open_cost: float,
    close_cost: float,
    min_cost: float,
    limit_threshold: float,
    num_threads: int,
    use_ashare_exchange: bool = False,
    limit_price_buffer: float = 0.001,
    rebalance_step: int = 1,
) -> dict[str, Any]:
    """Build a Qlib workflow config for one rolling window/model."""

    start_time = window["train"][0]
    end_time = window["test"][1]
    qlib_init = {
        "provider_uri": provider_uri,
        "region": "cn",
        "kernels": 1,
        "joblib_backend": "threading",
    }
    if use_ashare_exchange:
        exchange_kwargs = ashare_exchange_kwargs(
            start_time=window["test"][0],
            end_time=window["test"][1],
            codes=market,
            deal_price="close",
            open_cost=open_cost,
            close_cost=close_cost,
            min_cost=min_cost,
            limit_threshold=limit_threshold,
            limit_price_buffer=limit_price_buffer,
        )
    else:
        exchange_kwargs = {
            "limit_threshold": limit_threshold,
            "deal_price": "close",
            "open_cost": open_cost,
            "close_cost": close_cost,
            "min_cost": min_cost,
        }
    strategy = _strategy_config(topk=topk, n_drop=n_drop, rebalance_step=rebalance_step)
    port_analysis_config = {
        "strategy": strategy,
        "backtest": {
            "start_time": window["test"][0],
            "end_time": window["test"][1],
            "account": account,
            "benchmark": benchmark,
            "exchange_kwargs": exchange_kwargs,
        },
    }
    if spec["kind"] == "alpha158":
        data_handler_config = {
            "start_time": start_time,
            "end_time": end_time,
            "fit_start_time": window["train"][0],
            "fit_end_time": window["train"][1],
            "instruments": market,
            "filter_pipe": [_selected_filter(start_time, end_time)],
        }
        model = {
            "class": "LGBModel",
            "module_path": "qlib.contrib.model.gbdt",
            "kwargs": {
                "loss": "mse",
                "colsample_bytree": 0.8879,
                "learning_rate": 0.05,
                "subsample": 0.8789,
                "lambda_l1": 205.6999,
                "lambda_l2": 580.9768,
                "max_depth": 8,
                "num_leaves": 210,
                "num_threads": num_threads,
            },
        }
        handler = {"class": "Alpha158", "module_path": "qlib.contrib.data.handler", "kwargs": data_handler_config}
    else:
        horizon = int(spec["label_horizon"])
        label_offset = horizon + 1
        data_handler_config = {
            "start_time": start_time,
            "end_time": end_time,
            "instruments": market,
            "infer_processors": [
                {"class": "ProcessInf"},
                {"class": "Fillna", "kwargs": {"fields_group": "feature", "fill_value": 0}},
            ],
            "learn_processors": [
                {"class": "ProcessInf"},
                {"class": "Fillna", "kwargs": {"fields_group": "feature", "fill_value": 0}},
                {"class": "DropnaLabel"},
                {"class": "CSRankNorm", "kwargs": {"fields_group": "label"}},
            ],
            "data_loader": {
                "class": "QlibDataLoader",
                "module_path": "qlib.data.dataset.loader",
                "kwargs": {
                    "config": {
                        "feature": [
                            [
                                "-1 * ($close / Ref($close, 20) - 1)",
                                "-1 * Std($close / Ref($close, 1) - 1, 60)",
                            ],
                            ["short_term_reversal", "low_volatility"],
                        ],
                        "label": [[f"Ref($close, -{label_offset}) / Ref($close, -1) - 1"], ["LABEL0"]],
                    },
                    "filter_pipe": [_selected_filter(start_time, end_time)],
                },
            },
        }
        model = {
            "class": "LinearModel",
            "module_path": "qlib.contrib.model.linear",
            "kwargs": {"estimator": "ridge", "alpha": 1.0},
        }
        handler = {"class": "DataHandlerLP", "module_path": "qlib.data.dataset.handler", "kwargs": data_handler_config}

    return {
        "qlib_init": qlib_init,
        "market": market,
        "benchmark": benchmark,
        "task": {
            "model": model,
            "dataset": {
                "class": "DatasetH",
                "module_path": "qlib.data.dataset",
                "kwargs": {
                    "handler": handler,
                    "segments": {
                        "train": window["train"],
                        "valid": window["valid"],
                        "test": window["test"],
                    },
                },
            },
            "record": [
                {
                    "class": "SignalRecord",
                    "module_path": "qlib.workflow.record_temp",
                    "kwargs": {"model": "<MODEL>", "dataset": "<DATASET>"},
                },
                {
                    "class": "SigAnaRecord",
                    "module_path": "qlib.workflow.record_temp",
                    "kwargs": {"ana_long_short": False, "ann_scaler": 252},
                },
                {
                    "class": "PortAnaRecord",
                    "module_path": "qlib.workflow.record_temp",
                    "kwargs": {"config": port_analysis_config},
                },
            ],
        },
    }


def run_qrun(config_path: Path, log_path: Path) -> dict[str, str]:
    """Run qrun and return the recorder and experiment ids."""

    qrun = shutil.which("qrun") or str(Path(sys.executable).parent / "Scripts" / "qrun.exe")
    env = dict(os.environ)
    env.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(ROOT) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    for key in ["OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"]:
        env.setdefault(key, "1")
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run([qrun, str(config_path)], stdout=log, stderr=subprocess.STDOUT, check=True, env=env)
    text = log_path.read_text(encoding="utf-8", errors="ignore")
    run_info = parse_qrun_log(text)
    if not run_info.get("run_id"):
        raise RuntimeError(f"Unable to find recorder id in {log_path}")
    return run_info


def parse_qrun_log(text: str) -> dict[str, str]:
    """Parse Qlib qrun log text for MLflow experiment and recorder ids."""

    experiment_id = ""
    experiment_match = re.search(r"Experiment (\d+) starts running", text)
    if experiment_match:
        experiment_id = experiment_match.group(1)
    recorder_match = re.search(r"Recorder ([0-9a-fA-F-]+) starts running(?: under Experiment (\d+))?", text)
    run_id = recorder_match.group(1) if recorder_match else ""
    if recorder_match and recorder_match.group(2):
        experiment_id = recorder_match.group(2)
    return {"experiment_id": experiment_id, "run_id": run_id}


def resolve_run_dir(mlruns_dir: str | Path, run_info: dict[str, str]) -> Path:
    """Resolve an MLflow run directory from parsed qrun ids."""

    root = Path(mlruns_dir)
    run_id = run_info.get("run_id", "")
    experiment_id = run_info.get("experiment_id", "")
    if experiment_id:
        candidate = root / experiment_id / run_id
        if candidate.exists():
            return candidate
    matches = list(root.glob(f"*/{run_id}"))
    if matches:
        return matches[0]
    raise FileNotFoundError(f"Unable to locate MLflow run directory for run_id={run_id!r} under {root}")


def read_run_metrics(run_dir: Path) -> dict[str, Any]:
    """Read metrics needed by the rolling comparison."""

    metrics_dir = run_dir / "metrics"
    metrics = {}
    for metric_file in metrics_dir.iterdir() if metrics_dir.exists() else []:
        if not metric_file.is_file():
            continue
        lines = [line.split() for line in metric_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            metrics[metric_file.name] = float(lines[-1][1])
    report_path = run_dir / "artifacts" / "portfolio_analysis" / "report_normal_1day.pkl"
    turnover = cost = account_total_return = benchmark_total_return = None
    if report_path.exists():
        report = pd.read_pickle(report_path)
        turnover = float(pd.to_numeric(report.get("turnover"), errors="coerce").dropna().mean())
        cost = float(pd.to_numeric(report.get("total_cost"), errors="coerce").dropna().sum())
        if "account" in report.columns and len(report):
            account = pd.to_numeric(report["account"], errors="coerce").dropna()
            if len(account) >= 2 and account.iloc[0] != 0:
                account_total_return = float(account.iloc[-1] / account.iloc[0] - 1.0)
        if "bench" in report.columns:
            bench = pd.to_numeric(report["bench"], errors="coerce").fillna(0.0)
            benchmark_total_return = float((1.0 + bench).prod() - 1.0)
    return {
        "IC": metrics.get("IC"),
        "ICIR": metrics.get("ICIR"),
        "RankIC": metrics.get("Rank IC"),
        "RankICIR": metrics.get("Rank ICIR"),
        "excess_annualized_return_with_cost": metrics.get("1day.excess_return_with_cost.annualized_return"),
        "excess_information_ratio_with_cost": metrics.get("1day.excess_return_with_cost.information_ratio"),
        "excess_max_drawdown_with_cost": metrics.get("1day.excess_return_with_cost.max_drawdown"),
        "account_total_return": account_total_return,
        "benchmark_total_return": benchmark_total_return,
        "turnover": turnover,
        "cost": cost,
    }


def render_markdown(comparison: pd.DataFrame, executed: bool) -> str:
    title = "# Rolling Baseline Comparison\n\n"
    note = "Executed qrun for all rows." if executed else "Dry run: configs generated but qrun was not executed."
    return title + note + "\n\n" + comparison.to_markdown(index=False) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider-uri", default="data/qlib_alpha158_hs300_full")
    parser.add_argument("--mlruns-dir", default="mlruns")
    parser.add_argument("--market", default="all")
    parser.add_argument("--benchmark", default="SH000300")
    parser.add_argument("--output-dir", default="reports/rolling_baselines")
    parser.add_argument("--comparison-csv", default="reports/rolling_baseline_comparison.csv")
    parser.add_argument("--comparison-md", default="reports/rolling_baseline_comparison.md")
    parser.add_argument("--models", nargs="+", choices=sorted(MODEL_SPECS), default=sorted(MODEL_SPECS))
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
    parser.add_argument("--rebalance-step", type=int, default=1)
    return parser.parse_args()


def _base_row(
    window: dict[str, Any],
    model_name: str,
    spec: dict[str, Any],
    config_path: Path,
    log_path: Path,
    benchmark: str,
    args: argparse.Namespace,
) -> dict[str, Any]:
    return {
        "model": spec["display"],
        "model_key": model_name,
        "topk": args.topk,
        "n_drop": args.n_drop,
        "rebalance_step": args.rebalance_step,
        "exchange_mode": "ashare_exchange" if args.use_ashare_exchange else "uniform_limit_threshold",
        "limit_price_buffer": args.limit_price_buffer if args.use_ashare_exchange else None,
        "train_start": window["train"][0],
        "train_end": window["train"][1],
        "valid_start": window["valid"][0],
        "valid_end": window["valid"][1],
        "test_start": window["test"][0],
        "test_end": window["test"][1],
        "benchmark": benchmark,
        "config_path": str(config_path),
        "log_path": str(log_path),
    }


def _strategy_config(topk: int, n_drop: int, rebalance_step: int = 1) -> dict[str, Any]:
    step = max(1, int(rebalance_step or 1))
    if step > 1:
        return {
            "class": "PeriodicTopkDropoutStrategy",
            "module_path": "ashare_adapter.strategy",
            "kwargs": {"signal": "<PRED>", "topk": topk, "n_drop": n_drop, "rebalance_step": step},
        }
    return {
        "class": "TopkDropoutStrategy",
        "module_path": "qlib.contrib.strategy",
        "kwargs": {"signal": "<PRED>", "topk": topk, "n_drop": n_drop},
    }


def _selected_filter(start_time: str, end_time: str) -> dict[str, Any]:
    return {
        "filter_type": "ExpressionDFilter",
        "rule_expression": "$selected > 0.5",
        "filter_start_time": start_time,
        "filter_end_time": end_time,
        "keep": False,
    }


if __name__ == "__main__":
    main()
