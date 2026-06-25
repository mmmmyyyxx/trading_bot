"""Single-factor top-K backtest comparisons."""

from __future__ import annotations

import copy

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors, recompute_composite_score
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.research.parallel import SharedFrameStore, process_map, read_shared_frame
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags

SINGLE_FACTORS = ["momentum", "trend", "volatility", "liquidity", "short_term_reversal"]


def run_single_factor_backtests(
    config: AppConfig,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run one top-K backtest per factor while keeping other settings fixed."""
    benchmark_frame = benchmarks if benchmarks is not None else load_benchmarks(config, bars)
    benchmark_return = _configured_benchmark_return(config, benchmark_frame)
    enriched = build_strategy_universe_flags(config, bars)
    base_factors = compute_composite_factors(bars, config.factors)

    with SharedFrameStore(config.report.output_dir) as store:
        bars_path = store.write("single_factor_bars", bars)
        enriched_path = store.write("single_factor_enriched", enriched)
        factors_path = store.write("single_factor_factors", base_factors)
        benchmark_path = store.write("single_factor_benchmarks", benchmark_frame)
        jobs = [
            (config, factor, benchmark_return, bars_path, enriched_path, factors_path, benchmark_path)
            for factor in SINGLE_FACTORS
        ]
        rows = process_map(jobs, _run_single_factor_job, max_workers=config.report.parallel_workers)
    return pd.DataFrame(rows).sort_values("factor").reset_index(drop=True)


def _run_single_factor_job(job: tuple[AppConfig, str, float, str, str, str, str]) -> dict[str, object]:
    config, factor, benchmark_return, bars_path, enriched_path, factors_path, benchmark_path = job
    bars = read_shared_frame(bars_path)
    enriched = read_shared_frame(enriched_path)
    base_factors = read_shared_frame(factors_path)
    benchmark_frame = read_shared_frame(benchmark_path)
    cfg = copy.deepcopy(config)
    cfg.strategy.name = "custom"
    cfg.factors.weights = {name: 0.0 for name in SINGLE_FACTORS}
    cfg.factors.weights[factor] = 1.0
    factor_scores = recompute_composite_score(base_factors, cfg.factors.weights)
    strategy = MultiFactorRotationStrategy(cfg)
    strategy._benchmark_cache = benchmark_frame
    targets = strategy.generate_targets(bars, factor_scores=factor_scores, enriched_bars=enriched)
    result = BacktestEngine(cfg).run(bars, targets)
    row: dict[str, object] = {"factor": factor, "target_rows": len(targets)}
    row.update(result.metrics)
    row["benchmark_return"] = benchmark_return
    row["excess_return"] = float(row.get("total_return", 0.0)) - benchmark_return
    return row


def _configured_benchmark_return(config: AppConfig, benchmarks: pd.DataFrame) -> float:
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
