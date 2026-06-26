"""End-to-end research diagnostics pipeline."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.pipeline import _attach_benchmark_return, load_market_data
from ashare_quant.report.performance_report import prepare_output_dir, write_report
from ashare_quant.research.benchmark import benchmark_summary, load_benchmarks
from ashare_quant.research.exposure import write_exposure_reports
from ashare_quant.research.groups import compute_factor_group_returns
from ashare_quant.research.grid import run_parameter_grid
from ashare_quant.research.ic import compute_rank_ic
from ashare_quant.research.report import write_research_report
from ashare_quant.research.regime import compute_regime_performance
from ashare_quant.research.single_factor import run_single_factor_backtests
from ashare_quant.research.strategy_compare import run_strategy_comparison
from ashare_quant.research.walk_forward import run_walk_forward
from ashare_quant.research.walk_forward_selection import run_walk_forward_selection
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags
from ashare_quant.strategy.profiles import apply_strategy_profile

LOGGER = logging.getLogger(__name__)


def run_research_pipeline(config: AppConfig, refresh_data: bool = False) -> dict[str, pd.DataFrame]:
    """Run benchmark, IC, group-return, single-factor, and grid diagnostics."""
    output_dir = Path(config.report.output_dir)
    prepare_output_dir(output_dir, clean=True)

    bars = load_market_data(config, refresh=refresh_data)
    LOGGER.info("Research data rows: %d", len(bars))
    effective_config = apply_strategy_profile(config)
    factor_scores = compute_composite_factors(bars, effective_config.factors)
    industry_fallback_rate = _industry_momentum_fallback_rate(factor_scores)

    benchmarks = load_benchmarks(config, bars)
    bench_summary = benchmark_summary(benchmarks)
    LOGGER.info("Generating default strategy targets for universe and exposure diagnostics.")
    default_enriched = build_strategy_universe_flags(config, bars)
    strategy = MultiFactorRotationStrategy(config)
    strategy._benchmark_cache = benchmarks
    default_targets = strategy.generate_targets(bars, factor_scores=factor_scores, enriched_bars=default_enriched)
    default_result = BacktestEngine(config).run(bars, default_targets)
    _attach_benchmark_return(default_result, config, bars)
    write_report(default_result, output_dir, make_plots=config.report.make_plots, clean_output=False)
    regime_performance = compute_regime_performance(default_result.equity_curve, benchmarks)
    LOGGER.info("Computing factor IC diagnostics.")
    ic_summary, ic_daily = compute_rank_ic(bars, factor_scores, horizons=[1, 5, 20])
    LOGGER.info("Computing factor group returns.")
    group_summary, group_returns = compute_factor_group_returns(bars, factor_scores, n_groups=5, horizon=1, min_group_size=20)
    LOGGER.info("Running single-factor backtests.")
    single_factor_results = run_single_factor_backtests(config, bars, benchmarks=benchmarks)
    LOGGER.info("Running daily research parameter grid.")
    parameter_grid = run_parameter_grid(
        config,
        bars,
        top_k_values=[30, 50],
        rebalance_values=["M"],
        weighting_values=["equal_weight", "inverse_vol_weight"],
        momentum_windows=[60, 120],
        skip_windows=[5, 20],
        benchmarks=benchmarks,
    )
    LOGGER.info("Running rolling OOS evaluation.")
    walk_forward = run_walk_forward(config, bars, benchmarks=benchmarks)
    LOGGER.info("Running walk-forward parameter selection.")
    walk_forward_selection = run_walk_forward_selection(
        config,
        bars,
        benchmarks=benchmarks,
        strategy_names=["reversal_low_vol", "defensive_low_vol", "offensive_momentum", "balanced_multi_factor"],
        top_k_values=[30, 50],
        weighting_values=["equal_weight", "inverse_vol_weight"],
        rebalance_values=["M"],
        momentum_windows=[120],
        skip_windows=[20],
    )
    LOGGER.info("Running named strategy comparison.")
    strategy_comparison = run_strategy_comparison(config, bars, benchmark_frame=benchmarks)
    exposure_reports = write_exposure_reports(default_result, bars, benchmarks, output_dir)

    benchmarks.to_csv(output_dir / "benchmark_returns.csv", index=False)
    bench_summary.to_csv(output_dir / "benchmark_summary.csv", index=False)
    strategy.universe_diagnostics.to_csv(output_dir / "universe_diagnostics.csv", index=False)
    strategy.daily_universe_size.to_csv(output_dir / "daily_universe_size.csv", index=False)
    ic_summary.to_csv(output_dir / "factor_ic.csv", index=False)
    ic_daily.to_csv(output_dir / "factor_ic_daily.csv", index=False)
    group_summary.to_csv(output_dir / "factor_group_summary.csv", index=False)
    group_returns.to_csv(output_dir / "factor_group_returns.csv", index=False)
    single_factor_results.to_csv(output_dir / "single_factor_backtests.csv", index=False)
    parameter_grid.to_csv(output_dir / "parameter_grid.csv", index=False)
    walk_forward.to_csv(output_dir / "walk_forward.csv", index=False)
    walk_forward.to_csv(output_dir / "rolling_oos_eval.csv", index=False)
    walk_forward_selection.to_csv(output_dir / "walk_forward_selection.csv", index=False)
    strategy_comparison.to_csv(output_dir / "strategy_comparison.csv", index=False)
    regime_performance.to_csv(output_dir / "regime_performance.csv", index=False)

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
        walk_forward_selection=walk_forward_selection,
        universe_diagnostics=strategy.universe_diagnostics,
        strategy_comparison=strategy_comparison,
        regime_performance=regime_performance,
        exposure_report=exposure_reports["exposure_report"],
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
        "walk_forward_selection": walk_forward_selection,
        "strategy_comparison": strategy_comparison,
        "regime_performance": regime_performance,
        "universe_diagnostics": strategy.universe_diagnostics,
        "daily_universe_size": strategy.daily_universe_size,
        "exposure_report": exposure_reports["exposure_report"],
        "top_holdings": exposure_reports["top_holdings"],
    }


def _industry_momentum_fallback_rate(factor_scores: pd.DataFrame) -> float:
    if "industry_momentum_fallback" not in factor_scores.columns:
        return 1.0
    valid = factor_scores["industry_momentum"].notna() if "industry_momentum" in factor_scores.columns else pd.Series(True, index=factor_scores.index)
    sample = factor_scores.loc[valid, "industry_momentum_fallback"]
    if sample.empty:
        return 1.0
    return float(sample.astype(bool).mean())
