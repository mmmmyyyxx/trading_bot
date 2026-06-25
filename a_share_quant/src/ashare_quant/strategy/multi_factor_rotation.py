"""Daily A-share multi-factor rotation strategy."""

from __future__ import annotations

import logging

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.data.calendar import next_trading_day, rebalance_signal_dates, trading_days_from_bars
from ashare_quant.data.universe import add_universe_flags, build_universe_diagnostics, daily_universe_size, select_universe_on
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.portfolio.weighting import build_target_weights
from ashare_quant.research.benchmark import load_benchmarks
from ashare_quant.strategy.base import Strategy
from ashare_quant.strategy.profiles import apply_strategy_profile

LOGGER = logging.getLogger(__name__)


def build_strategy_universe_flags(config: AppConfig, bars: pd.DataFrame) -> pd.DataFrame:
    """Build backward-looking universe flags using the strategy's data settings."""
    cfg = apply_strategy_profile(config)
    universe_mode = cfg.data.universe_mode
    liquidity_window = cfg.data.universe_liquidity_window if universe_mode == "dynamic_liquidity" else cfg.data.liquidity_window
    min_amount = cfg.data.universe_min_amount if universe_mode == "dynamic_liquidity" else cfg.data.min_amount
    return add_universe_flags(
        bars,
        min_listed_days=cfg.data.min_listed_days,
        min_amount=min_amount,
        liquidity_window=liquidity_window,
        liquidity_top_pct=None if universe_mode == "dynamic_liquidity" else cfg.data.liquidity_top_pct,
        exclude_st=cfg.data.exclude_st,
        exclude_paused=cfg.data.exclude_paused,
        exclude_limit_buy=cfg.data.exclude_limit_buy,
    )


class MultiFactorRotationStrategy(Strategy):
    """Monthly top-K rotation using backward-looking A-share factors."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._benchmark_cache: pd.DataFrame | None = None
        self.universe_diagnostics = pd.DataFrame()
        self.daily_universe_size = pd.DataFrame()

    def generate_targets(
        self,
        bars: pd.DataFrame,
        factor_scores: pd.DataFrame | None = None,
        enriched_bars: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Generate target weights for execution on the next trading day."""
        cfg = self._effective_config()
        days = trading_days_from_bars(bars)
        universe_mode = cfg.data.universe_mode
        enriched = enriched_bars if enriched_bars is not None else build_strategy_universe_flags(cfg, bars)
        factor_scores = factor_scores if factor_scores is not None else compute_composite_factors(bars, cfg.factors)
        signal_dates = rebalance_signal_dates(days, cfg.strategy.rebalance_frequency)
        self.universe_diagnostics = build_universe_diagnostics(
            enriched,
            signal_dates,
            universe_mode=universe_mode,
            top_n=cfg.data.universe_top_n,
            candidate_source=cfg.data.candidate_source,
        )
        self.daily_universe_size = daily_universe_size(self.universe_diagnostics)

        rows: list[pd.DataFrame] = []
        for signal_date in signal_dates:
            execution_date = next_trading_day(days, signal_date)
            if execution_date is None:
                continue
            universe = select_universe_on(enriched, signal_date, universe_mode, cfg.data.universe_top_n)
            eligible = universe["symbol"].astype(str).tolist()
            if len(eligible) < cfg.strategy.top_k:
                continue
            weights = build_target_weights(
                factor_scores=factor_scores,
                as_of_date=signal_date,
                eligible_symbols=eligible,
                top_k=cfg.strategy.top_k,
                weighting=cfg.strategy.weighting,
                max_weight=cfg.strategy.max_weight,
            )
            if weights.empty:
                continue
            weights = self._apply_market_filter(weights, bars, signal_date)
            weights["signal_date"] = signal_date
            weights["date"] = execution_date
            rows.append(weights[["date", "signal_date", "symbol", "target_weight"]])

        if not rows:
            return pd.DataFrame(columns=["date", "signal_date", "symbol", "target_weight"])
        return pd.concat(rows, ignore_index=True).sort_values(["date", "symbol"]).reset_index(drop=True)

    def _effective_config(self) -> AppConfig:
        return apply_strategy_profile(self.config)

    def _apply_market_filter(self, weights: pd.DataFrame, bars: pd.DataFrame, signal_date: pd.Timestamp) -> pd.DataFrame:
        if not self.config.risk.market_filter:
            return weights
        market = self._market_filter_series(bars, signal_date)
        if market.empty:
            LOGGER.warning("Market filter benchmark unavailable; market filter disabled for %s.", signal_date.date())
            return weights
        if len(market) < self.config.risk.market_filter_window:
            return weights
        ma = market.rolling(self.config.risk.market_filter_window).mean()
        if market.iloc[-1] < ma.iloc[-1]:
            filtered = weights.copy()
            filtered["target_weight"] *= self.config.risk.defensive_exposure
            return filtered
        return weights

    def _market_filter_series(self, bars: pd.DataFrame, signal_date: pd.Timestamp) -> pd.Series:
        try:
            if self._benchmark_cache is None:
                self._benchmark_cache = load_benchmarks(self.config, bars)
            key = self.config.risk.market_filter_benchmark.lower()
            benchmark = self._benchmark_cache[self._benchmark_cache["benchmark"].str.lower() == key].copy()
            benchmark = benchmark[benchmark["date"] <= signal_date].sort_values("date")
            return benchmark.set_index("date")["close"].astype(float)
        except Exception as exc:
            LOGGER.warning("Unable to load market filter benchmark: %s", exc)
            return pd.Series(dtype=float)
