"""Parameter grid diagnostics with in-sample/out-of-sample splits."""

from __future__ import annotations

import copy
import itertools

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.backtest.metrics import compute_metrics
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.research.parallel import SharedFrameStore, process_map, read_shared_frame
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags
from ashare_quant.strategy.profiles import apply_strategy_profile


def _period_metrics(result, start_date: pd.Timestamp, end_date: pd.Timestamp, prefix: str) -> dict[str, float]:
    equity = result.equity_curve.copy()
    equity["date"] = pd.to_datetime(equity["date"])
    period_equity = equity[(equity["date"] >= start_date) & (equity["date"] <= end_date)].copy()
    if len(period_equity) < 2:
        return {
            f"{prefix}_total_return": 0.0,
            f"{prefix}_annual_return": 0.0,
            f"{prefix}_annual_volatility": 0.0,
            f"{prefix}_sharpe": 0.0,
            f"{prefix}_max_drawdown": 0.0,
            f"{prefix}_calmar": 0.0,
        }
    initial = float(period_equity["net_equity"].iloc[0])
    period_equity.loc[period_equity.index[0], "daily_return"] = 0.0
    trades = result.trades.copy()
    if not trades.empty and "date" in trades:
        trades["date"] = pd.to_datetime(trades["date"])
        trades = trades[(trades["date"] >= start_date) & (trades["date"] <= end_date)]
    metrics = compute_metrics(period_equity, trades, initial_cash=initial)
    return {
        f"{prefix}_total_return": metrics["total_return"],
        f"{prefix}_annual_return": metrics["annual_return"],
        f"{prefix}_annual_volatility": metrics["annual_volatility"],
        f"{prefix}_sharpe": metrics["sharpe"],
        f"{prefix}_max_drawdown": metrics["max_drawdown"],
        f"{prefix}_calmar": metrics["calmar"],
    }


def run_parameter_grid(
    config: AppConfig,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame | None = None,
    top_k_values: list[int] | None = None,
    rebalance_values: list[str] | None = None,
    weighting_values: list[str] | None = None,
    momentum_windows: list[int] | None = None,
    skip_windows: list[int] | None = None,
) -> pd.DataFrame:
    """Run the requested parameter grid and report both IS and OOS metrics."""
    top_k_values = top_k_values or [10, 20, 30, 50]
    rebalance_values = rebalance_values or ["weekly", "monthly"]
    weighting_values = weighting_values or ["equal_weight", "inverse_vol_weight"]
    momentum_windows = momentum_windows or [60, 120, 180]
    skip_windows = skip_windows or [5, 20]

    dates = pd.DatetimeIndex(pd.to_datetime(bars["date"]).drop_duplicates().sort_values())
    split_idx = max(1, int(len(dates) * 0.7))
    split_date = pd.Timestamp(dates[split_idx])
    start_date = pd.Timestamp(dates[0])
    end_date = pd.Timestamp(dates[-1])

    enriched = build_strategy_universe_flags(config, bars)
    combos = list(itertools.product(top_k_values, rebalance_values, weighting_values, momentum_windows, skip_windows))
    unique_symbols = bars["symbol"].nunique()
    factor_cache = _precompute_factor_cache(config, bars, momentum_windows, skip_windows)
    benchmark_frame = benchmarks if benchmarks is not None else load_benchmarks(config, bars)
    with SharedFrameStore(config.report.output_dir) as store:
        bars_path = store.write("grid_bars", bars)
        enriched_path = store.write("grid_enriched", enriched)
        benchmark_path = store.write("grid_benchmarks", benchmark_frame)
        factor_paths = {key: store.write(f"grid_factors_{idx}", frame) for idx, (key, frame) in enumerate(factor_cache.items())}
        jobs = [
            (
                config,
                combo,
                bars_path,
                enriched_path,
                benchmark_path,
                factor_paths,
                split_date,
                start_date,
                end_date,
                unique_symbols,
            )
            for combo in combos
        ]
        if unique_symbols < max(top_k_values) * 2:
            rows = [_run_grid_combo_job(job) for job in jobs]
        else:
            rows = process_map(jobs, _run_grid_combo_job, max_workers=config.report.parallel_workers)
    return pd.DataFrame(rows).sort_values(["oos_sharpe", "oos_total_return"], ascending=False).reset_index(drop=True)


def _run_grid_combo_job(
    job: tuple[
        AppConfig,
        tuple[int, str, str, int, int],
        str,
        str,
        str,
        dict[tuple[object, ...], str],
        pd.Timestamp,
        pd.Timestamp,
        pd.Timestamp,
        int,
    ],
) -> dict[str, object]:
    config, combo, bars_path, enriched_path, benchmark_path, factor_paths, split_date, start_date, end_date, unique_symbols = job
    top_k, rebalance, weighting, momentum_window, skip_window = combo
    if unique_symbols < top_k * 2:
        return _skipped_row(top_k, rebalance, weighting, momentum_window, skip_window, split_date)

    bars = read_shared_frame(bars_path)
    enriched = read_shared_frame(enriched_path)
    benchmark_frame = read_shared_frame(benchmark_path)
    cfg = copy.deepcopy(config)
    cfg.strategy.top_k = top_k
    cfg.strategy.rebalance_frequency = rebalance
    cfg.strategy.weighting = weighting
    cfg.factors.momentum_window = momentum_window
    cfg.factors.momentum_skip = skip_window
    cfg.report.make_plots = False

    factor_scores = read_shared_frame(factor_paths[_factor_cache_key(apply_strategy_profile(cfg))], cache=False)
    strategy = MultiFactorRotationStrategy(cfg)
    strategy._benchmark_cache = benchmark_frame
    targets = strategy.generate_targets(bars, factor_scores=factor_scores, enriched_bars=enriched)
    result = BacktestEngine(cfg).run(bars, targets)
    row: dict[str, object] = {
        "top_k": top_k,
        "rebalance": rebalance,
        "weighting": weighting,
        "momentum_window": momentum_window,
        "skip_window": skip_window,
        "target_rows": len(targets),
        "split_date": split_date,
        "status": "ok",
    }
    row.update(_period_metrics(result, start_date, split_date, "is"))
    row.update(_period_metrics(result, split_date, end_date, "oos"))
    return row


def _skipped_row(
    top_k: int,
    rebalance: str,
    weighting: str,
    momentum_window: int,
    skip_window: int,
    split_date: pd.Timestamp,
) -> dict[str, object]:
    return {
        "top_k": top_k,
        "rebalance": rebalance,
        "weighting": weighting,
        "momentum_window": momentum_window,
        "skip_window": skip_window,
        "target_rows": 0,
        "split_date": split_date,
        "status": "skipped_insufficient_universe",
        "is_total_return": 0.0,
        "is_annual_return": 0.0,
        "is_annual_volatility": 0.0,
        "is_sharpe": 0.0,
        "is_max_drawdown": 0.0,
        "is_calmar": 0.0,
        "oos_total_return": 0.0,
        "oos_annual_return": 0.0,
        "oos_annual_volatility": 0.0,
        "oos_sharpe": 0.0,
        "oos_max_drawdown": 0.0,
        "oos_calmar": 0.0,
    }


def _precompute_factor_cache(
    config: AppConfig,
    bars: pd.DataFrame,
    momentum_windows: list[int],
    skip_windows: list[int],
) -> dict[tuple[object, ...], pd.DataFrame]:
    cache: dict[tuple[object, ...], pd.DataFrame] = {}
    for momentum_window, skip_window in itertools.product(momentum_windows, skip_windows):
        cfg = copy.deepcopy(config)
        cfg.factors.momentum_window = momentum_window
        cfg.factors.momentum_skip = skip_window
        effective = apply_strategy_profile(cfg)
        key = _factor_cache_key(effective)
        if key not in cache:
            cache[key] = compute_composite_factors(bars, effective.factors)
    return cache


def _factor_cache_key(config: AppConfig) -> tuple[object, ...]:
    return (
        config.strategy.name,
        config.factors.momentum_window,
        config.factors.momentum_skip,
        tuple(sorted(config.factors.weights.items())),
    )
