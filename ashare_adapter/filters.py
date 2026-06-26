"""Backward-looking A-share filter columns."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_adapter.config import UniverseConfig


def add_filter_columns(bars: pd.DataFrame, config: UniverseConfig) -> pd.DataFrame:
    """Add listed-days, rolling amount, and eligibility flags without lookahead."""

    data = bars.sort_values(["symbol", "date"]).copy()
    data["date"] = pd.to_datetime(data["date"])
    grouped = data.groupby("symbol", group_keys=False)

    if "list_date" in data.columns:
        list_date = pd.to_datetime(data["list_date"], errors="coerce")
        data["listed_days"] = (data["date"] - list_date).dt.days
        fallback = data["listed_days"].isna()
        data.loc[fallback, "listed_days"] = grouped.cumcount()[fallback] + 1
        data["listed_days_fallback"] = fallback
    else:
        data["listed_days"] = grouped.cumcount() + 1
        data["listed_days_fallback"] = True

    data["avg_amount"] = grouped["amount"].transform(
        lambda series: series.rolling(config.liquidity_window, min_periods=1).mean()
    )

    eligible = (data["listed_days"] >= config.min_listed_days) & (data["avg_amount"] >= config.min_amount)
    if config.exclude_st and "is_st" in data.columns:
        eligible &= ~data["is_st"].fillna(False).astype(bool)
    if config.exclude_paused and "is_paused" in data.columns:
        eligible &= ~data["is_paused"].fillna(False).astype(bool)
    if config.exclude_limit_buy and {"open", "limit_up"}.issubset(data.columns):
        eligible &= pd.to_numeric(data["open"], errors="coerce") < pd.to_numeric(data["limit_up"], errors="coerce")

    data["eligible"] = eligible.fillna(False)
    if config.dynamic_liquidity_top_n:
        data["liquidity_rank"] = data.groupby("date")["avg_amount"].rank(method="first", ascending=False)
        data["selected"] = data["eligible"] & (data["liquidity_rank"] <= int(config.dynamic_liquidity_top_n))
    else:
        data["liquidity_rank"] = np.nan
        data["selected"] = data["eligible"]
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def filter_snapshot(enriched_bars: pd.DataFrame, date: object, selected_only: bool = True) -> pd.DataFrame:
    """Return eligible or selected symbols on a single date."""

    target = pd.Timestamp(date)
    snapshot = enriched_bars[pd.to_datetime(enriched_bars["date"]) == target].copy()
    if snapshot.empty:
        return snapshot
    column = "selected" if selected_only and "selected" in snapshot.columns else "eligible"
    if column not in snapshot.columns:
        return snapshot.iloc[0:0]
    return snapshot[snapshot[column].fillna(False).astype(bool)].sort_values(["avg_amount", "symbol"], ascending=[False, True])
