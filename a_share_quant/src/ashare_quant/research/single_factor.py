"""Single-factor top-K backtest comparisons."""

from __future__ import annotations

import copy

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy

SINGLE_FACTORS = ["momentum", "trend", "volatility", "liquidity"]


def run_single_factor_backtests(config: AppConfig, bars: pd.DataFrame) -> pd.DataFrame:
    """Run one top-K backtest per factor while keeping other settings fixed."""
    benchmark_return = _configured_benchmark_return(config, bars)
    rows: list[dict[str, object]] = []
    for factor in SINGLE_FACTORS:
        cfg = copy.deepcopy(config)
        cfg.strategy.name = "custom"
        cfg.factors.weights = {name: 0.0 for name in SINGLE_FACTORS}
        cfg.factors.weights[factor] = 1.0
        targets = MultiFactorRotationStrategy(cfg).generate_targets(bars)
        result = BacktestEngine(cfg).run(bars, targets)
        row: dict[str, object] = {"factor": factor, "target_rows": len(targets)}
        row.update(result.metrics)
        row["benchmark_return"] = benchmark_return
        row["excess_return"] = float(row.get("total_return", 0.0)) - benchmark_return
        rows.append(row)
    return pd.DataFrame(rows).sort_values("factor").reset_index(drop=True)


def _configured_benchmark_return(config: AppConfig, bars: pd.DataFrame) -> float:
    benchmarks = load_benchmarks(config, bars)
    key = (config.data.benchmark_symbol or "hs300").lower()
    selected = benchmarks[benchmarks["benchmark"].str.lower() == key].copy()
    if selected.empty:
        first_key = str(benchmarks["benchmark"].iloc[0])
        selected = benchmarks[benchmarks["benchmark"] == first_key].copy()
    if selected.empty:
        return float("nan")
    selected["date"] = pd.to_datetime(selected["date"])
    if config.backtest.start_date:
        selected = selected[selected["date"] >= pd.Timestamp(config.backtest.start_date)]
    if config.backtest.end_date:
        selected = selected[selected["date"] <= pd.Timestamp(config.backtest.end_date)]
    if len(selected) < 2:
        return float("nan")
    return float(selected["equity"].iloc[-1] / selected["equity"].iloc[0] - 1.0)
