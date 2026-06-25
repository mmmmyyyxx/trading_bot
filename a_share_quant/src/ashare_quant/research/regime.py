"""Market-regime performance diagnostics."""

from __future__ import annotations

import numpy as np
import pandas as pd


REGIME_COLUMNS = [
    "benchmark",
    "benchmark_name",
    "regime",
    "sample_days",
    "strategy_return",
    "benchmark_return",
    "excess_return",
    "annual_return",
    "benchmark_annual_return",
    "sharpe",
    "information_ratio",
    "max_drawdown",
    "win_rate",
    "benchmark_ma_window",
    "benchmark_vol_window",
]


def compute_regime_performance(
    equity_curve: pd.DataFrame,
    benchmarks: pd.DataFrame,
    ma_window: int = 120,
    vol_window: int = 20,
) -> pd.DataFrame:
    """Compare strategy performance across benchmark-defined market regimes."""
    if equity_curve.empty or benchmarks.empty:
        return pd.DataFrame(columns=REGIME_COLUMNS)

    equity = equity_curve[["date", "daily_return"]].copy()
    equity["date"] = pd.to_datetime(equity["date"])
    equity["daily_return"] = pd.to_numeric(equity["daily_return"], errors="coerce").fillna(0.0)

    rows: list[dict[str, object]] = []
    for benchmark, bench in benchmarks.groupby("benchmark"):
        aligned = _aligned_frame(equity, bench, ma_window, vol_window)
        if aligned.empty:
            continue
        benchmark_name = str(aligned["benchmark_name"].iloc[0])
        masks = _regime_masks(aligned)
        for regime, mask in masks.items():
            row = _regime_metrics(aligned.loc[mask], regime)
            row.update(
                {
                    "benchmark": benchmark,
                    "benchmark_name": benchmark_name,
                    "benchmark_ma_window": ma_window,
                    "benchmark_vol_window": vol_window,
                }
            )
            rows.append(row)

    if not rows:
        return pd.DataFrame(columns=REGIME_COLUMNS)
    return pd.DataFrame(rows)[REGIME_COLUMNS]


def _aligned_frame(equity: pd.DataFrame, benchmark: pd.DataFrame, ma_window: int, vol_window: int) -> pd.DataFrame:
    bench = benchmark[["date", "benchmark_name", "close", "return"]].copy()
    bench["date"] = pd.to_datetime(bench["date"])
    bench["close"] = pd.to_numeric(bench["close"], errors="coerce")
    bench["return"] = pd.to_numeric(bench["return"], errors="coerce").fillna(0.0)
    bench = bench.sort_values("date")
    bench["ma"] = bench["close"].rolling(ma_window, min_periods=ma_window).mean()
    bench["rolling_vol"] = bench["return"].rolling(vol_window, min_periods=max(5, vol_window // 2)).std(ddof=0) * np.sqrt(252)
    bench["month"] = bench["date"].dt.to_period("M")
    monthly_return = bench.groupby("month")["return"].apply(lambda values: (1.0 + values).prod() - 1.0)
    bench["monthly_benchmark_return"] = bench["month"].map(monthly_return)
    return equity.merge(bench, on="date", how="inner").sort_values("date").reset_index(drop=True)


def _regime_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    valid_ma = frame["ma"].notna()
    valid_vol = frame["rolling_vol"].notna()
    vol_median = frame.loc[valid_vol, "rolling_vol"].median()
    if pd.isna(vol_median):
        vol_median = float("inf")
    return {
        "benchmark_above_ma120": valid_ma & (frame["close"] > frame["ma"]),
        "benchmark_below_ma120": valid_ma & (frame["close"] <= frame["ma"]),
        "high_vol_market": valid_vol & (frame["rolling_vol"] >= vol_median),
        "low_vol_market": valid_vol & (frame["rolling_vol"] < vol_median),
        "up_month": frame["monthly_benchmark_return"] > 0,
        "down_month": frame["monthly_benchmark_return"] <= 0,
    }


def _regime_metrics(frame: pd.DataFrame, regime: str) -> dict[str, object]:
    if frame.empty:
        return {
            "regime": regime,
            "sample_days": 0,
            "strategy_return": np.nan,
            "benchmark_return": np.nan,
            "excess_return": np.nan,
            "annual_return": np.nan,
            "benchmark_annual_return": np.nan,
            "sharpe": np.nan,
            "information_ratio": np.nan,
            "max_drawdown": np.nan,
            "win_rate": np.nan,
        }

    strategy_return = frame["daily_return"].astype(float)
    benchmark_return = frame["return"].astype(float)
    strategy_total = float((1.0 + strategy_return).prod() - 1.0)
    benchmark_total = float((1.0 + benchmark_return).prod() - 1.0)
    days = len(frame)
    strategy_curve = (1.0 + strategy_return).cumprod()
    excess = strategy_return - benchmark_return
    return {
        "regime": regime,
        "sample_days": days,
        "strategy_return": strategy_total,
        "benchmark_return": benchmark_total,
        "excess_return": strategy_total - benchmark_total,
        "annual_return": _annualize(strategy_total, days),
        "benchmark_annual_return": _annualize(benchmark_total, days),
        "sharpe": _annualized_ratio(strategy_return),
        "information_ratio": _annualized_ratio(excess),
        "max_drawdown": float((strategy_curve / strategy_curve.cummax() - 1.0).min()),
        "win_rate": float((strategy_return > 0).mean()),
    }


def _annualized_ratio(returns: pd.Series) -> float:
    std = returns.std(ddof=0)
    if std == 0 or pd.isna(std):
        return 0.0
    return float(returns.mean() / std * np.sqrt(252))


def _annualize(total_return: float, days: int) -> float:
    if days <= 0 or total_return <= -1.0:
        return np.nan
    return float((1.0 + total_return) ** (252 / days) - 1.0)
