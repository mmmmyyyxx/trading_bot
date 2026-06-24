from __future__ import annotations

from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.research.benchmark import benchmark_summary, load_benchmarks
from ashare_quant.research.groups import compute_factor_group_returns
from ashare_quant.research.grid import run_parameter_grid
from ashare_quant.research.ic import compute_rank_ic
from tests.real_data import load_real_cached_bars


def _sample_config_and_bars():
    config = AppConfig()
    config.strategy.top_k = 3
    config.strategy.max_weight = 0.3
    bars = load_real_cached_bars()
    return config, bars


def test_rank_ic_and_group_returns_are_generated_offline() -> None:
    config, bars = _sample_config_and_bars()
    factors = compute_composite_factors(bars, config.factors)

    ic_summary, ic_daily = compute_rank_ic(bars, factors, horizons=[1, 5])
    group_summary, group_returns = compute_factor_group_returns(bars, factors, n_groups=3, horizon=1)

    assert not ic_summary.empty
    assert not ic_daily.empty
    assert {"ic_mean", "icir", "positive_ic_ratio"}.issubset(ic_summary.columns)
    assert not group_summary.empty
    assert not group_returns.empty
    assert group_returns["group"].nunique() == 3


def test_benchmark_loads_real_akshare_series() -> None:
    config, bars = _sample_config_and_bars()
    benchmarks = load_benchmarks(config, bars)
    summary = benchmark_summary(benchmarks)

    assert set(summary["benchmark"]) == {"hs300", "csi500", "csi1000"}
    assert set(summary["source"]) == {"akshare"}


def test_parameter_grid_reports_is_and_oos_metrics() -> None:
    config, bars = _sample_config_and_bars()
    grid = run_parameter_grid(
        config,
        bars,
        top_k_values=[2],
        rebalance_values=["monthly"],
        weighting_values=["equal_weight"],
        momentum_windows=[60],
        skip_windows=[5],
    )

    assert len(grid) == 1
    assert "is_total_return" in grid.columns
    assert "oos_total_return" in grid.columns
    assert "oos_sharpe" in grid.columns
