"""Single-factor top-K backtest comparisons."""

from __future__ import annotations

import copy

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy

SINGLE_FACTORS = ["momentum", "trend", "volatility", "liquidity"]


def run_single_factor_backtests(config: AppConfig, bars: pd.DataFrame) -> pd.DataFrame:
    """Run one top-K backtest per factor while keeping other settings fixed."""
    rows: list[dict[str, object]] = []
    for factor in SINGLE_FACTORS:
        cfg = copy.deepcopy(config)
        cfg.factors.weights = {name: 0.0 for name in SINGLE_FACTORS}
        cfg.factors.weights[factor] = 1.0
        targets = MultiFactorRotationStrategy(cfg).generate_targets(bars)
        result = BacktestEngine(cfg).run(bars, targets)
        row: dict[str, object] = {"factor": factor, "target_rows": len(targets)}
        row.update(result.metrics)
        rows.append(row)
    return pd.DataFrame(rows).sort_values("factor").reset_index(drop=True)

