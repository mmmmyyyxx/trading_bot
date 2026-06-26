"""Active exposure and attribution diagnostics for Qlib portfolio outputs."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_adapter.exposure import beta_exposure, monthly_excess_return
from ashare_adapter.metadata import normalize_symbol


def active_holdings(
    positions: pd.DataFrame,
    benchmark_symbols: list[str],
) -> pd.DataFrame:
    """Compute daily active stock weights versus an equal-weight benchmark set."""

    pos = _normalize_positions(positions)
    benchmark_set = {normalize_symbol(symbol) for symbol in benchmark_symbols}
    rows = []
    for date, frame in pos.groupby("date"):
        weight = frame.groupby("symbol")["weight"].sum()
        symbols = sorted(set(weight.index) | benchmark_set)
        benchmark_weight = 1.0 / len(benchmark_set) if benchmark_set else 0.0
        for symbol in symbols:
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "portfolio_weight": float(weight.get(symbol, 0.0)),
                    "benchmark_weight": benchmark_weight if symbol in benchmark_set else 0.0,
                    "active_weight": float(weight.get(symbol, 0.0)) - (benchmark_weight if symbol in benchmark_set else 0.0),
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "active_weight"], ascending=[True, False]).reset_index(drop=True)


def active_industry_weight(
    positions: pd.DataFrame,
    bars: pd.DataFrame,
    benchmark_symbols: list[str],
) -> pd.DataFrame:
    """Compute daily active industry weights versus equal-weight benchmark industries."""

    pos = _normalize_positions(positions)
    meta = _industry_meta(bars)
    bench = meta[meta["symbol"].isin({normalize_symbol(symbol) for symbol in benchmark_symbols})]
    rows = []
    for date, frame in pos.groupby("date"):
        day_meta = meta[meta["date"] == pd.Timestamp(date)][["symbol", "industry"]]
        pos_industry = frame.merge(day_meta, on="symbol", how="left")
        pos_industry["industry"] = pos_industry["industry"].fillna("unknown")
        portfolio = pos_industry.groupby("industry")["weight"].sum()

        day_bench = bench[bench["date"] == pd.Timestamp(date)].drop_duplicates("symbol")
        if day_bench.empty:
            benchmark = pd.Series(dtype=float)
        else:
            benchmark = day_bench.groupby("industry")["symbol"].count().astype(float)
            benchmark = benchmark / benchmark.sum()
        industries = sorted(set(portfolio.index) | set(benchmark.index))
        for industry in industries:
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "industry": industry,
                    "portfolio_weight": float(portfolio.get(industry, 0.0)),
                    "benchmark_weight": float(benchmark.get(industry, 0.0)),
                    "active_weight": float(portfolio.get(industry, 0.0)) - float(benchmark.get(industry, 0.0)),
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "active_weight"], ascending=[True, False]).reset_index(drop=True)


def up_down_market_performance(equity: pd.DataFrame, benchmarks: pd.DataFrame) -> pd.DataFrame:
    """Summarize monthly excess performance in up and down benchmark months."""

    monthly = monthly_excess_return(equity, benchmarks)
    if monthly.empty:
        return pd.DataFrame(columns=["benchmark", "up_market", "months", "avg_excess_return", "hit_rate", "total_excess_return"])
    return (
        monthly.groupby(["benchmark", "up_market"])
        .agg(
            months=("excess_return", "count"),
            avg_excess_return=("excess_return", "mean"),
            hit_rate=("excess_return", lambda values: float((values > 0).mean())),
            total_excess_return=("excess_return", "sum"),
        )
        .reset_index()
    )


def return_contribution_by_holding(positions: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Approximate holding return contributions using next close-to-close return."""

    pos = _normalize_positions(positions)
    returns = bars[["date", "symbol", "close"]].copy()
    returns["date"] = pd.to_datetime(returns["date"])
    returns["symbol"] = returns["symbol"].map(normalize_symbol)
    returns = returns.sort_values(["symbol", "date"])
    returns["next_return"] = returns.groupby("symbol")["close"].shift(-1) / returns["close"] - 1.0
    merged = pos.merge(returns[["date", "symbol", "next_return"]], on=["date", "symbol"], how="left")
    merged["return_contribution"] = merged["weight"] * pd.to_numeric(merged["next_return"], errors="coerce").fillna(0.0)
    return (
        merged.groupby("symbol")
        .agg(
            total_contribution=("return_contribution", "sum"),
            avg_contribution=("return_contribution", "mean"),
            holding_days=("date", "nunique"),
            avg_weight=("weight", "mean"),
            max_weight=("weight", "max"),
        )
        .sort_values("total_contribution", ascending=False)
        .reset_index()
    )


def write_active_attribution(
    output_dir: str | Path,
    bars: pd.DataFrame,
    equity: pd.DataFrame,
    positions: pd.DataFrame,
    benchmarks: pd.DataFrame,
    benchmark_symbols: list[str],
) -> dict[str, Path]:
    """Write active attribution CSV files."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "active_industry_weight": out / "active_industry_weight.csv",
        "active_holdings": out / "active_holdings.csv",
        "monthly_attribution": out / "monthly_attribution.csv",
        "up_down_market_performance": out / "up_down_market_performance.csv",
        "return_contribution_by_holding": out / "return_contribution_by_holding.csv",
        "style_beta_summary": out / "style_beta_summary.csv",
    }
    active_industry_weight(positions, bars, benchmark_symbols).to_csv(paths["active_industry_weight"], index=False)
    active_holdings(positions, benchmark_symbols).to_csv(paths["active_holdings"], index=False)
    monthly_excess_return(equity, benchmarks).to_csv(paths["monthly_attribution"], index=False)
    up_down_market_performance(equity, benchmarks).to_csv(paths["up_down_market_performance"], index=False)
    return_contribution_by_holding(positions, bars).to_csv(paths["return_contribution_by_holding"], index=False)
    beta_exposure(equity, benchmarks).to_csv(paths["style_beta_summary"], index=False)
    return paths


def _normalize_positions(positions: pd.DataFrame) -> pd.DataFrame:
    data = positions.copy()
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    data["weight"] = pd.to_numeric(data["weight"], errors="coerce").fillna(0.0)
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def _industry_meta(bars: pd.DataFrame) -> pd.DataFrame:
    meta = bars[["date", "symbol", "industry"]].copy()
    meta["date"] = pd.to_datetime(meta["date"])
    meta["symbol"] = meta["symbol"].map(normalize_symbol)
    meta["industry"] = meta["industry"].fillna("").astype(str).str.strip()
    meta.loc[meta["industry"] == "", "industry"] = "unknown"
    return meta.drop_duplicates(["date", "symbol"])
