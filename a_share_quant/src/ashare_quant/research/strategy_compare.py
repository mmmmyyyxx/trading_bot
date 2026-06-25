"""Named-strategy comparisons against multiple benchmarks."""

from __future__ import annotations

import copy
import logging

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.research.benchmark import BENCHMARKS, load_benchmarks
from ashare_quant.research.parallel import SharedFrameStore, process_map, read_shared_frame
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags
from ashare_quant.strategy.profiles import apply_strategy_profile, get_strategy_profile, profile_names

LOGGER = logging.getLogger(__name__)


def run_strategy_comparison(
    config: AppConfig,
    bars: pd.DataFrame,
    strategies: list[str] | None = None,
    benchmarks: list[str] | None = None,
    benchmark_frame: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Run named strategy profiles and compare each against configured benchmarks."""
    strategies = strategies or profile_names()
    benchmarks = benchmarks or list(BENCHMARKS)
    if benchmark_frame is None:
        try:
            benchmark_frame = load_benchmarks(config, bars)
        except Exception:
            benchmark_frame = pd.DataFrame()
    enriched = build_strategy_universe_flags(config, bars)
    factor_cache = _precompute_factor_cache(config, bars, strategies)

    with SharedFrameStore(config.report.output_dir) as store:
        bars_path = store.write("strategy_compare_bars", bars)
        enriched_path = store.write("strategy_compare_enriched", enriched)
        benchmark_path = store.write("strategy_compare_benchmarks", benchmark_frame)
        factor_paths = {key: store.write(f"strategy_compare_factors_{idx}", frame) for idx, (key, frame) in enumerate(factor_cache.items())}
        jobs = [(config, strategy_name, benchmarks, bars_path, enriched_path, benchmark_path, factor_paths) for strategy_name in strategies]
        row_groups = process_map(jobs, _run_strategy_compare_job, max_workers=config.report.parallel_workers)
    rows = [row for group in row_groups for row in group]
    return pd.DataFrame(rows)


def _run_strategy_compare_job(
    job: tuple[AppConfig, str, list[str], str, str, str, dict[tuple[object, ...], str]],
) -> list[dict[str, object]]:
    config, strategy_name, benchmarks, bars_path, enriched_path, benchmark_path, factor_paths = job
    LOGGER.info("Running strategy comparison for %s.", strategy_name)
    bars = read_shared_frame(bars_path)
    enriched = read_shared_frame(enriched_path)
    benchmark_frame = read_shared_frame(benchmark_path)
    cfg = copy.deepcopy(config)
    cfg.strategy.name = strategy_name
    profile = get_strategy_profile(strategy_name)
    if profile is not None:
        cfg.strategy.weighting = profile.default_weighting
    cfg.report.make_plots = False
    factor_scores = read_shared_frame(factor_paths[_factor_cache_key(apply_strategy_profile(cfg))], cache=False)
    strategy = MultiFactorRotationStrategy(cfg)
    strategy._benchmark_cache = benchmark_frame
    targets = strategy.generate_targets(bars, factor_scores=factor_scores, enriched_bars=enriched)
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
    rows: list[dict[str, object]] = []
    for benchmark in benchmarks:
        selected = benchmark_frame[benchmark_frame["benchmark"].str.lower() == benchmark.lower()].copy()
        rel = _relative_metrics(result.equity_curve, selected, result.metrics)
        rows.append({**base, "benchmark": benchmark, **rel, **_evaluation_fields(strategy_name, base, rel)})
    return rows


def _evaluation_fields(
    strategy_name: str,
    metrics: dict[str, object],
    relative_metrics: dict[str, float],
) -> dict[str, object]:
    """Return acceptance diagnostics for defensive and return-seeking profiles."""
    if strategy_name == "defensive_low_vol":
        beta = float(relative_metrics.get("beta", float("nan")))
        down_capture = float(relative_metrics.get("down_capture", float("nan")))
        max_drawdown = float(metrics.get("max_drawdown", float("nan")))
        calmar = float(metrics.get("calmar", float("nan")))
        passed = max_drawdown >= -0.15 and calmar > 0 and beta <= 0.70 and down_capture <= 0.80
        return {
            "evaluation_class": "defensive",
            "primary_metrics": "max_drawdown,calmar,down_capture,beta",
            "acceptance_rule": "max_drawdown>=-15%, calmar>0, beta<=0.70, down_capture<=0.80",
            "acceptance_pass": bool(passed),
        }

    excess = float(relative_metrics.get("excess_return", float("nan")))
    information_ratio = float(relative_metrics.get("information_ratio", float("nan")))
    monthly_win = float(relative_metrics.get("monthly_win_rate_vs_benchmark", float("nan")))
    passed = excess > 0 and information_ratio > 0 and monthly_win > 0.50
    return {
        "evaluation_class": "return_seeking",
        "primary_metrics": "excess_return,information_ratio,monthly_win_rate_vs_benchmark,up_capture",
        "acceptance_rule": "excess_return>0, information_ratio>0, monthly_win_rate_vs_benchmark>50%",
        "acceptance_pass": bool(passed),
    }


def _precompute_factor_cache(
    config: AppConfig,
    bars: pd.DataFrame,
    strategies: list[str],
) -> dict[tuple[object, ...], pd.DataFrame]:
    cache: dict[tuple[object, ...], pd.DataFrame] = {}
    for strategy_name in strategies:
        cfg = copy.deepcopy(config)
        cfg.strategy.name = strategy_name
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
