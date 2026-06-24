"""Walk-forward out-of-sample diagnostics."""

from __future__ import annotations

import copy

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.backtest.metrics import compute_metrics
from ashare_quant.config import AppConfig
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy


def run_walk_forward(
    config: AppConfig,
    bars: pd.DataFrame,
    train_months: list[int] | None = None,
    test_months: list[int] | None = None,
) -> pd.DataFrame:
    """Evaluate the current parameter set over rolling OOS windows."""
    train_months = train_months or [12, 24]
    test_months = test_months or [3, 6]
    dates = pd.DatetimeIndex(pd.to_datetime(bars["date"]).drop_duplicates().sort_values())
    if dates.empty:
        return pd.DataFrame()

    try:
        benchmarks = load_benchmarks(config, bars)
    except Exception:
        benchmarks = pd.DataFrame()

    rows: list[dict[str, object]] = []
    for train_m in train_months:
        for test_m in test_months:
            start = dates[0] + pd.DateOffset(months=train_m)
            while start < dates[-1]:
                end = min(start + pd.DateOffset(months=test_m), dates[-1])
                cfg = copy.deepcopy(config)
                cfg.backtest.start_date = start.strftime("%Y-%m-%d")
                cfg.backtest.end_date = pd.Timestamp(end).strftime("%Y-%m-%d")
                targets = MultiFactorRotationStrategy(cfg).generate_targets(bars)
                result = BacktestEngine(cfg).run(bars, targets)
                if result.equity_curve.empty:
                    start = end
                    continue
                metrics = compute_metrics(
                    result.equity_curve,
                    result.trades,
                    initial_cash=float(result.equity_curve["net_equity"].iloc[0]),
                )
                rows.append(
                    {
                        "train_months": train_m,
                        "test_months": test_m,
                        "test_start": cfg.backtest.start_date,
                        "test_end": cfg.backtest.end_date,
                        "oos_total_return": metrics["total_return"],
                        "oos_sharpe": metrics["sharpe"],
                        "oos_max_drawdown": metrics["max_drawdown"],
                        "oos_information_ratio": _information_ratio(result.equity_curve, benchmarks, cfg),
                    }
                )
                start = end
    return pd.DataFrame(rows)


def _information_ratio(equity_curve: pd.DataFrame, benchmarks: pd.DataFrame, config: AppConfig) -> float:
    if equity_curve.empty or benchmarks.empty:
        return float("nan")
    key = (config.data.benchmark_symbol or "hs300").lower()
    benchmark = benchmarks[benchmarks["benchmark"].str.lower() == key].copy()
    if benchmark.empty:
        first_key = str(benchmarks["benchmark"].iloc[0])
        benchmark = benchmarks[benchmarks["benchmark"] == first_key].copy()
    equity = equity_curve[["date", "daily_return"]].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    benchmark = benchmark[["date", "return"]].copy()
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    merged = equity.merge(benchmark, on="date", how="inner")
    if len(merged) < 2:
        return float("nan")
    excess = merged["daily_return"].astype(float) - merged["return"].astype(float)
    std = excess.std(ddof=0)
    if std == 0 or pd.isna(std):
        return 0.0
    return float(excess.mean() / std * (252**0.5))
