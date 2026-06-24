"""End-to-end data, strategy, backtest, and report orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.backtest.result import BacktestResult
from ashare_quant.config import AppConfig
from ashare_quant.data.akshare_provider import AKShareProvider
from ashare_quant.data.base import DataProvider, ProviderUnavailable
from ashare_quant.data.storage import SQLiteStorage
from ashare_quant.data.tushare_provider import TushareProvider
from ashare_quant.report.performance_report import write_report
from ashare_quant.research.benchmark import benchmark_summary, load_benchmarks
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy

LOGGER = logging.getLogger(__name__)


def make_provider(name: str) -> DataProvider:
    """Build a provider by name."""
    lowered = name.lower()
    if lowered == "akshare":
        return AKShareProvider()
    if lowered == "tushare":
        return TushareProvider()
    raise ProviderUnavailable(f"Unknown data provider: {name}")


def load_market_data(config: AppConfig, refresh: bool = False) -> pd.DataFrame:
    """Load cached bars or fetch them from the configured provider."""
    storage = SQLiteStorage(config.data.cache_path)
    symbols = resolve_symbols(config)
    cached_bars: pd.DataFrame | None = None
    try:
        cached_bars = storage.load_bars(symbols or None, config.data.start_date, config.data.end_date)
    except (FileNotFoundError, ValueError) as exc:
        LOGGER.info("Cache unavailable: %s", exc)

    if not refresh:
        if cached_bars is not None and not cached_bars.empty:
            LOGGER.info("Loaded %d cached bars from %s", len(cached_bars), storage.db_path)
            return cached_bars

    try:
        provider = make_provider(config.data.provider)
        bars = provider.fetch_bars(
            symbols=symbols,
            start_date=config.data.start_date,
            end_date=config.data.end_date,
            adjust=config.data.adjust,
        )
    except ProviderUnavailable as exc:
        if cached_bars is not None and not cached_bars.empty:
            LOGGER.warning(
                "Provider %s unavailable (%s); keeping existing cache with %d rows.",
                config.data.provider,
                exc,
                len(cached_bars),
            )
            return cached_bars
        raise

    storage.save_bars(bars, replace=True)
    LOGGER.info("Saved %d bars to %s", len(bars), storage.db_path)
    return bars


def resolve_symbols(config: AppConfig) -> list[str]:
    """Resolve configured symbols or a real AKShare all-A universe."""
    if config.data.symbols:
        return config.data.symbols[: config.data.max_symbols]
    if config.data.universe_type != "all_a_share_liquid":
        return []
    return _fetch_akshare_symbols(config)


def _fetch_akshare_symbols(config: AppConfig) -> list[str]:
    try:
        import akshare as ak  # type: ignore

        raw = ak.stock_info_a_code_name()
        code_col = "code" if "code" in raw.columns else raw.columns[0]
        name_col = "name" if "name" in raw.columns else (raw.columns[1] if len(raw.columns) > 1 else None)
        data = raw.copy()
        data[code_col] = data[code_col].astype(str).str.zfill(6)
        if name_col is not None and config.data.exclude_st:
            data = data[~data[name_col].astype(str).str.contains("ST", case=False, na=False)]
        codes = data[code_col].tolist()
        symbols = [f"{code}.SH" if code.startswith("6") else f"{code}.SZ" for code in codes]
        LOGGER.info("Resolved %d AKShare A-share symbols; using first %d.", len(symbols), config.data.max_symbols)
        return symbols[: config.data.max_symbols]
    except Exception as exc:  # pragma: no cover - depends on external API
        raise ProviderUnavailable(f"Unable to fetch AKShare stock list: {exc}") from exc


def run_backtest_pipeline(config: AppConfig, refresh_data: bool = False, write_outputs: bool = True) -> BacktestResult:
    """Run the full MVP pipeline and optionally write reports."""
    bars = load_market_data(config, refresh=refresh_data)
    strategy = MultiFactorRotationStrategy(config)
    targets = strategy.generate_targets(bars)
    targets = _filter_targets_to_backtest_window(targets, config)
    LOGGER.info("Generated %d target-weight rows.", len(targets))
    result = BacktestEngine(config).run(bars, targets)
    _attach_benchmark_return(result, config, bars)
    if write_outputs:
        write_report(result, Path(config.report.output_dir), make_plots=config.report.make_plots)
        LOGGER.info("Reports written to %s", config.report.output_dir)
    return result


def _attach_benchmark_return(result: BacktestResult, config: AppConfig, bars: pd.DataFrame) -> None:
    """Attach configured benchmark cumulative return to the metrics dict."""
    try:
        benchmarks = load_benchmarks(config, bars)
        summary = benchmark_summary(benchmarks)
    except Exception as exc:  # pragma: no cover - depends on external data
        LOGGER.warning("Unable to load benchmark return: %s", exc)
        return
    key = (config.data.benchmark_symbol or "hs300").lower()
    selected = summary[summary["benchmark"].str.lower() == key]
    if selected.empty:
        selected = summary.head(1)
    if not selected.empty:
        result.metrics["benchmark_return"] = float(selected["benchmark_return"].iloc[0])
        benchmark_key = str(selected["benchmark"].iloc[0])
        benchmark_frame = benchmarks[benchmarks["benchmark"] == benchmark_key]
        result.metrics.update(_relative_metrics(result.equity_curve, benchmark_frame, result.metrics))


def _filter_targets_to_backtest_window(targets: pd.DataFrame, config: AppConfig) -> pd.DataFrame:
    if targets.empty:
        return targets
    filtered = targets.copy()
    filtered["date"] = pd.to_datetime(filtered["date"])
    if config.backtest.start_date:
        filtered = filtered[filtered["date"] >= pd.Timestamp(config.backtest.start_date)]
    if config.backtest.end_date:
        filtered = filtered[filtered["date"] <= pd.Timestamp(config.backtest.end_date)]
    return filtered.reset_index(drop=True)


def _relative_metrics(equity_curve: pd.DataFrame, benchmark: pd.DataFrame, metrics: dict[str, float]) -> dict[str, float]:
    equity = equity_curve[["date", "net_equity", "daily_return"]].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    bench = benchmark[["date", "return", "equity"]].copy()
    bench["date"] = pd.to_datetime(bench["date"])
    merged = equity.merge(bench, on="date", how="inner")
    if len(merged) < 2:
        return {}

    strategy_return = merged["daily_return"].astype(float)
    benchmark_return = merged["return"].astype(float)
    excess_daily = strategy_return - benchmark_return
    tracking_error = float(excess_daily.std(ddof=0) * (252**0.5))
    information_ratio = 0.0 if tracking_error == 0 else float(excess_daily.mean() / excess_daily.std(ddof=0) * (252**0.5))
    variance = benchmark_return.var(ddof=0)
    beta = 0.0 if variance == 0 else float(strategy_return.cov(benchmark_return) / variance)
    days = len(merged)
    bench_total = float(merged["equity"].iloc[-1] / merged["equity"].iloc[0] - 1.0)
    bench_annual = float((1.0 + bench_total) ** (252 / days) - 1.0)
    alpha = float(metrics.get("annual_return", 0.0) - beta * bench_annual)
    up = merged[benchmark_return > 0]
    down = merged[benchmark_return < 0]
    up_capture = 0.0 if up.empty or up["return"].mean() == 0 else float(up["daily_return"].mean() / up["return"].mean())
    down_capture = 0.0 if down.empty or down["return"].mean() == 0 else float(down["daily_return"].mean() / down["return"].mean())
    strategy_norm = merged["net_equity"] / merged["net_equity"].iloc[0]
    bench_norm = merged["equity"] / merged["equity"].iloc[0]
    relative_curve = strategy_norm / bench_norm
    relative_drawdown = float((relative_curve / relative_curve.cummax() - 1.0).min())
    monthly = merged.set_index("date")[["daily_return", "return"]].resample("ME").apply(lambda x: (1.0 + x).prod() - 1.0)
    monthly_win = float((monthly["daily_return"] > monthly["return"]).mean()) if not monthly.empty else 0.0
    return {
        "benchmark_return": bench_total,
        "excess_return": float(metrics.get("total_return", 0.0) - bench_total),
        "tracking_error": tracking_error,
        "information_ratio": information_ratio,
        "beta": beta,
        "alpha": alpha,
        "up_capture": up_capture,
        "down_capture": down_capture,
        "relative_drawdown": relative_drawdown,
        "monthly_win_rate_vs_benchmark": monthly_win,
    }
