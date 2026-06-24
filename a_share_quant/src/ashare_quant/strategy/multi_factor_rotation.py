"""Daily A-share multi-factor rotation strategy."""

from __future__ import annotations

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.data.calendar import next_trading_day, rebalance_signal_dates, trading_days_from_bars
from ashare_quant.data.universe import add_universe_flags, eligible_symbols_on
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.portfolio.weighting import build_target_weights
from ashare_quant.strategy.base import Strategy


class MultiFactorRotationStrategy(Strategy):
    """Monthly top-K rotation using backward-looking A-share factors."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def generate_targets(self, bars: pd.DataFrame) -> pd.DataFrame:
        """Generate target weights for execution on the next trading day."""
        cfg = self.config
        days = trading_days_from_bars(bars)
        enriched = add_universe_flags(
            bars,
            min_listed_days=cfg.data.min_listed_days,
            min_amount=cfg.data.min_amount,
            liquidity_window=cfg.data.liquidity_window,
            liquidity_top_pct=cfg.data.liquidity_top_pct,
            exclude_st=cfg.data.exclude_st,
            exclude_paused=cfg.data.exclude_paused,
            exclude_limit_buy=cfg.data.exclude_limit_buy,
        )
        factor_scores = compute_composite_factors(bars, cfg.factors)

        rows: list[pd.DataFrame] = []
        for signal_date in rebalance_signal_dates(days, cfg.strategy.rebalance_frequency):
            execution_date = next_trading_day(days, signal_date)
            if execution_date is None:
                continue
            eligible = eligible_symbols_on(enriched, signal_date)
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

    def _apply_market_filter(self, weights: pd.DataFrame, bars: pd.DataFrame, signal_date: pd.Timestamp) -> pd.DataFrame:
        if not self.config.risk.market_filter:
            return weights
        proxy = bars[bars["date"] <= signal_date].copy()
        market = proxy.groupby("date")["close"].mean().sort_index()
        if len(market) < self.config.risk.market_filter_window:
            return weights
        ma = market.rolling(self.config.risk.market_filter_window).mean()
        if market.iloc[-1] < ma.iloc[-1]:
            filtered = weights.copy()
            filtered["target_weight"] *= self.config.risk.defensive_exposure
            return filtered
        return weights
