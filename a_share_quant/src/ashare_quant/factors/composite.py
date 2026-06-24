"""Composite multi-factor scoring."""

from __future__ import annotations

from functools import reduce

import numpy as np
import pandas as pd

from ashare_quant.config import FactorConfig
from ashare_quant.factors.base import cross_sectional_zscore, standardize_by_date
from ashare_quant.factors.liquidity import liquidity_factor
from ashare_quant.factors.momentum import momentum_factor
from ashare_quant.factors.trend import trend_factor
from ashare_quant.factors.volatility import volatility_factor


FACTOR_COLUMNS = ["momentum", "industry_momentum", "trend", "volatility", "liquidity"]


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
    data["industry_momentum"] = data.where(valid_industry).groupby(["date", "industry"])["momentum"].transform(cross_sectional_zscore)
    missing = data["industry_momentum"].isna()
    data.loc[missing, "industry_momentum"] = data.loc[missing, "momentum"]
    data["industry_momentum_fallback"] = missing
    return data[["date", "symbol", "industry_momentum", "industry_momentum_fallback"]]


def compute_raw_factors(bars: pd.DataFrame, config: FactorConfig) -> pd.DataFrame:
    """Compute raw rolling factors using only past and current signal-date data."""
    frames = [
        momentum_factor(bars, config.momentum_window, config.momentum_skip),
        trend_factor(bars, config.trend_window),
        volatility_factor(bars, config.volatility_window),
        liquidity_factor(bars, config.liquidity_window),
        industry_neutral_momentum_factor(bars, config),
    ]
    return reduce(lambda left, right: left.merge(right, on=["date", "symbol"], how="outer"), frames)


def compute_composite_factors(bars: pd.DataFrame, config: FactorConfig) -> pd.DataFrame:
    """Compute standardized factor scores and weighted composite scores."""
    raw = compute_raw_factors(bars, config).sort_values(["date", "symbol"])
    scored = standardize_by_date(raw, FACTOR_COLUMNS, lower_is_better={"volatility"})
    weighted_factors = [factor for factor, weight in config.weights.items() if weight and factor in FACTOR_COLUMNS]
    valid_columns = weighted_factors or FACTOR_COLUMNS
    valid = scored[valid_columns].notna().all(axis=1)
    composite = np.zeros(len(scored), dtype=float)
    for factor, weight in config.weights.items():
        score_col = f"{factor}_score"
        if score_col in scored.columns:
            composite += float(weight) * scored[score_col].fillna(0.0).to_numpy()
    scored["composite_score"] = np.where(valid, composite, np.nan)
    return scored.reset_index(drop=True)
