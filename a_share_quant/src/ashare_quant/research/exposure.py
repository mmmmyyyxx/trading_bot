"""Portfolio exposure diagnostics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_quant.backtest.result import BacktestResult
from ashare_quant.research.benchmark import BENCHMARKS


EXPOSURE_COLUMNS = [
    "date",
    "portfolio_beta_to_hs300",
    "portfolio_beta_to_csi500",
    "portfolio_beta_to_csi1000",
    "avg_stock_volatility",
    "avg_market_cap",
    "median_market_cap",
    "market_cap_available",
    "industry_weight_top1",
    "industry_weight_top3",
    "cash_weight",
    "top10_weight",
]


def build_exposure_reports(
    result: BacktestResult,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build exposure, top-holding, and industry-exposure reports."""
    positions = result.positions.copy()
    equity = result.equity_curve.copy()
    if positions.empty or equity.empty:
        return {
            "exposure_report": pd.DataFrame(columns=EXPOSURE_COLUMNS),
            "top_holdings": pd.DataFrame(columns=["date", "rank", "symbol", "weight", "industry", "market_cap"]),
            "industry_exposure": pd.DataFrame(columns=["date", "industry", "weight"]),
        }

    positions["date"] = pd.to_datetime(positions["date"])
    equity["date"] = pd.to_datetime(equity["date"])
    exposure = equity[["date", "cash", "net_equity", "daily_return"]].copy()
    exposure["cash_weight"] = exposure["cash"] / exposure["net_equity"].where(exposure["net_equity"] != 0)

    for key in BENCHMARKS:
        exposure[f"portfolio_beta_to_{key}"] = _rolling_beta(exposure, benchmarks, key)

    stock_vol = _stock_volatility(bars)
    pos_with_vol = positions.merge(stock_vol, on=["date", "symbol"], how="left")
    exposure = exposure.merge(_weighted_mean(pos_with_vol, "stock_volatility", "avg_stock_volatility"), on="date", how="left")

    market_cap_available = _market_cap_available(positions)
    if market_cap_available:
        exposure = exposure.merge(_weighted_mean(positions, "market_cap", "avg_market_cap"), on="date", how="left")
        exposure = exposure.merge(_weighted_median_market_cap(positions), on="date", how="left")
    else:
        exposure["avg_market_cap"] = float("nan")
        exposure["median_market_cap"] = float("nan")
    exposure["market_cap_available"] = market_cap_available

    industry_exposure = _industry_exposure(positions)
    exposure = exposure.merge(_industry_concentration(industry_exposure), on="date", how="left")
    exposure = exposure.merge(_top10_weight(positions), on="date", how="left")

    top_holdings = _top_holdings(positions)
    exposure = exposure[EXPOSURE_COLUMNS].fillna(
        {
            "avg_stock_volatility": 0.0,
            "industry_weight_top1": 0.0,
            "industry_weight_top3": 0.0,
            "cash_weight": 0.0,
            "top10_weight": 0.0,
        }
    )
    return {
        "exposure_report": exposure,
        "top_holdings": top_holdings,
        "industry_exposure": industry_exposure,
    }


def write_exposure_reports(
    result: BacktestResult,
    bars: pd.DataFrame,
    benchmarks: pd.DataFrame,
    output_dir: str | Path,
) -> dict[str, pd.DataFrame]:
    """Write exposure diagnostics to reports/."""
    reports = build_exposure_reports(result, bars, benchmarks)
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    reports["exposure_report"].to_csv(path / "exposure_report.csv", index=False)
    reports["top_holdings"].to_csv(path / "top_holdings.csv", index=False)
    reports["industry_exposure"].to_csv(path / "industry_exposure.csv", index=False)
    return reports


def _rolling_beta(equity: pd.DataFrame, benchmarks: pd.DataFrame, key: str, window: int = 60) -> pd.Series:
    if benchmarks.empty:
        return pd.Series(float("nan"), index=equity.index)
    benchmark = benchmarks[benchmarks["benchmark"].str.lower() == key.lower()][["date", "return"]].copy()
    if benchmark.empty:
        return pd.Series(float("nan"), index=equity.index)
    benchmark["date"] = pd.to_datetime(benchmark["date"])
    merged = equity[["date", "daily_return"]].merge(benchmark, on="date", how="left")
    cov = merged["daily_return"].rolling(window, min_periods=20).cov(merged["return"])
    var = merged["return"].rolling(window, min_periods=20).var()
    beta = cov / var.replace(0, pd.NA)
    return beta.astype(float).reindex(equity.index)


def _stock_volatility(bars: pd.DataFrame, window: int = 60) -> pd.DataFrame:
    data = bars[["date", "symbol", "close"]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data = data.sort_values(["symbol", "date"])
    data["return"] = data.groupby("symbol")["close"].pct_change()
    data["stock_volatility"] = data.groupby("symbol")["return"].transform(lambda s: s.rolling(window, min_periods=20).std(ddof=0) * (252**0.5))
    return data[["date", "symbol", "stock_volatility"]]


def _weighted_mean(frame: pd.DataFrame, value_col: str, output_col: str) -> pd.DataFrame:
    if frame.empty or value_col not in frame.columns:
        return pd.DataFrame(columns=["date", output_col])
    data = frame[["date", "weight", value_col]].copy()
    data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
    data["weight"] = pd.to_numeric(data["weight"], errors="coerce").fillna(0.0)
    data = data.dropna(subset=[value_col])
    if data.empty:
        return pd.DataFrame(columns=["date", output_col])
    rows = []
    for date, group in data.groupby("date"):
        denom = group["weight"].abs().sum()
        value = 0.0 if denom == 0 else float((group[value_col] * group["weight"].abs()).sum() / denom)
        rows.append({"date": date, output_col: value})
    return pd.DataFrame(rows)


def _weighted_median_market_cap(positions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, group in positions.dropna(subset=["market_cap"]).groupby("date"):
        rows.append({"date": date, "median_market_cap": float(pd.to_numeric(group["market_cap"], errors="coerce").median())})
    return pd.DataFrame(rows, columns=["date", "median_market_cap"])


def _market_cap_available(positions: pd.DataFrame) -> bool:
    if "market_cap" not in positions.columns:
        return False
    values = pd.to_numeric(positions["market_cap"], errors="coerce").fillna(0.0)
    return bool((values > 0).any())


def _industry_exposure(positions: pd.DataFrame) -> pd.DataFrame:
    if "industry" not in positions.columns:
        return pd.DataFrame(columns=["date", "industry", "weight"])
    data = positions[["date", "industry", "weight"]].copy()
    data["industry"] = data["industry"].fillna("").astype(str).str.strip()
    data = data[data["industry"] != ""]
    if data.empty:
        return pd.DataFrame(columns=["date", "industry", "weight"])
    return data.groupby(["date", "industry"], as_index=False)["weight"].sum()


def _industry_concentration(industry_exposure: pd.DataFrame) -> pd.DataFrame:
    if industry_exposure.empty:
        return pd.DataFrame(columns=["date", "industry_weight_top1", "industry_weight_top3"])
    rows = []
    for date, group in industry_exposure.groupby("date"):
        weights = group["weight"].abs().sort_values(ascending=False)
        rows.append(
            {
                "date": date,
                "industry_weight_top1": float(weights.head(1).sum()),
                "industry_weight_top3": float(weights.head(3).sum()),
            }
        )
    return pd.DataFrame(rows)


def _top10_weight(positions: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for date, group in positions.groupby("date"):
        rows.append({"date": date, "top10_weight": float(group["weight"].abs().sort_values(ascending=False).head(10).sum())})
    return pd.DataFrame(rows, columns=["date", "top10_weight"])


def _top_holdings(positions: pd.DataFrame, limit: int = 10) -> pd.DataFrame:
    rows = []
    columns = ["date", "rank", "symbol", "weight", "industry", "market_cap"]
    for date, group in positions.sort_values(["date", "weight"], ascending=[True, False]).groupby("date"):
        top = group.head(limit).reset_index(drop=True)
        for idx, row in top.iterrows():
            rows.append(
                {
                    "date": date,
                    "rank": idx + 1,
                    "symbol": row.get("symbol", ""),
                    "weight": row.get("weight", 0.0),
                    "industry": row.get("industry", ""),
                    "market_cap": row.get("market_cap", float("nan")),
                }
            )
    return pd.DataFrame(rows, columns=columns)
