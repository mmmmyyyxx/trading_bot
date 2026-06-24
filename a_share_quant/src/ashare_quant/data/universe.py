"""A-share universe filtering rules."""

from __future__ import annotations

import pandas as pd


def add_universe_flags(
    bars: pd.DataFrame,
    min_listed_days: int,
    min_amount: float,
    liquidity_window: int,
    liquidity_top_pct: float | None = None,
    exclude_st: bool = True,
    exclude_paused: bool = True,
    exclude_limit_buy: bool = False,
) -> pd.DataFrame:
    """Add listing-age, liquidity, and eligibility columns without future data."""
    data = bars.sort_values(["symbol", "date"]).copy()
    grouped = data.groupby("symbol", group_keys=False)
    data["listed_days"] = grouped.cumcount() + 1
    data["avg_amount"] = grouped["amount"].transform(
        lambda s: s.rolling(liquidity_window, min_periods=1).mean()
    )

    eligible = (data["listed_days"] >= min_listed_days) & (data["avg_amount"] >= min_amount)
    if liquidity_top_pct is not None:
        if not 0 < liquidity_top_pct <= 1:
            raise ValueError("liquidity_top_pct must be in (0, 1].")
        pct_rank = data.groupby("date")["avg_amount"].rank(pct=True, ascending=False)
        eligible &= pct_rank <= liquidity_top_pct
    if exclude_st:
        eligible &= ~data["is_st"]
    if exclude_paused:
        eligible &= ~data["is_paused"]
    if exclude_limit_buy:
        eligible &= data["open"] < data["limit_up"]
    data["eligible"] = eligible
    return data.sort_values(["date", "symbol"]).reset_index(drop=True)


def eligible_symbols_on(enriched_bars: pd.DataFrame, as_of_date: pd.Timestamp) -> list[str]:
    """Return eligible symbols on one signal date."""
    date = pd.Timestamp(as_of_date)
    snapshot = enriched_bars[enriched_bars["date"] == date]
    return snapshot.loc[snapshot["eligible"], "symbol"].astype(str).tolist()
