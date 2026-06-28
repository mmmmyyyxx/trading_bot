"""Run portfolio-layer sensitivity checks from an existing real Qlib prediction."""

from __future__ import annotations

import argparse
import json
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import qlib
from qlib.contrib.evaluate import backtest_daily

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.exchange import ashare_exchange_kwargs
from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


TURNOVER_SPECS = [
    {"name": "topk50_drop1", "topk": 50, "n_drop": 1, "rebalance_step": 1},
    {"name": "topk50_drop3", "topk": 50, "n_drop": 3, "rebalance_step": 1},
    {"name": "topk50_drop5", "topk": 50, "n_drop": 5, "rebalance_step": 1},
    {"name": "topk50_drop10", "topk": 50, "n_drop": 10, "rebalance_step": 1},
    {"name": "topk100_drop1", "topk": 100, "n_drop": 1, "rebalance_step": 1},
    {"name": "topk100_drop3", "topk": 100, "n_drop": 3, "rebalance_step": 1},
    {"name": "topk100_drop5", "topk": 100, "n_drop": 5, "rebalance_step": 1},
    {"name": "topk100_drop10", "topk": 100, "n_drop": 10, "rebalance_step": 1},
    {"name": "weekly_rebalance_topk50_drop10", "topk": 50, "n_drop": 10, "rebalance_step": 5},
    {"name": "monthly_rebalance_topk50_drop10", "topk": 50, "n_drop": 10, "rebalance_step": 20},
]

EXCHANGE_SPECS = [
    {"name": "uniform_limit_threshold_0.095", "exchange_mode": "uniform", "limit_price_buffer": None},
    {"name": "ashare_exchange_buffer_0.001", "exchange_mode": "ashare", "limit_price_buffer": 0.001},
    {"name": "ashare_exchange_buffer_0.000", "exchange_mode": "ashare", "limit_price_buffer": 0.0},
]


def main() -> None:
    args = parse_args()
    qlib.init(provider_uri=args.provider_uri, region="cn", kernels=args.kernels, joblib_backend="threading")
    signal = _load_signal(args.pred_path)
    data_quality = _read_json(args.data_quality_summary)
    industry_quality = _read_json(args.industry_quality_summary)
    if data_quality.get("data_type") in {"synthetic", "mock"}:
        raise RuntimeError("Refusing to run formal sensitivity report on synthetic/mock data.")

    specs = TURNOVER_SPECS if args.mode == "turnover" else EXCHANGE_SPECS
    rows = []
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    for spec in specs:
        row, report, positions = run_one(args, signal, spec, data_quality, industry_quality)
        rows.append(row)
        run_dir = output_dir / spec["name"]
        run_dir.mkdir(parents=True, exist_ok=True)
        report.to_csv(run_dir / "report_normal_1day.csv")
        _write_positions(positions, run_dir / "positions_normal_1day.csv")

    comparison = pd.DataFrame(rows)
    csv_path = Path(args.comparison_csv)
    md_path = Path(args.comparison_md)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    comparison.to_csv(csv_path, index=False)
    md_path.write_text(_render_markdown(args.mode, comparison), encoding="utf-8")
    manifest = {
        **real_data_markers(),
        "mode": args.mode,
        "provider_uri": args.provider_uri,
        "pred_path": args.pred_path,
        "benchmark": args.benchmark,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "comparison_csv": str(csv_path),
        "comparison_md": str(md_path),
        "data_quality_status": data_quality.get("quality_status"),
        "industry_quality_status": industry_quality.get("industry_quality_status", industry_quality.get("quality_status")),
    }
    (output_dir / f"{args.mode}_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.mode} comparison: {csv_path}")


def run_one(args: argparse.Namespace, signal: pd.Series, spec: dict[str, Any], data_quality: dict[str, Any], industry_quality: dict[str, Any]):
    if args.mode == "turnover":
        strategy = {
            "class": "PeriodicTopkDropoutStrategy",
            "module_path": "ashare_adapter.strategy",
            "kwargs": {
                "signal": signal,
                "topk": spec["topk"],
                "n_drop": spec["n_drop"],
                "rebalance_step": spec["rebalance_step"],
            },
        }
        exchange_kwargs = _uniform_exchange_kwargs(args)
        exchange_mode = "uniform_limit_threshold_0.095"
    else:
        strategy = {
            "class": "TopkDropoutStrategy",
            "module_path": "qlib.contrib.strategy",
            "kwargs": {"signal": signal, "topk": args.topk, "n_drop": args.n_drop},
        }
        exchange_mode = spec["name"]
        exchange_kwargs = (
            _uniform_exchange_kwargs(args)
            if spec["exchange_mode"] == "uniform"
            else ashare_exchange_kwargs(
                start_time=args.start_time,
                end_time=args.end_time,
                codes=args.market,
                deal_price="close",
                open_cost=args.open_cost,
                close_cost=args.close_cost,
                min_cost=args.min_cost,
                limit_threshold=args.limit_threshold,
                limit_price_buffer=float(spec["limit_price_buffer"]),
            )
        )

    report, positions = backtest_daily(
        start_time=args.start_time,
        end_time=args.end_time,
        strategy=strategy,
        account=args.account,
        benchmark=args.benchmark,
        exchange_kwargs=exchange_kwargs,
    )
    metrics = _report_metrics(report)
    row = {
        **real_data_markers(),
        "universe_name": args.universe_name,
        "model": "Alpha158 + LightGBM",
        "benchmark": args.benchmark,
        "start_time": args.start_time,
        "end_time": args.end_time,
        "scenario": spec["name"],
        "topk": spec.get("topk", args.topk),
        "n_drop": spec.get("n_drop", args.n_drop),
        "rebalance_step": spec.get("rebalance_step", 1),
        "exchange_mode": exchange_mode,
        "limit_price_buffer": spec.get("limit_price_buffer"),
        "data_quality_status": data_quality.get("quality_status"),
        "industry_quality_status": industry_quality.get("industry_quality_status", industry_quality.get("quality_status")),
        **metrics,
        "caveats": "; ".join(
            [
                "real_akshare_prediction_reused",
                "portfolio_layer_sensitivity_only",
                "current_listed_candidate_bias",
                "2026_ytd_window",
            ]
        ),
    }
    return row, report, positions


def _uniform_exchange_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "freq": "day",
        "limit_threshold": args.limit_threshold,
        "deal_price": "close",
        "open_cost": args.open_cost,
        "close_cost": args.close_cost,
        "min_cost": args.min_cost,
    }


def _report_metrics(report: pd.DataFrame) -> dict[str, Any]:
    data = report.copy()
    for column in ["return", "bench", "cost", "turnover", "total_cost"]:
        if column not in data.columns:
            data[column] = 0.0
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)
    excess_with_cost = data["return"] - data["bench"] - data["cost"]
    account = pd.to_numeric(data.get("account"), errors="coerce").dropna()
    bench_total = float((1.0 + data["bench"]).prod() - 1.0)
    wealth = (1.0 + excess_with_cost).cumprod()
    drawdown = wealth / wealth.cummax() - 1.0
    std = excess_with_cost.std()
    return {
        "excess_annualized_return_with_cost": float(excess_with_cost.mean() * 252),
        "excess_information_ratio_with_cost": float(excess_with_cost.mean() / std * (252**0.5)) if std else None,
        "excess_max_drawdown_with_cost": float(drawdown.min()) if len(drawdown) else None,
        "account_total_return": float(account.iloc[-1] / account.iloc[0] - 1.0) if len(account) >= 2 and account.iloc[0] != 0 else None,
        "benchmark_total_return": bench_total,
        "turnover": float(data["turnover"].mean()),
        "cost": float(data["total_cost"].sum()),
    }


def _load_signal(path: str | Path) -> pd.Series:
    with Path(path).open("rb") as fh:
        obj = pickle.load(fh)
    if isinstance(obj, pd.DataFrame):
        if "score" in obj.columns:
            return obj["score"]
        return obj.iloc[:, 0]
    if isinstance(obj, pd.Series):
        return obj
    raise TypeError(f"Unsupported prediction object: {type(obj)!r}")


def _write_positions(positions: Any, path: Path) -> None:
    if isinstance(positions, pd.DataFrame):
        positions.to_csv(path)
    elif isinstance(positions, dict):
        rows = []
        for date, position in positions.items():
            payload = getattr(position, "position", None)
            if payload is None and isinstance(position, dict):
                payload = position.get("position")
            if not isinstance(payload, dict):
                continue
            for symbol, item in payload.items():
                if symbol in {"cash", "now_account_value"} or not isinstance(item, dict):
                    continue
                rows.append({"date": date, "symbol": symbol, **item})
        pd.DataFrame(rows).to_csv(path, index=False)
    else:
        pd.DataFrame().to_csv(path, index=False)


def _read_json(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    source = Path(path)
    if not source.exists():
        return {}
    return json.loads(source.read_text(encoding="utf-8"))


def _render_markdown(mode: str, comparison: pd.DataFrame) -> str:
    title = "Turnover Sensitivity Comparison Real AKShare" if mode == "turnover" else "AShareExchange Comparison Real AKShare"
    note = (
        "Portfolio-layer sensitivity using an existing real Alpha158 prediction. No synthetic data is used, and the main result is not overwritten."
    )
    return f"# {title}\n\n{note}\n\n" + comparison.to_markdown(index=False) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["turnover", "exchange"], required=True)
    parser.add_argument("--provider-uri", required=True)
    parser.add_argument("--pred-path", required=True)
    parser.add_argument("--universe-name", required=True)
    parser.add_argument("--market", default="all")
    parser.add_argument("--benchmark", default="SH000905")
    parser.add_argument("--start-time", default="2025-01-01")
    parser.add_argument("--end-time", default="2026-06-24")
    parser.add_argument("--account", type=float, default=100_000_000)
    parser.add_argument("--open-cost", type=float, default=0.00031)
    parser.add_argument("--close-cost", type=float, default=0.00081)
    parser.add_argument("--min-cost", type=float, default=5.0)
    parser.add_argument("--limit-threshold", type=float, default=0.095)
    parser.add_argument("--topk", type=int, default=50)
    parser.add_argument("--n-drop", type=int, default=10)
    parser.add_argument("--kernels", type=int, default=1)
    parser.add_argument("--data-quality-summary", default=None)
    parser.add_argument("--industry-quality-summary", default=None)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--comparison-csv", required=True)
    parser.add_argument("--comparison-md", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    main()
