"""Walk-forward parameter selection diagnostics."""

from __future__ import annotations

import copy
import itertools
import logging
from dataclasses import dataclass

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.research.parallel import SharedFrameStore, process_map, read_shared_frame
from ashare_quant.research.strategy_compare import _relative_metrics
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy, build_strategy_universe_flags
from ashare_quant.strategy.profiles import apply_strategy_profile, profile_names

LOGGER = logging.getLogger(__name__)


OUTPUT_COLUMNS = [
    "train_start",
    "train_end",
    "test_start",
    "test_end",
    "selected_strategy",
    "selected_top_k",
    "selected_weighting",
    "selected_rebalance",
    "selected_momentum_window",
    "selected_skip",
    "train_score",
    "train_total_return",
    "train_sharpe",
    "train_ir",
    "test_total_return",
    "test_excess_return",
    "test_sharpe",
    "test_ir",
    "test_max_drawdown",
    "test_calmar",
    "test_beta",
    "test_up_capture",
    "test_down_capture",
]


@dataclass(frozen=True)
class Candidate:
    strategy_name: str
    top_k: int
    weighting: str
    rebalance_frequency: str
    momentum_window: int
    momentum_skip: int


def run_walk_forward_selection(
    config: AppConfig,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame | None = None,
    train_months: int = 12,
    test_months: int = 6,
    strategy_names: list[str] | None = None,
    top_k_values: list[int] | None = None,
    weighting_values: list[str] | None = None,
    rebalance_values: list[str] | None = None,
    momentum_windows: list[int] | None = None,
    skip_windows: list[int] | None = None,
) -> pd.DataFrame:
    """Select parameters on each train window and evaluate them on the next test window."""
    strategy_names = strategy_names or profile_names()
    top_k_values = top_k_values or [30, 50, 80]
    weighting_values = weighting_values or ["equal_weight", "inverse_vol_weight"]
    rebalance_values = rebalance_values or ["W", "M"]
    momentum_windows = momentum_windows or [60, 120, 180]
    skip_windows = skip_windows or [5, 20]

    windows = _walk_windows(bars, train_months, test_months)
    if not windows:
        return pd.DataFrame(columns=OUTPUT_COLUMNS)

    if benchmarks is None:
        try:
            benchmark_frame = load_benchmarks(config, bars)
        except Exception:
            benchmark_frame = pd.DataFrame()
    else:
        benchmark_frame = benchmarks

    candidates = [
        Candidate(strategy, top_k, weighting, rebalance, momentum_window, skip)
        for strategy, top_k, weighting, rebalance, momentum_window, skip in itertools.product(
            strategy_names,
            top_k_values,
            weighting_values,
            rebalance_values,
            momentum_windows,
            skip_windows,
        )
    ]
    LOGGER.info("Walk-forward selection windows=%d candidates=%d.", len(windows), len(candidates))
    enriched = build_strategy_universe_flags(config, bars)
    factor_cache: dict[tuple[object, ...], pd.DataFrame] = {}
    target_cache: dict[Candidate, tuple[AppConfig, pd.DataFrame]] = {}
    for candidate in candidates:
        _candidate_config_and_targets(config, bars, candidate, target_cache, factor_cache, enriched, benchmark_frame)

    train_rows = _run_train_candidate_jobs(config, bars, benchmark_frame, windows, target_cache)
    train_by_window = (
        {
            (pd.Timestamp(train_start), pd.Timestamp(train_end)): group
            for (train_start, train_end), group in train_rows.groupby(["train_start", "train_end"], sort=False)
        }
        if not train_rows.empty
        else {}
    )

    rows: list[dict[str, object]] = []
    for train_start, train_end, test_start, test_end in windows:
        scored = _score_candidates(train_by_window.get((pd.Timestamp(train_start), pd.Timestamp(train_end)), pd.DataFrame()))
        if scored.empty:
            continue
        best = scored.sort_values(["train_score", "train_sharpe", "train_total_return"], ascending=False).iloc[0]
        selected: Candidate = best["candidate"]
        selected_cfg, selected_targets = target_cache[selected]
        test_result = _run_window(selected_cfg, bars, selected_targets, test_start, test_end)
        test_rel = _relative_for_config(test_result.equity_curve, benchmark_frame, selected_cfg, test_result.metrics)
        rows.append(
            {
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "selected_strategy": selected.strategy_name,
                "selected_top_k": selected.top_k,
                "selected_weighting": selected.weighting,
                "selected_rebalance": selected.rebalance_frequency,
                "selected_momentum_window": selected.momentum_window,
                "selected_skip": selected.momentum_skip,
                "train_score": float(best["train_score"]),
                "train_total_return": float(best["train_total_return"]),
                "train_sharpe": float(best["train_sharpe"]),
                "train_ir": float(best["train_ir"]),
                "test_total_return": test_result.metrics["total_return"],
                "test_excess_return": test_rel.get("excess_return", float("nan")),
                "test_sharpe": test_result.metrics["sharpe"],
                "test_ir": test_rel.get("information_ratio", float("nan")),
                "test_max_drawdown": test_result.metrics["max_drawdown"],
                "test_calmar": test_result.metrics["calmar"],
                "test_beta": test_rel.get("beta", float("nan")),
                "test_up_capture": test_rel.get("up_capture", float("nan")),
                "test_down_capture": test_rel.get("down_capture", float("nan")),
            }
        )
    return pd.DataFrame(rows, columns=OUTPUT_COLUMNS)


def _candidate_config_and_targets(
    config: AppConfig,
    bars: pd.DataFrame,
    candidate: Candidate,
    cache: dict[Candidate, tuple[AppConfig, pd.DataFrame]],
    factor_cache: dict[tuple[object, ...], pd.DataFrame],
    enriched: pd.DataFrame,
    benchmarks: pd.DataFrame | None = None,
) -> tuple[AppConfig, pd.DataFrame]:
    if candidate in cache:
        return cache[candidate]
    cfg = copy.deepcopy(config)
    cfg.strategy.name = candidate.strategy_name
    cfg.strategy.top_k = candidate.top_k
    cfg.strategy.weighting = candidate.weighting
    cfg.strategy.rebalance_frequency = candidate.rebalance_frequency
    cfg.factors.momentum_window = candidate.momentum_window
    cfg.factors.momentum_skip = candidate.momentum_skip
    cfg.report.make_plots = False
    factor_scores = _cached_factor_scores(cfg, bars, factor_cache)
    strategy = MultiFactorRotationStrategy(cfg)
    if benchmarks is not None:
        strategy._benchmark_cache = benchmarks
    targets = strategy.generate_targets(bars, factor_scores=factor_scores, enriched_bars=enriched)
    cache[candidate] = (cfg, targets)
    return cfg, targets


def _run_train_candidate_jobs(
    config: AppConfig,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame,
    windows: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]],
    target_cache: dict[Candidate, tuple[AppConfig, pd.DataFrame]],
) -> pd.DataFrame:
    if not windows or not target_cache:
        return pd.DataFrame()
    with SharedFrameStore(config.report.output_dir) as store:
        bars_path = store.write("walk_forward_selection_bars", bars)
        benchmarks_path = store.write("walk_forward_selection_benchmarks", benchmarks)
        target_paths = {
            candidate: store.write(f"walk_forward_selection_targets_{idx}", targets)
            for idx, (candidate, (_, targets)) in enumerate(target_cache.items())
        }
        jobs = [
            (
                cfg,
                candidate,
                bars_path,
                target_paths[candidate],
                benchmarks_path,
                pd.Timestamp(train_start),
                pd.Timestamp(train_end),
            )
            for train_start, train_end, _, _ in windows
            for candidate, (cfg, _) in target_cache.items()
        ]
        rows = process_map(jobs, _run_train_candidate_job, max_workers=config.report.parallel_workers)
    return pd.DataFrame(rows)


def _run_train_candidate_job(
    job: tuple[AppConfig, Candidate, str, str, str, pd.Timestamp, pd.Timestamp],
) -> dict[str, object]:
    config, candidate, bars_path, targets_path, benchmarks_path, train_start, train_end = job
    bars = read_shared_frame(bars_path)
    targets = read_shared_frame(targets_path, cache=False)
    benchmarks = read_shared_frame(benchmarks_path)
    train_result = _run_window(config, bars, targets, train_start, train_end)
    rel = _relative_for_config(train_result.equity_curve, benchmarks, config, train_result.metrics)
    return {
        "train_start": train_start,
        "train_end": train_end,
        "candidate": candidate,
        "train_total_return": train_result.metrics["total_return"],
        "train_sharpe": train_result.metrics["sharpe"],
        "train_ir": rel.get("information_ratio", 0.0),
        "train_calmar": train_result.metrics["calmar"],
        "monthly_win_rate_vs_benchmark": rel.get("monthly_win_rate_vs_benchmark", 0.0),
        "turnover_penalty": train_result.metrics.get("average_turnover", 0.0),
    }


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


def _run_window(
    config: AppConfig,
    bars: pd.DataFrame,
    targets: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
):
    cfg = copy.deepcopy(config)
    cfg.backtest.start_date = pd.Timestamp(start).strftime("%Y-%m-%d")
    cfg.backtest.end_date = pd.Timestamp(end).strftime("%Y-%m-%d")
    cfg.backtest.save_positions = False
    return BacktestEngine(cfg).run(bars, targets)


def _relative_for_config(
    equity_curve: pd.DataFrame,
    benchmarks: pd.DataFrame,
    config: AppConfig,
    metrics: dict[str, float],
) -> dict[str, float]:
    key = (config.data.benchmark_symbol or "hs300").lower()
    selected = benchmarks[benchmarks["benchmark"].str.lower() == key].copy() if not benchmarks.empty else pd.DataFrame()
    if selected.empty and not benchmarks.empty:
        selected = benchmarks[benchmarks["benchmark"] == benchmarks["benchmark"].iloc[0]].copy()
    return _relative_metrics(equity_curve, selected, metrics)


def _score_candidates(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    scored = frame.copy()
    scored["train_score"] = (
        0.35 * _zscore(scored["train_sharpe"])
        + 0.25 * _zscore(scored["train_ir"])
        + 0.20 * _zscore(scored["train_calmar"])
        + 0.10 * scored["monthly_win_rate_vs_benchmark"].fillna(0.0)
        - 0.10 * _zscore(scored["turnover_penalty"])
    )
    return scored


def _zscore(values: pd.Series) -> pd.Series:
    clean = pd.to_numeric(values, errors="coerce").replace([float("inf"), float("-inf")], pd.NA).fillna(0.0)
    std = clean.std(ddof=0)
    if std == 0 or pd.isna(std):
        return pd.Series(0.0, index=values.index)
    return (clean - clean.mean()) / std


def _walk_windows(bars: pd.DataFrame, train_months: int, test_months: int) -> list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]]:
    dates = pd.DatetimeIndex(pd.to_datetime(bars["date"]).drop_duplicates().sort_values())
    if dates.empty:
        return []
    windows: list[tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]] = []
    train_start = pd.Timestamp(dates[0])
    while True:
        train_boundary = train_start + pd.DateOffset(months=train_months)
        train_candidates = dates[dates <= train_boundary]
        train_candidates = train_candidates[train_candidates >= train_start]
        if train_candidates.empty:
            break
        train_end = pd.Timestamp(train_candidates[-1])
        test_candidates = dates[dates > train_end]
        if test_candidates.empty:
            break
        test_start = pd.Timestamp(test_candidates[0])
        test_boundary = test_start + pd.DateOffset(months=test_months)
        test_candidates = dates[(dates >= test_start) & (dates <= test_boundary)]
        if len(test_candidates) < 2:
            break
        test_end = pd.Timestamp(test_candidates[-1])
        windows.append((train_start, train_end, test_start, test_end))
        next_train = dates[dates > test_end]
        if next_train.empty:
            break
        train_start = pd.Timestamp(next_train[0])
    return windows
