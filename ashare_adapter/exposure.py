"""Exposure diagnostics for Qlib portfolio outputs."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ashare_adapter.metadata import normalize_symbol


def monthly_excess_return(equity: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Compute monthly strategy, benchmark, and excess returns."""

    strategy = _normalize_equity(equity)
    bench = benchmarks.copy()
    bench["date"] = pd.to_datetime(bench["date"])
    rows: list[dict[str, object]] = []
    for benchmark, frame in bench.groupby("benchmark"):
        merged = strategy.merge(frame[["date", "return"]], on="date", how="inner", suffixes=("_strategy", "_benchmark"))
        if merged.empty:
            continue
        merged["month"] = merged["date"].dt.to_period("M").astype(str)
        for month, group in merged.groupby("month"):
            strategy_ret = float((1.0 + group["daily_return"].fillna(0.0)).prod() - 1.0)
            benchmark_ret = float((1.0 + group["return"].fillna(0.0)).prod() - 1.0)
            rows.append(
                {
                    "month": month,
                    "benchmark": benchmark,
                    "strategy_return": strategy_ret,
                    "benchmark_return": benchmark_ret,
                    "excess_return": strategy_ret - benchmark_ret,
                    "up_market": bool(benchmark_ret > 0),
                }
            )
    return pd.DataFrame(rows).sort_values(["benchmark", "month"]).reset_index(drop=True)


def top_holdings(positions: pd.DataFrame, top_n: int = 50) -> pd.DataFrame:
    """Summarize most important holdings by average weight and holding days."""

    if positions.empty:
        return pd.DataFrame(columns=["symbol", "avg_weight", "max_weight", "holding_days", "first_date", "last_date"])
    data = positions.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["weight"] = pd.to_numeric(data["weight"], errors="coerce").fillna(0.0)
    summary = (
        data.groupby("symbol")
        .agg(
            avg_weight=("weight", "mean"),
            max_weight=("weight", "max"),
            holding_days=("date", "nunique"),
            first_date=("date", "min"),
            last_date=("date", "max"),
        )
        .sort_values(["avg_weight", "holding_days"], ascending=False)
        .head(top_n)
        .reset_index()
    )
    return summary


def industry_exposure(positions: pd.DataFrame, bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute daily and average industry exposure from position weights."""

    if positions.empty:
        empty = pd.DataFrame(columns=["date", "industry", "weight"])
        return empty, pd.DataFrame(columns=["industry", "avg_weight", "max_weight", "days"])
    pos = positions.copy()
    pos["date"] = pd.to_datetime(pos["date"])
    pos["symbol"] = pos["symbol"].map(normalize_symbol)
    pos["weight"] = pd.to_numeric(pos["weight"], errors="coerce").fillna(0.0)

    meta = bars[["date", "symbol", "industry"]].copy()
    meta["date"] = pd.to_datetime(meta["date"])
    meta["symbol"] = meta["symbol"].map(normalize_symbol)
    meta["industry"] = meta["industry"].fillna("").astype(str).str.strip()
    meta.loc[meta["industry"] == "", "industry"] = "unknown"
    meta = meta.drop_duplicates(["date", "symbol"])

    merged = pos.merge(meta, on=["date", "symbol"], how="left")
    merged["industry"] = merged["industry"].fillna("unknown")
    daily = (
        merged.groupby(["date", "industry"], as_index=False)["weight"]
        .sum()
        .sort_values(["date", "weight"], ascending=[True, False])
    )
    summary = (
        daily.groupby("industry")
        .agg(avg_weight=("weight", "mean"), max_weight=("weight", "max"), days=("date", "nunique"))
        .sort_values("avg_weight", ascending=False)
        .reset_index()
    )
    return daily, summary


def beta_exposure(equity: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Estimate beta/correlation of strategy daily returns versus benchmarks."""

    strategy = _normalize_equity(equity)
    bench = benchmarks.copy()
    bench["date"] = pd.to_datetime(bench["date"])
    rows: list[dict[str, object]] = []
    for benchmark, frame in bench.groupby("benchmark"):
        merged = strategy.merge(frame[["date", "return"]], on="date", how="inner")
        if merged.empty:
            continue
        strategy_ret = pd.to_numeric(merged["daily_return"], errors="coerce").fillna(0.0)
        benchmark_ret = pd.to_numeric(merged["return"], errors="coerce").fillna(0.0)
        variance = benchmark_ret.var(ddof=0)
        beta = float(strategy_ret.cov(benchmark_ret) / variance) if variance else 0.0
        rows.append(
            {
                "benchmark": benchmark,
                "beta": beta,
                "correlation": float(strategy_ret.corr(benchmark_ret)) if benchmark_ret.std(ddof=0) else 0.0,
                "strategy_vol": float(strategy_ret.std(ddof=0) * np.sqrt(252)),
                "benchmark_vol": float(benchmark_ret.std(ddof=0) * np.sqrt(252)),
            }
        )
    return pd.DataFrame(rows)


def universe_benchmark_overlap(
    bars: pd.DataFrame,
    benchmark_symbols: list[str],
    selected_col: str = "selected",
) -> pd.DataFrame:
    """Compute selected-universe overlap with a benchmark constituent list."""

    data = bars.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if selected_col not in data.columns:
        selected_col = "eligible" if "eligible" in data.columns else selected_col
    if selected_col not in data.columns:
        raise ValueError("Bars must contain selected or eligible column.")
    benchmark_set = {normalize_symbol(symbol) for symbol in benchmark_symbols}
    rows = []
    for date, frame in data.groupby("date"):
        selected = set(frame.loc[frame[selected_col].fillna(False).astype(bool), "symbol"])
        if not selected:
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "selected_count": 0,
                    "benchmark_count": len(benchmark_set),
                    "overlap_count": 0,
                    "selected_overlap_ratio": 0.0,
                    "benchmark_coverage_ratio": 0.0,
                }
            )
            continue
        overlap = selected & benchmark_set
        rows.append(
            {
                "date": pd.Timestamp(date),
                "selected_count": len(selected),
                "benchmark_count": len(benchmark_set),
                "overlap_count": len(overlap),
                "selected_overlap_ratio": len(overlap) / len(selected),
                "benchmark_coverage_ratio": len(overlap) / len(benchmark_set) if benchmark_set else 0.0,
            }
        )
    return pd.DataFrame(rows).sort_values("date").reset_index(drop=True)


def write_exposure_diagnostics(
    output_dir: str | Path,
    bars: pd.DataFrame,
    equity: pd.DataFrame,
    positions: pd.DataFrame,
    benchmarks: pd.DataFrame,
    benchmark_symbols: list[str] | None = None,
) -> dict[str, Path]:
    """Write standard exposure diagnostic files."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    paths["monthly_excess_return"] = _write_csv(monthly_excess_return(equity, benchmarks), out / "monthly_excess_return.csv")
    paths["top_holdings"] = _write_csv(top_holdings(positions), out / "top_holdings.csv")
    daily_industry, industry_summary = industry_exposure(positions, bars)
    paths["industry_exposure"] = _write_csv(daily_industry, out / "industry_exposure.csv")
    paths["industry_exposure_summary"] = _write_csv(industry_summary, out / "industry_exposure_summary.csv")
    paths["beta_exposure"] = _write_csv(beta_exposure(equity, benchmarks), out / "beta_exposure.csv")
    if benchmark_symbols:
        paths["universe_benchmark_overlap"] = _write_csv(
            universe_benchmark_overlap(bars, benchmark_symbols),
            out / "universe_benchmark_overlap.csv",
        )
    return paths


def _normalize_equity(equity: pd.DataFrame) -> pd.DataFrame:
    data = equity.copy()
    data["date"] = pd.to_datetime(data["date"])
    if "daily_return" not in data.columns:
        if "return" in data.columns:
            data["daily_return"] = pd.to_numeric(data["return"], errors="coerce").fillna(0.0)
        elif "equity" in data.columns:
            data["daily_return"] = pd.to_numeric(data["equity"], errors="coerce").pct_change().fillna(0.0)
        else:
            raise ValueError("Equity must contain daily_return, return, or equity.")
    return data.sort_values("date").reset_index(drop=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> Path:
    frame.to_csv(path, index=False)
    return path
