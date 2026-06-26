"""Composite multi-factor scoring."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_quant.config import FactorConfig
from ashare_quant.factors.base import cross_sectional_zscore, standardize_by_date
from ashare_quant.factors.momentum import momentum_factor


FACTOR_COLUMNS = ["momentum", "industry_momentum", "trend", "volatility", "liquidity", "short_term_reversal"]


def industry_neutral_momentum_factor(bars: pd.DataFrame, config: FactorConfig) -> pd.DataFrame:
    """Compute industry-neutral momentum, falling back to plain momentum when industry is unavailable."""
    momentum = momentum_factor(bars, config.momentum_window, config.momentum_skip)
    if "industry" not in bars.columns:
        momentum["industry_momentum"] = momentum["momentum"]
        momentum["industry_momentum_fallback"] = True
        return momentum[["date", "symbol", "industry_momentum", "industry_momentum_fallback"]]

    industries = bars[["date", "symbol", "industry"]].drop_duplicates()
    data = momentum.merge(industries, on=["date", "symbol"], how="left")
    valid_industry = data["industry"].notna() & (data["industry"].astype(str) != "")
    masked = data[["date", "industry", "momentum"]].copy()
    masked.loc[~valid_industry, ["industry", "momentum"]] = np.nan
    data["industry_momentum"] = masked.groupby(["date", "industry"], sort=False)["momentum"].transform(cross_sectional_zscore)
    missing = data["industry_momentum"].isna()
    data.loc[missing, "industry_momentum"] = data.loc[missing, "momentum"]
    data["industry_momentum_fallback"] = missing
    return data[["date", "symbol", "industry_momentum", "industry_momentum_fallback"]]


def compute_raw_factors(bars: pd.DataFrame, config: FactorConfig) -> pd.DataFrame:
    """Compute raw rolling factors using only past and current signal-date data."""
    data = bars.sort_values(["symbol", "date"]).copy()
    grouped_close = data.groupby("symbol", sort=False)["close"]
    features = data[["date", "symbol"]].copy()

    features["momentum"] = grouped_close.shift(config.momentum_skip) / grouped_close.shift(config.momentum_skip + config.momentum_window) - 1.0
    moving_average = grouped_close.transform(
        lambda s: s.rolling(config.trend_window, min_periods=config.trend_window).mean()
    )
    features["trend"] = data["close"] / moving_average - 1.0
    returns = grouped_close.pct_change()
    features["volatility"] = returns.groupby(data["symbol"], sort=False).transform(
        lambda s: s.rolling(config.volatility_window, min_periods=config.volatility_window).std()
    )
    features["liquidity"] = data.groupby("symbol", sort=False)["amount"].transform(
        lambda s: s.rolling(config.liquidity_window, min_periods=config.liquidity_window).mean()
    )
    features["short_term_reversal"] = -(data["close"] / grouped_close.shift(config.reversal_window) - 1.0)

    if "industry" not in data.columns:
        features["industry_momentum"] = features["momentum"]
        features["industry_momentum_fallback"] = True
        return features

    industry = data["industry"]
    valid_industry = industry.notna() & (industry.astype(str) != "")
    industry_data = features[["date", "momentum"]].copy()
    industry_data["industry"] = industry
    industry_data.loc[~valid_industry, ["momentum", "industry"]] = np.nan
    industry_data["industry_momentum"] = (
        industry_data.groupby(["date", "industry"], sort=False)["momentum"].transform(cross_sectional_zscore)
    )
    missing = industry_data["industry_momentum"].isna()
    features["industry_momentum"] = industry_data["industry_momentum"].where(~missing, features["momentum"])
    features["industry_momentum_fallback"] = missing
    return features


def compute_composite_factors(bars: pd.DataFrame, config: FactorConfig) -> pd.DataFrame:
    """Compute standardized factor scores and weighted composite scores."""
    raw = compute_raw_factors(bars, config).sort_values(["date", "symbol"])
    scored = standardize_by_date(raw, FACTOR_COLUMNS, lower_is_better={"volatility"})
    return recompute_composite_score(scored, config.weights).reset_index(drop=True)


def recompute_composite_score(scored_factors: pd.DataFrame, weights: dict[str, float]) -> pd.DataFrame:
    """Rebuild composite_score from already-computed factor score columns."""
    scored = scored_factors.copy()
    weighted_factors = [factor for factor, weight in weights.items() if weight and factor in FACTOR_COLUMNS]
    valid_columns = weighted_factors or FACTOR_COLUMNS
    valid = scored[valid_columns].notna().all(axis=1)
    composite = np.zeros(len(scored), dtype=float)
    for factor, weight in weights.items():
        score_col = f"{factor}_score"
        if score_col in scored.columns:
            composite += float(weight) * scored[score_col].fillna(0.0).to_numpy()
    scored["composite_score"] = np.where(valid, composite, np.nan)
    return scored
