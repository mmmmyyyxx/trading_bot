"""Factor IC and Rank IC diagnostics."""

from __future__ import annotations

import pandas as pd

FACTOR_COLUMNS = [
    "momentum",
    "industry_momentum",
    "trend",
    "volatility",
    "liquidity",
    "short_term_reversal",
    "composite_score",
]
LOWER_IS_BETTER = {"volatility"}


def add_forward_returns(bars: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Add future close-to-close returns for each requested horizon."""
    data = bars.sort_values(["symbol", "date"])[["date", "symbol", "close"]].copy()
    grouped = data.groupby("symbol")["close"]
    for horizon in horizons:
        data[f"future_return_{horizon}d"] = grouped.shift(-horizon) / data["close"] - 1.0
    return data.drop(columns=["close"])


def compute_rank_ic(
    bars: pd.DataFrame,
    factor_scores: pd.DataFrame,
    horizons: list[int] | None = None,
    factor_columns: list[str] | None = None,
    min_cross_section: int = 50,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute daily Rank IC and summary statistics for each factor/horizon."""
    horizons = horizons or [1, 5, 20]
    factor_columns = factor_columns or FACTOR_COLUMNS
    forward = add_forward_returns(bars, horizons)
    merged = factor_scores[["date", "symbol", *factor_columns]].merge(forward, on=["date", "symbol"], how="left")

    daily_rows: list[dict[str, object]] = []
    for factor in factor_columns:
        for horizon in horizons:
            ret_col = f"future_return_{horizon}d"
            for date, group in merged.groupby("date"):
                sample = group[[factor, ret_col]].dropna()
                if len(sample) < min_cross_section or sample[factor].nunique() < 2 or sample[ret_col].nunique() < 2:
                    continue
                factor_values = -sample[factor] if factor in LOWER_IS_BETTER else sample[factor]
                rank_ic = factor_values.corr(sample[ret_col], method="spearman")
                if pd.notna(rank_ic):
                    daily_rows.append(
                        {
                            "date": date,
                            "factor": factor,
                            "horizon": horizon,
                            "rank_ic": float(rank_ic),
                            "count": len(sample),
                            "confidence": "normal" if len(sample) >= 100 else "low",
                        }
                    )

    daily = pd.DataFrame(daily_rows)
    if daily.empty:
        return pd.DataFrame(), daily

    summary = (
        daily.groupby(["factor", "horizon"])
        .agg(
            ic_mean=("rank_ic", "mean"),
            ic_std=("rank_ic", "std"),
            positive_ic_ratio=("rank_ic", lambda s: float((s > 0).mean())),
            observations=("rank_ic", "count"),
            avg_count=("count", "mean"),
        )
        .reset_index()
    )
    summary["icir"] = summary["ic_mean"] / summary["ic_std"].replace(0.0, pd.NA)
    return summary.sort_values(["factor", "horizon"]).reset_index(drop=True), daily
