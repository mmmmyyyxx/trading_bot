from __future__ import annotations

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.factors.composite import compute_composite_factors
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy
from tests.real_data import load_real_cached_bars


def test_factors_do_not_change_when_future_prices_are_edited() -> None:
    config = AppConfig()
    bars = load_real_cached_bars()
    cutoff = sorted(bars["date"].unique())[220]

    baseline = compute_composite_factors(bars, config.factors)
    edited = bars.copy()
    future_mask = edited["date"] > cutoff
    edited.loc[future_mask, ["open", "high", "low", "close", "amount"]] *= 5.0
    changed = compute_composite_factors(edited, config.factors)

    columns = ["date", "symbol", "momentum", "trend", "volatility", "liquidity", "composite_score"]
    left = baseline.loc[baseline["date"] <= cutoff, columns].reset_index(drop=True)
    right = changed.loc[changed["date"] <= cutoff, columns].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_strategy_trades_after_signal_date() -> None:
    config = AppConfig()
    config.strategy.top_k = 3
    config.strategy.max_weight = 0.3
    bars = load_real_cached_bars()

    targets = MultiFactorRotationStrategy(config).generate_targets(bars)

    assert not targets.empty
    assert (targets["date"] > targets["signal_date"]).all()
