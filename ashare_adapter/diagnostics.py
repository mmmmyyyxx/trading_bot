"""Lightweight factor and portfolio diagnostics around Qlib outputs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def add_forward_returns(bars: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Add future close-to-close returns for each horizon."""

    data = bars.sort_values(["symbol", "date"])[["date", "symbol", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"])
    grouped = data.groupby("symbol")["close"]
    for horizon in horizons:
        data[f"future_return_{horizon}d"] = grouped.shift(-horizon) / data["close"] - 1.0
    return data.drop(columns=["close"])


def compute_ic(
    bars: pd.DataFrame,
    scores: pd.DataFrame,
    score_col: str = "score",
    horizons: list[int] | None = None,
    min_cross_section: int = 30,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute daily Pearson IC and Spearman Rank IC."""

    horizons = horizons or [1, 5, 20]
    merged = _merge_scores_and_forward_returns(bars, scores, score_col, horizons)
    rows: list[dict[str, object]] = []
    for horizon in horizons:
        ret_col = f"future_return_{horizon}d"
        for date, group in merged.groupby("date"):
            sample = group[[score_col, ret_col]].dropna()
            if len(sample) < min_cross_section or sample[score_col].nunique() < 2 or sample[ret_col].nunique() < 2:
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "horizon": horizon,
                    "ic": float(sample[score_col].corr(sample[ret_col], method="pearson")),
                    "rank_ic": float(sample[score_col].corr(sample[ret_col], method="spearman")),
                    "count": int(len(sample)),
                }
            )
    daily = pd.DataFrame(rows)
    if daily.empty:
        return pd.DataFrame(), daily
    summary = (
        daily.groupby("horizon")
        .agg(
            ic_mean=("ic", "mean"),
            ic_std=("ic", "std"),
            rank_ic_mean=("rank_ic", "mean"),
            rank_ic_std=("rank_ic", "std"),
            positive_rank_ic_ratio=("rank_ic", lambda values: float((values > 0).mean())),
            observations=("rank_ic", "count"),
            avg_count=("count", "mean"),
        )
        .reset_index()
    )
    summary["rank_icir"] = summary["rank_ic_mean"] / summary["rank_ic_std"].replace(0.0, np.nan)
    summary["icir"] = summary["ic_mean"] / summary["ic_std"].replace(0.0, np.nan)
    return summary, daily


def compute_group_returns(
    bars: pd.DataFrame,
    scores: pd.DataFrame,
    score_col: str = "score",
    n_groups: int = 5,
    horizon: int = 1,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute equal-weight forward returns by score quantile group."""

    merged = _merge_scores_and_forward_returns(bars, scores, score_col, [horizon])
    ret_col = f"future_return_{horizon}d"
    rows: list[dict[str, object]] = []
    for date, group in merged.groupby("date"):
        sample = group[["symbol", score_col, ret_col]].dropna().copy()
        if len(sample) < n_groups or sample[score_col].nunique() < n_groups:
            continue
        try:
            sample["group"] = pd.qcut(sample[score_col], q=n_groups, labels=False, duplicates="drop") + 1
        except ValueError:
            continue
        for group_id, group_frame in sample.groupby("group"):
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "group": int(group_id),
                    "daily_return": float(group_frame[ret_col].mean()),
                    "count": int(len(group_frame)),
                }
            )
    group_returns = pd.DataFrame(rows)
    if group_returns.empty:
        return pd.DataFrame(), group_returns
    group_returns = group_returns.sort_values(["group", "date"]).reset_index(drop=True)
    group_returns["equity"] = group_returns.groupby("group")["daily_return"].transform(lambda values: (1.0 + values).cumprod())
    summary = (
        group_returns.groupby("group")
        .agg(
            total_return=("daily_return", lambda values: float((1.0 + values).prod() - 1.0)),
            annual_return=("daily_return", _annualized_return),
            observations=("daily_return", "count"),
            avg_group_size=("count", "mean"),
        )
        .reset_index()
    )
    return summary, group_returns


def benchmark_comparison(equity: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Compare strategy daily returns with each benchmark."""

    if equity.empty or benchmarks.empty:
        return pd.DataFrame()
    strategy = _normalize_equity(equity)
    bench = benchmarks.copy()
    bench["date"] = pd.to_datetime(bench["date"])
    rows = []
    for key, frame in bench.groupby("benchmark"):
        merged = strategy.merge(frame[["date", "return", "equity"]], on="date", how="inner", suffixes=("_strategy", "_benchmark"))
        if merged.empty:
            continue
        strategy_return = merged["daily_return"].astype(float)
        benchmark_return = merged["return"].astype(float)
        excess = strategy_return - benchmark_return
        rows.append(
            {
                "benchmark": key,
                "strategy_return": float(merged["equity_strategy"].iloc[-1] / merged["equity_strategy"].iloc[0] - 1.0),
                "benchmark_return": float(merged["equity_benchmark"].iloc[-1] / merged["equity_benchmark"].iloc[0] - 1.0),
                "excess_return": float((1.0 + excess).prod() - 1.0),
                "tracking_error": float(excess.std(ddof=0) * np.sqrt(252)),
                "information_ratio": _safe_ratio(excess.mean() * 252, excess.std(ddof=0) * np.sqrt(252)),
                "beta": _beta(strategy_return, benchmark_return),
                "max_drawdown": max_drawdown(merged["equity_strategy"]),
                "relative_drawdown": max_drawdown(merged["equity_strategy"] / merged["equity_benchmark"]),
            }
        )
    return pd.DataFrame(rows)


def compute_turnover(positions: pd.DataFrame) -> pd.DataFrame:
    """Compute one-way turnover from date/symbol/weight positions."""

    if positions.empty:
        return pd.DataFrame(columns=["date", "turnover"])
    data = positions.copy()
    data["date"] = pd.to_datetime(data["date"])
    pivot = data.pivot_table(index="date", columns="symbol", values="weight", aggfunc="sum").fillna(0.0)
    turnover = pivot.diff().abs().sum(axis=1) / 2.0
    turnover.iloc[0] = pivot.iloc[0].abs().sum()
    return turnover.rename("turnover").reset_index()


def total_cost(trades: pd.DataFrame) -> float:
    """Return total cost from a Qlib/local trade table when cost columns exist."""

    if trades.empty:
        return 0.0
    candidates = ["cost", "total_cost", "commission", "stamp_tax", "transfer_fee", "slippage"]
    present = [column for column in candidates if column in trades.columns]
    if not present:
        return 0.0
    if "total_cost" in trades.columns:
        return float(pd.to_numeric(trades["total_cost"], errors="coerce").fillna(0.0).sum())
    return float(pd.to_numeric(trades[present].stack(), errors="coerce").fillna(0.0).sum())


def max_drawdown(equity: pd.Series) -> float:
    """Compute max drawdown from an equity curve."""

    values = pd.to_numeric(equity, errors="coerce").dropna()
    if values.empty:
        return 0.0
    running_max = values.cummax()
    drawdown = values / running_max - 1.0
    return float(drawdown.min())


def split_oos(equity: pd.DataFrame, oos_start_date: str | None) -> pd.DataFrame:
    """Summarize in-sample and out-of-sample equity performance."""

    data = _normalize_equity(equity)
    if data.empty:
        return pd.DataFrame()
    if oos_start_date is None:
        return pd.DataFrame([_performance_row(data, "all")])
    cutoff = pd.Timestamp(oos_start_date)
    rows = []
    insample = data[data["date"] < cutoff]
    oos = data[data["date"] >= cutoff]
    if not insample.empty:
        rows.append(_performance_row(insample, "in_sample"))
    if not oos.empty:
        rows.append(_performance_row(oos, "out_of_sample"))
    return pd.DataFrame(rows)


def write_diagnostics(
    output_dir: str | Path,
    bars: pd.DataFrame,
    scores: pd.DataFrame,
    benchmarks: pd.DataFrame | None = None,
    equity: pd.DataFrame | None = None,
    positions: pd.DataFrame | None = None,
    trades: pd.DataFrame | None = None,
    score_col: str = "score",
    horizons: list[int] | None = None,
    n_groups: int = 5,
    oos_start_date: str | None = None,
) -> dict[str, Path]:
    """Write the standard diagnostics CSV files."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    ic_summary, ic_daily = compute_ic(bars, scores, score_col=score_col, horizons=horizons)
    paths["ic_summary"] = _write_csv(ic_summary, out / "factor_ic_summary.csv")
    paths["ic_daily"] = _write_csv(ic_daily, out / "factor_ic_daily.csv")

    group_summary, group_returns = compute_group_returns(bars, scores, score_col=score_col, n_groups=n_groups)
    paths["group_summary"] = _write_csv(group_summary, out / "factor_group_summary.csv")
    paths["group_returns"] = _write_csv(group_returns, out / "factor_group_returns.csv")

    if equity is not None and benchmarks is not None:
        paths["benchmark_comparison"] = _write_csv(benchmark_comparison(equity, benchmarks), out / "benchmark_comparison.csv")
    if positions is not None:
        paths["turnover"] = _write_csv(compute_turnover(positions), out / "turnover.csv")
    if equity is not None:
        paths["oos"] = _write_csv(split_oos(equity, oos_start_date), out / "oos_summary.csv")
    if trades is not None:
        paths["cost"] = _write_csv(pd.DataFrame([{"total_cost": total_cost(trades)}]), out / "cost_summary.csv")
    return paths


def _merge_scores_and_forward_returns(
    bars: pd.DataFrame,
    scores: pd.DataFrame,
    score_col: str,
    horizons: list[int],
) -> pd.DataFrame:
    forward = add_forward_returns(bars, horizons)
    score_frame = scores.copy()
    score_frame["date"] = pd.to_datetime(score_frame["date"])
    if score_col not in score_frame.columns:
        raise ValueError(f"Score column not found: {score_col}")
    return score_frame[["date", "symbol", score_col]].merge(forward, on=["date", "symbol"], how="left")


def _normalize_equity(equity: pd.DataFrame) -> pd.DataFrame:
    data = equity.copy()
    data["date"] = pd.to_datetime(data["date"])
    if "equity" not in data.columns:
        if "account_value" in data.columns:
            data["equity"] = data["account_value"] / data["account_value"].iloc[0]
        elif "return" in data.columns:
            data["equity"] = (1.0 + data["return"].fillna(0.0)).cumprod()
        else:
            raise ValueError("Equity data must contain equity, account_value, or return.")
    if "daily_return" not in data.columns:
        data["daily_return"] = data["equity"].pct_change().fillna(0.0)
    return data.sort_values("date").reset_index(drop=True)


def _performance_row(frame: pd.DataFrame, segment: str) -> dict[str, object]:
    days = max(len(frame), 1)
    total_return = float(frame["equity"].iloc[-1] / frame["equity"].iloc[0] - 1.0)
    daily_return = frame["daily_return"].astype(float)
    return {
        "segment": segment,
        "start_date": frame["date"].iloc[0],
        "end_date": frame["date"].iloc[-1],
        "total_return": total_return,
        "annual_return": (1.0 + total_return) ** (252 / days) - 1.0,
        "annual_volatility": float(daily_return.std(ddof=0) * np.sqrt(252)),
        "max_drawdown": max_drawdown(frame["equity"]),
    }


def _annualized_return(values: pd.Series) -> float:
    total = float((1.0 + values).prod() - 1.0)
    return (1.0 + total) ** (252 / max(len(values), 1)) - 1.0


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0 or pd.isna(denominator):
        return 0.0
    return float(numerator / denominator)


def _beta(strategy_return: pd.Series, benchmark_return: pd.Series) -> float:
    variance = benchmark_return.var(ddof=0)
    if variance == 0 or pd.isna(variance):
        return 0.0
    return float(strategy_return.cov(benchmark_return) / variance)


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False)
    return path
