"""End-to-end research diagnostics pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.pipeline import load_market_data
from ashare_quant.research.benchmark import benchmark_summary, load_benchmarks
from ashare_quant.research.groups import compute_factor_group_returns
from ashare_quant.research.grid import run_parameter_grid
from ashare_quant.research.ic import compute_rank_ic
from ashare_quant.research.report import write_research_report
from ashare_quant.research.single_factor import run_single_factor_backtests
from ashare_quant.research.walk_forward import run_walk_forward

LOGGER = logging.getLogger(__name__)


def run_research_pipeline(config: AppConfig, refresh_data: bool = False) -> dict[str, pd.DataFrame]:
    """Run benchmark, IC, group-return, single-factor, and grid diagnostics."""
    output_dir = Path(config.report.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bars = load_market_data(config, refresh=refresh_data)
    LOGGER.info("Research data rows: %d", len(bars))
    factor_scores = compute_composite_factors(bars, config.factors)
    industry_fallback_rate = _industry_momentum_fallback_rate(factor_scores)

    benchmarks = load_benchmarks(config, bars)
    bench_summary = benchmark_summary(benchmarks)
    ic_summary, ic_daily = compute_rank_ic(bars, factor_scores, horizons=[1, 5, 20])
    group_summary, group_returns = compute_factor_group_returns(bars, factor_scores, n_groups=5, horizon=1, min_group_size=20)
    single_factor_results = run_single_factor_backtests(config, bars)
    parameter_grid = run_parameter_grid(config, bars)
    walk_forward = run_walk_forward(config, bars)

    benchmarks.to_csv(output_dir / "benchmark_returns.csv", index=False)
    bench_summary.to_csv(output_dir / "benchmark_summary.csv", index=False)
    ic_summary.to_csv(output_dir / "factor_ic.csv", index=False)
    ic_daily.to_csv(output_dir / "factor_ic_daily.csv", index=False)
    group_summary.to_csv(output_dir / "factor_group_summary.csv", index=False)
    group_returns.to_csv(output_dir / "factor_group_returns.csv", index=False)
    single_factor_results.to_csv(output_dir / "single_factor_backtests.csv", index=False)
    parameter_grid.to_csv(output_dir / "parameter_grid.csv", index=False)
    walk_forward.to_csv(output_dir / "walk_forward.csv", index=False)

    write_research_report(
        output_dir=output_dir,
        config=config,
        benchmark_summary=bench_summary,
        ic_summary=ic_summary,
        group_summary=group_summary,
        single_factor_results=single_factor_results,
        parameter_grid=parameter_grid,
        industry_fallback_rate=industry_fallback_rate,
        walk_forward=walk_forward,
    )
    LOGGER.info("Research diagnostics written to %s", output_dir)
    return {
        "benchmark_summary": bench_summary,
        "factor_ic": ic_summary,
        "factor_ic_daily": ic_daily,
        "factor_group_summary": group_summary,
        "factor_group_returns": group_returns,
        "single_factor_backtests": single_factor_results,
        "parameter_grid": parameter_grid,
        "walk_forward": walk_forward,
    }


def _industry_momentum_fallback_rate(factor_scores: pd.DataFrame) -> float:
    if "industry_momentum_fallback" not in factor_scores.columns:
        return 1.0
    valid = factor_scores["industry_momentum"].notna() if "industry_momentum" in factor_scores.columns else pd.Series(True, index=factor_scores.index)
    sample = factor_scores.loc[valid, "industry_momentum_fallback"]
    if sample.empty:
        return 1.0
    return float(sample.astype(bool).mean())
