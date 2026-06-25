"""End-to-end data, strategy, backtest, and report orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.backtest.result import BacktestResult
from ashare_quant.config import AppConfig
from ashare_quant.data.akshare_provider import AKShareProvider, enrich_bars_with_akshare_metadata
from ashare_quant.data.base import DataProvider, ProviderUnavailable
from ashare_quant.data.storage import SQLiteStorage
from ashare_quant.data.tushare_provider import TushareProvider
from ashare_quant.report.performance_report import write_report
from ashare_quant.research.benchmark import benchmark_summary, load_benchmarks
from ashare_quant.research.exposure import write_exposure_reports
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
    symbols = resolve_symbols(config, refresh=refresh)
    cached_bars: pd.DataFrame | None = None
    try:
        cached_bars = storage.load_bars(symbols or None, config.data.start_date, config.data.end_date)
    except (FileNotFoundError, ValueError) as exc:
        LOGGER.info("Cache unavailable: %s", exc)

    if not refresh and cached_bars is not None and not cached_bars.empty and _cache_covers_symbols(cached_bars, symbols):
        LOGGER.info("Loaded %d cached bars from %s", len(cached_bars), storage.db_path)
        return _enrich_loaded_bars(config, cached_bars)
    if not refresh and cached_bars is not None and not cached_bars.empty:
        if symbols:
            LOGGER.warning(
                "Cached bars do not cover the requested candidate universe (%d symbols); using existing cache. "
                "Run download_data.py with refresh=True to expand the candidate pool.",
                len(symbols),
            )
            fallback_bars = _load_all_cached_bars(storage, config)
            if fallback_bars is not None and not fallback_bars.empty:
                return _enrich_loaded_bars(config, fallback_bars)
        else:
            LOGGER.warning("No explicit symbols are available for refresh; using existing real cache.")
        return _enrich_loaded_bars(config, cached_bars)
    if not refresh and symbols:
        fallback_bars = _load_all_cached_bars(storage, config)
        if fallback_bars is not None and not fallback_bars.empty:
            LOGGER.warning(
                "Cached bars have no overlap with the requested candidate universe (%d symbols); "
                "using all existing cache rows instead.",
                len(symbols),
            )
            return _enrich_loaded_bars(config, fallback_bars)
    if not refresh and (cached_bars is None or cached_bars.empty) and _is_large_candidate_request(config, symbols):
        raise ProviderUnavailable(
            "No usable local bar cache is available for the configured large candidate universe. "
            "Run scripts/download_data.py with --refresh to build or expand the cache explicitly."
        )

    cached_bars_all = _load_all_cached_bars(storage, config) if refresh else cached_bars
    cached_symbols = _cached_symbol_set(cached_bars)
    all_cached_symbols = _cached_symbol_set(cached_bars_all)
    date_range_complete = _cache_covers_date_range(cached_bars, config.data.start_date, config.data.end_date)
    if refresh:
        if symbols:
            missing_symbols = [symbol for symbol in symbols if symbol not in all_cached_symbols]
            symbols_to_fetch = symbols if not date_range_complete else missing_symbols
        elif all_cached_symbols:
            symbols_to_fetch = sorted(all_cached_symbols) if not date_range_complete else []
        else:
            symbols_to_fetch = []
    else:
        symbols_to_fetch = symbols

    if refresh and not symbols_to_fetch:
        if cached_bars is not None and not cached_bars.empty:
            LOGGER.info("Local cache already covers %d requested symbols and the configured date range.", len(cached_symbols))
            return _enrich_loaded_bars(config, cached_bars)
        if cached_bars_all is not None and not cached_bars_all.empty:
            LOGGER.info("Local cache already covers the configured date range; returning all cached bars.")
            return _enrich_loaded_bars(config, _filter_bars_to_symbols_or_all(cached_bars_all, symbols))
    if not symbols_to_fetch:
        raise ProviderUnavailable("No symbols are available for provider refresh.")

    try:
        provider = make_provider(config.data.provider)
        bars = _fetch_bars_in_batches(
            provider,
            symbols_to_fetch,
            config.data.start_date,
            config.data.end_date,
            config.data.adjust,
            config.data.download_batch_size,
        )
    except ProviderUnavailable as exc:
        fallback_bars = cached_bars if cached_bars is not None and not cached_bars.empty else cached_bars_all
        if fallback_bars is not None and not fallback_bars.empty:
            LOGGER.warning(
                "Provider %s unavailable (%s); keeping existing real cache with %d rows.",
                config.data.provider,
                exc,
                len(fallback_bars),
            )
            return _enrich_loaded_bars(config, _filter_bars_to_symbols_or_all(fallback_bars, symbols))
        raise

    combined = _merge_bar_frames(cached_bars_all, bars)
    storage.save_bars(combined, replace=True)
    LOGGER.info("Saved %d bars to %s", len(combined), storage.db_path)
    return _enrich_loaded_bars(config, _filter_bars_to_symbols(combined, symbols))


def resolve_symbols(config: AppConfig, refresh: bool = False) -> list[str]:
    """Resolve configured symbols or a candidate universe for downloading bars."""
    if config.data.symbols:
        return config.data.symbols[: config.data.max_symbols]
    if config.data.universe_mode == "fixed_symbols":
        return []
    if config.data.universe_type != "all_a_share_liquid":
        return []
    source = config.data.candidate_source.lower()
    cache_exists = Path(config.data.cache_path).exists()
    if source in {"cache", "local_cache"} and cache_exists:
        LOGGER.info("Dynamic liquidity mode uses all symbols available in the local cache.")
        return []
    if source in {"akshare_metadata", "metadata", "all_a_metadata", "full_a_share", "full_a_share_metadata"}:
        return _fetch_akshare_metadata_symbols(config, refresh=refresh)
    if source in {"current_snapshot", "current_liquidity_snapshot", "spot"}:
        return _fetch_akshare_symbols(config)
    if source in {"cache", "local_cache"} and not cache_exists:
        LOGGER.warning("Local cache candidate source requested but cache is missing; falling back to AKShare metadata candidates.")
        return _fetch_akshare_metadata_symbols(config, refresh=refresh)
    raise ProviderUnavailable(f"Unsupported data.candidate_source: {config.data.candidate_source}")


def _fetch_akshare_symbols(config: AppConfig) -> list[str]:
    try:
        symbols = _symbols_from_akshare_spot(config)
        LOGGER.info("Resolved %d AKShare symbols by real spot liquidity.", len(symbols))
        return symbols
    except Exception as exc:  # pragma: no cover - depends on external API
        LOGGER.warning("Unable to resolve live AKShare spot liquidity universe: %s", exc)

    cached = _symbols_from_liquidity_cache(config)
    if cached:
        LOGGER.info("Resolved %d symbols from existing real liquidity cache.", len(cached))
        return cached
    raise ProviderUnavailable("Unable to resolve real liquidity universe and no usable liquidity cache exists.")


def _fetch_akshare_metadata_symbols(config: AppConfig, refresh: bool = False) -> list[str]:
    """Resolve A-share candidates from AKShare code-name metadata, not current liquidity."""
    cache_path = Path(config.data.candidate_symbols_path)
    cached = _load_candidate_symbols_file(cache_path, config)
    if cached and not refresh:
        LOGGER.info("Loaded %d cached metadata candidate symbols from %s.", len(cached), cache_path)
        return cached
    try:
        import akshare as ak  # type: ignore

        raw = ak.stock_info_a_code_name()
        symbols = _symbols_from_metadata_frame(raw, config)
        if symbols:
            LOGGER.info("Resolved %d AKShare metadata candidate symbols.", len(symbols))
            _store_candidate_symbols_file(cache_path, symbols)
            return symbols
    except Exception as exc:  # pragma: no cover - depends on external API
        LOGGER.warning("Unable to resolve AKShare metadata candidates: %s", exc)

    if cached:
        LOGGER.warning("Using stale metadata candidate symbol cache from %s.", cache_path)
        return cached

    cached = _symbols_from_liquidity_cache(config)
    if cached:
        LOGGER.info("Resolved %d symbols from existing real liquidity cache.", len(cached))
        return cached
    raise ProviderUnavailable("Unable to resolve AKShare metadata candidates and no usable cache exists.")


def _symbols_from_metadata_frame(raw: pd.DataFrame, config: AppConfig) -> list[str]:
    """Normalize AKShare code-name metadata into exchange-qualified symbols."""
    if raw.empty:
        return []
    code_col = _find_column(raw, ["code"], None) or _find_column(raw, ["\u4ee3\u7801"], 0) or str(raw.columns[0])
    name_col = _find_column(raw, ["name"], None) or _find_column(raw, ["\u540d\u79f0"], 1)
    data = raw.copy()
    data[code_col] = data[code_col].astype(str).str.split(".", expand=True).iloc[:, 0].str.zfill(6)
    if name_col is not None and config.data.exclude_st:
        data = data[~data[name_col].astype(str).str.contains("ST", case=False, na=False)]
    codes = (
        data[code_col]
        .dropna()
        .astype(str)
        .str.strip()
        .loc[lambda s: (s != "") & (s.str.lower() != "nan")]
        .drop_duplicates()
        .sort_values()
        .head(config.data.max_symbols)
        .tolist()
    )
    return [_symbol_from_code(code) for code in codes]


def _load_candidate_symbols_file(path: Path, config: AppConfig) -> list[str]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    symbols = [line.strip() for line in lines if line.strip()]
    if config.data.max_symbols > 0:
        symbols = symbols[: config.data.max_symbols]
    return symbols


def _store_candidate_symbols_file(path: Path, symbols: list[str]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(symbols) + "\n", encoding="utf-8")
    except Exception as exc:  # pragma: no cover - filesystem dependent
        LOGGER.warning("Unable to persist candidate symbol cache %s: %s", path, exc)


def _symbols_from_akshare_spot(config: AppConfig) -> list[str]:
    import akshare as ak  # type: ignore

    raw = ak.stock_zh_a_spot_em()
    code_col = _find_column(raw, ["\u4ee3\u7801"], 1)
    name_col = _find_column(raw, ["\u540d\u79f0"], 2)
    amount_col = _find_column(raw, ["\u6210\u4ea4\u989d"], 7)
    if code_col is None or amount_col is None:
        raise ProviderUnavailable("AKShare spot data does not contain code/amount columns.")

    data = raw.copy()
    data[code_col] = data[code_col].astype(str).str.split(".", expand=True).iloc[:, 0].str.zfill(6)
    if name_col is not None and config.data.exclude_st:
        data = data[~data[name_col].astype(str).str.contains("ST", case=False, na=False)]
    data[amount_col] = pd.to_numeric(data[amount_col], errors="coerce").fillna(0.0)
    data = data.sort_values(amount_col, ascending=False)
    codes = data[code_col].head(config.data.max_symbols).tolist()
    return [_symbol_from_code(code) for code in codes]


def _symbols_from_liquidity_cache(config: AppConfig) -> list[str]:
    cache_path = Path(config.data.cache_path)
    if not cache_path.exists():
        return []
    try:
        bars = SQLiteStorage(cache_path).load_bars(start_date=config.data.start_date, end_date=config.data.end_date)
    except Exception:
        return []
    if bars.empty or "amount" not in bars.columns:
        return []
    recent_dates = pd.DatetimeIndex(pd.to_datetime(bars["date"]).drop_duplicates().sort_values())
    if recent_dates.empty:
        return []
    selected_dates = set(recent_dates[-config.data.liquidity_window :])
    recent = bars[bars["date"].isin(selected_dates)]
    ranked = recent.groupby("symbol")["amount"].mean().sort_values(ascending=False)
    return ranked.head(config.data.max_symbols).index.astype(str).tolist()


def _enrich_loaded_bars(config: AppConfig, bars: pd.DataFrame) -> pd.DataFrame:
    if config.data.provider.lower() != "akshare":
        return bars
    return enrich_bars_with_akshare_metadata(bars)


def _load_all_cached_bars(storage: SQLiteStorage, config: AppConfig) -> pd.DataFrame | None:
    try:
        return storage.load_bars(start_date=config.data.start_date, end_date=config.data.end_date)
    except (FileNotFoundError, ValueError) as exc:
        LOGGER.info("Full cache unavailable: %s", exc)
        return None


def _cached_symbol_set(cached_bars: pd.DataFrame | None) -> set[str]:
    if cached_bars is None or cached_bars.empty or "symbol" not in cached_bars.columns:
        return set()
    return set(cached_bars["symbol"].astype(str).unique())


def _cache_covers_symbols(cached_bars: pd.DataFrame | None, symbols: list[str]) -> bool:
    if not symbols:
        return True
    return set(symbols).issubset(_cached_symbol_set(cached_bars))


def _cache_covers_date_range(cached_bars: pd.DataFrame | None, start_date: str, end_date: str) -> bool:
    if cached_bars is None or cached_bars.empty or "date" not in cached_bars.columns:
        return False
    dates = pd.to_datetime(cached_bars["date"], errors="coerce").dropna()
    if dates.empty:
        return False
    return dates.min() <= pd.Timestamp(start_date) and dates.max() >= pd.Timestamp(end_date)


def _is_large_candidate_request(config: AppConfig, symbols: list[str]) -> bool:
    if not symbols:
        return False
    return config.data.universe_mode == "dynamic_liquidity" and len(symbols) >= 100


def _fetch_bars_in_batches(
    provider: DataProvider,
    symbols: list[str],
    start_date: str,
    end_date: str,
    adjust: str,
    batch_size: int,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    effective_batch_size = max(1, int(batch_size or 1))
    total = len(symbols)
    for start in range(0, total, effective_batch_size):
        batch = symbols[start : start + effective_batch_size]
        LOGGER.info(
            "Fetching bars for symbols %d-%d of %d.",
            start + 1,
            start + len(batch),
            total,
        )
        try:
            frame = provider.fetch_bars(
                symbols=batch,
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )
        except ProviderUnavailable as exc:
            LOGGER.warning("Provider returned no usable bars for batch starting at %s: %s", batch[0], exc)
            continue
        if not frame.empty:
            frames.append(frame)
    if not frames:
        raise ProviderUnavailable("Provider returned no usable bars for any requested batch.")
    return pd.concat(frames, ignore_index=True)


def _merge_bar_frames(existing: pd.DataFrame | None, fetched: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in [existing, fetched] if frame is not None and not frame.empty]
    if not frames:
        raise ProviderUnavailable("No bars are available to save.")
    merged = pd.concat(frames, ignore_index=True)
    sort_cols = [col for col in ["date", "symbol"] if col in merged.columns]
    if sort_cols:
        merged = merged.drop_duplicates(subset=sort_cols, keep="last")
    return merged


def _filter_bars_to_symbols(bars: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if not symbols or bars.empty or "symbol" not in bars.columns:
        return bars
    return bars[bars["symbol"].astype(str).isin(set(symbols))].copy()


def _filter_bars_to_symbols_or_all(bars: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    filtered = _filter_bars_to_symbols(bars, symbols)
    if symbols and filtered.empty and not bars.empty:
        return bars
    return filtered


def _find_column(frame: pd.DataFrame, keywords: list[str], fallback_index: int | None) -> str | None:
    for column in frame.columns:
        text = str(column)
        if all(keyword in text for keyword in keywords):
            return str(column)
    if fallback_index is not None and fallback_index < len(frame.columns):
        return str(frame.columns[fallback_index])
    return None


def _symbol_from_code(code: object) -> str:
    text = str(code).strip().split(".")[0].zfill(6)
    if text.startswith(("8", "4", "920")):
        return f"{text}.BJ"
    if text.startswith("6"):
        return f"{text}.SH"
    return f"{text}.SZ"


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
        _write_universe_reports(strategy, Path(config.report.output_dir))
        try:
            benchmarks = load_benchmarks(config, bars)
        except Exception as exc:  # pragma: no cover - depends on external data
            LOGGER.warning("Unable to load benchmarks for exposure report: %s", exc)
            benchmarks = pd.DataFrame()
        write_exposure_reports(result, bars, benchmarks, Path(config.report.output_dir))
        LOGGER.info("Reports written to %s", config.report.output_dir)
    return result


def _write_universe_reports(strategy: MultiFactorRotationStrategy, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    strategy.universe_diagnostics.to_csv(output_dir / "universe_diagnostics.csv", index=False)
    strategy.daily_universe_size.to_csv(output_dir / "daily_universe_size.csv", index=False)


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
