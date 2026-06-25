"""Named-strategy comparisons against multiple benchmarks."""

from __future__ import annotations

import copy
import logging

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.research.benchmark import BENCHMARKS, load_benchmarks
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags
from ashare_quant.strategy.profiles import apply_strategy_profile, get_strategy_profile, profile_names

LOGGER = logging.getLogger(__name__)


def run_strategy_comparison(
    config: AppConfig,
    bars: pd.DataFrame,
    strategies: list[str] | None = None,
    benchmarks: list[str] | None = None,
) -> pd.DataFrame:
    """Run named strategy profiles and compare each against configured benchmarks."""
    strategies = strategies or profile_names()
    benchmarks = benchmarks or list(BENCHMARKS)
    benchmark_frame = load_benchmarks(config, bars)
    enriched = build_strategy_universe_flags(config, bars)
    factor_cache: dict[tuple[object, ...], pd.DataFrame] = {}

    rows: list[dict[str, object]] = []
    for strategy_name in strategies:
        LOGGER.info("Running strategy comparison for %s.", strategy_name)
        cfg = copy.deepcopy(config)
        cfg.strategy.name = strategy_name
        profile = get_strategy_profile(strategy_name)
        if profile is not None:
            cfg.strategy.weighting = profile.default_weighting
        cfg.report.make_plots = False
        factor_scores = _cached_factor_scores(cfg, bars, factor_cache)
        targets = MultiFactorRotationStrategy(cfg).generate_targets(bars, factor_scores=factor_scores, enriched_bars=enriched)
        result = BacktestEngine(cfg).run(bars, targets)
        base = {
            "strategy": strategy_name,
            "objective": profile.objective if profile is not None else "custom",
            "weighting": cfg.strategy.weighting,
            "top_k": cfg.strategy.top_k,
            "target_rows": len(targets),
            "quality_factor_available": bool(profile.quality_factor_available) if profile is not None else False,
            "value_factor_available": bool(profile.value_factor_available) if profile is not None else False,
            **result.metrics,
        }
        for benchmark in benchmarks:
            selected = benchmark_frame[benchmark_frame["benchmark"].str.lower() == benchmark.lower()].copy()
            rel = _relative_metrics(result.equity_curve, selected, result.metrics)
            rows.append({**base, "benchmark": benchmark, **rel})
    return pd.DataFrame(rows)


def _cached_factor_scores(
    config: AppConfig,
    bars: pd.DataFrame,
    cache: dict[tuple[object, ...], pd.DataFrame],
) -> pd.DataFrame:
    effective = apply_strategy_profile(config)
    key = (
        effective.strategy.name,
        effective.factors.momentum_window,
        effective.factors.momentum_skip,
        tuple(sorted(effective.factors.weights.items())),
    )
    if key not in cache:
        cache[key] = compute_composite_factors(bars, effective.factors)
    return cache[key]


def _relative_metrics(equity_curve: pd.DataFrame, benchmark: pd.DataFrame, metrics: dict[str, float]) -> dict[str, float]:
    if equity_curve.empty or benchmark.empty:
        return {
            "benchmark_return": float("nan"),
            "excess_return": float("nan"),
            "information_ratio": float("nan"),
            "beta": float("nan"),
            "alpha": float("nan"),
            "up_capture": float("nan"),
            "down_capture": float("nan"),
            "monthly_win_rate_vs_benchmark": float("nan"),
        }

    equity = equity_curve[["date", "net_equity", "daily_return"]].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    bench = benchmark[["date", "return", "equity"]].copy()
    bench["date"] = pd.to_datetime(bench["date"])
    merged = equity.merge(bench, on="date", how="inner")
    if len(merged) < 2:
        return {
            "benchmark_return": float("nan"),
            "excess_return": float("nan"),
            "information_ratio": float("nan"),
            "beta": float("nan"),
            "alpha": float("nan"),
            "up_capture": float("nan"),
            "down_capture": float("nan"),
            "monthly_win_rate_vs_benchmark": float("nan"),
        }

    strategy_return = merged["daily_return"].astype(float)
    benchmark_return = merged["return"].astype(float)
    excess = strategy_return - benchmark_return
    excess_std = excess.std(ddof=0)
    information_ratio = 0.0 if excess_std == 0 or pd.isna(excess_std) else float(excess.mean() / excess_std * (252**0.5))
    variance = benchmark_return.var(ddof=0)
    beta = 0.0 if variance == 0 or pd.isna(variance) else float(strategy_return.cov(benchmark_return) / variance)
    days = len(merged)
    bench_total = float(merged["equity"].iloc[-1] / merged["equity"].iloc[0] - 1.0)
    bench_annual = float((1.0 + bench_total) ** (252 / days) - 1.0)
    up = merged[benchmark_return > 0]
    down = merged[benchmark_return < 0]
    up_capture = 0.0 if up.empty or up["return"].mean() == 0 else float(up["daily_return"].mean() / up["return"].mean())
    down_capture = 0.0 if down.empty or down["return"].mean() == 0 else float(down["daily_return"].mean() / down["return"].mean())
    monthly = merged.set_index("date")[["daily_return", "return"]].resample("ME").apply(lambda x: (1.0 + x).prod() - 1.0)
    monthly_win = float((monthly["daily_return"] > monthly["return"]).mean()) if not monthly.empty else 0.0
    return {
        "benchmark_return": bench_total,
        "excess_return": float(metrics.get("total_return", 0.0) - bench_total),
        "information_ratio": information_ratio,
        "beta": beta,
        "alpha": float(metrics.get("annual_return", 0.0) - beta * bench_annual),
        "up_capture": up_capture,
        "down_capture": down_capture,
        "monthly_win_rate_vs_benchmark": monthly_win,
    }
