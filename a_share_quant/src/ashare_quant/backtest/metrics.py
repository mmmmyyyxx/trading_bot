"""Performance metrics for daily equity curves."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


def max_drawdown(equity: pd.Series) -> float:
    """Return maximum drawdown as a negative number."""
    running_max = equity.cummax()
    drawdown = equity / running_max - 1.0
    return float(drawdown.min())


def compute_metrics(
    equity_curve: pd.DataFrame,
    trades: pd.DataFrame,
    initial_cash: float,
    periods_per_year: int = 252,
    benchmark_curve: pd.Series | None = None,
) -> dict[str, float]:
    """Compute net/gross return, risk, cost, turnover, and drawdown metrics."""
    if equity_curve.empty:
        raise ValueError("equity_curve is empty.")

    net_equity = equity_curve["net_equity"].astype(float)
    gross_equity = equity_curve["gross_equity"].astype(float)
    daily_return = equity_curve["daily_return"].astype(float).fillna(0.0)
    days = max(len(equity_curve), 1)

    total_return = float(net_equity.iloc[-1] / initial_cash - 1.0)
    gross_total_return = float(gross_equity.iloc[-1] / initial_cash - 1.0)
    annual_return = float((1.0 + total_return) ** (periods_per_year / days) - 1.0)
    annual_volatility = float(daily_return.std(ddof=0) * math.sqrt(periods_per_year))
    sharpe = 0.0
    if annual_volatility > 0:
        sharpe = float(daily_return.mean() / daily_return.std(ddof=0) * math.sqrt(periods_per_year))
    mdd = max_drawdown(net_equity)
    calmar = float(annual_return / abs(mdd)) if mdd < 0 else 0.0
    win_base = daily_return.iloc[1:] if len(daily_return) > 1 else daily_return
    win_rate = float((win_base > 0).sum() / len(win_base)) if len(win_base) else 0.0

    total_cost = float(trades["total_cost"].sum()) if not trades.empty and "total_cost" in trades else 0.0
    total_turnover = float(equity_curve["turnover"].sum()) if "turnover" in equity_curve else 0.0
    average_turnover = float(equity_curve["turnover"].mean()) if "turnover" in equity_curve else 0.0

    benchmark_return = 0.0
    if benchmark_curve is not None and len(benchmark_curve) > 1:
        benchmark_return = float(benchmark_curve.iloc[-1] / benchmark_curve.iloc[0] - 1.0)

    return {
        "total_return": total_return,
        "gross_total_return": gross_total_return,
        "annual_return": annual_return,
        "annual_volatility": annual_volatility,
        "sharpe": sharpe,
        "max_drawdown": mdd,
        "calmar": calmar,
        "win_rate": win_rate,
        "turnover": total_turnover,
        "average_turnover": average_turnover,
        "total_cost": total_cost,
        "benchmark_return": benchmark_return,
    }

