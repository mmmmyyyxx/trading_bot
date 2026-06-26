"""Named strategy profiles for research comparisons."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ashare_quant.config import AppConfig


@dataclass(frozen=True)
class StrategyProfile:
    name: str
    factor_weights: dict[str, float]
    default_weighting: str
    objective: str
    quality_factor_available: bool = False
    value_factor_available: bool = False


STRATEGY_PROFILES: dict[str, StrategyProfile] = {
    "reversal_low_vol": StrategyProfile(
        name="reversal_low_vol",
        factor_weights={
            "short_term_reversal": 0.50,
            "volatility": 0.30,
            "industry_momentum": 0.20,
            "momentum": 0.0,
            "trend": 0.0,
            "liquidity": 0.0,
        },
        default_weighting="equal_weight",
        objective="reversal_defensive_alpha",
    ),
    "defensive_low_vol": StrategyProfile(
        name="defensive_low_vol",
        factor_weights={
            "volatility": 0.70,
            "industry_momentum": 0.30,
            "momentum": 0.0,
            "short_term_reversal": 0.0,
            "trend": 0.0,
            "liquidity": 0.0,
        },
        default_weighting="inverse_vol_weight",
        objective="low_drawdown_low_beta",
    ),
    "offensive_momentum": StrategyProfile(
        name="offensive_momentum",
        factor_weights={
            "industry_momentum": 0.80,
            "momentum": 0.20,
            "short_term_reversal": 0.0,
            "liquidity": 0.0,
            "trend": 0.0,
            "volatility": 0.0,
        },
        default_weighting="equal_weight",
        objective="benchmark_relative_alpha",
    ),
    "balanced_multi_factor": StrategyProfile(
        name="balanced_multi_factor",
        factor_weights={
            "industry_momentum": 0.40,
            "volatility": 0.40,
            "trend": 0.20,
            "momentum": 0.0,
            "short_term_reversal": 0.0,
            "liquidity": 0.0,
        },
        default_weighting="equal_weight",
        objective="balanced_baseline",
    ),
}


def get_strategy_profile(name: str) -> StrategyProfile | None:
    """Return a known strategy profile, or None for custom weights."""
    return STRATEGY_PROFILES.get(name)


def profile_names() -> list[str]:
    """Return the public named strategy profiles."""
    return list(STRATEGY_PROFILES)


def apply_strategy_profile(config: AppConfig) -> AppConfig:
    """Return a copied config with named factor weights applied."""
    cfg = copy.deepcopy(config)
    profile = get_strategy_profile(cfg.strategy.name)
    if profile is not None:
        cfg.factors.weights = profile.factor_weights.copy()
    return cfg
