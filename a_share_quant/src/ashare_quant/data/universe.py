"""A-share universe filtering rules."""

from __future__ import annotations

import pandas as pd


UNIVERSE_DIAGNOSTIC_COLUMNS = [
    "date",
    "raw_count",
    "eligible_count",
    "selected_universe_count",
    "configured_top_n",
    "raw_to_top_n_ratio",
    "selected_to_top_n_ratio",
    "candidate_pool_limited",
    "st_count",
    "paused_count",
    "limit_buy_blocked_count",
    "listed_days_fallback_rate",
    "industry_coverage_rate",
    "avg_amount_median",
    "avg_amount_min",
    "universe_mode",
    "candidate_source",
    "possible_selection_bias",
]


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
    if "list_date" in data.columns:
        list_date = pd.to_datetime(data["list_date"], errors="coerce")
        data["listed_days"] = (pd.to_datetime(data["date"]) - list_date).dt.days
        fallback = data["listed_days"].isna()
        data.loc[fallback, "listed_days"] = grouped.cumcount()[fallback] + 1
        list_date_fallback = (
            data["list_date_fallback"].astype(bool)
            if "list_date_fallback" in data.columns
            else pd.Series(False, index=data.index)
        )
        data["listed_days_fallback"] = fallback | list_date_fallback
    else:
        data["listed_days"] = grouped.cumcount() + 1
        data["listed_days_fallback"] = True
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


def possible_selection_bias(universe_mode: str, candidate_source: str | None = None) -> bool:
    """Flag modes whose candidate symbols can come from a current liquidity snapshot."""
    source = (candidate_source or "").lower()
    return universe_mode.lower() in {"current_snapshot", "current_liquidity_snapshot"} or source in {
        "current_snapshot",
        "current_liquidity_snapshot",
        "spot",
    }


def dynamic_liquidity_universe(
    enriched_bars: pd.DataFrame,
    as_of_date: pd.Timestamp,
    top_n: int,
) -> pd.DataFrame:
    """Select the top-N eligible symbols by backward-looking rolling average amount."""
    snapshot = _eligible_snapshot(enriched_bars, as_of_date)
    if snapshot.empty:
        return snapshot
    return snapshot.sort_values(["avg_amount", "symbol"], ascending=[False, True]).head(top_n).reset_index(drop=True)


def select_universe_on(
    enriched_bars: pd.DataFrame,
    as_of_date: pd.Timestamp,
    universe_mode: str = "fixed_symbols",
    top_n: int | None = None,
) -> pd.DataFrame:
    """Return the tradable universe for one signal date under the configured mode."""
    mode = universe_mode.lower()
    top_n = int(top_n or 0)
    if mode == "dynamic_liquidity":
        if top_n <= 0:
            raise ValueError("top_n must be positive for dynamic_liquidity universe.")
        return dynamic_liquidity_universe(enriched_bars, as_of_date, top_n)

    snapshot = _eligible_snapshot(enriched_bars, as_of_date)
    if mode in {"fixed_symbols", "current_snapshot", "current_liquidity_snapshot"}:
        if top_n > 0 and mode != "fixed_symbols":
            snapshot = snapshot.sort_values(["avg_amount", "symbol"], ascending=[False, True]).head(top_n)
        return snapshot.reset_index(drop=True)
    raise ValueError(f"Unsupported universe_mode: {universe_mode}")


def universe_diagnostic_row(
    enriched_bars: pd.DataFrame,
    as_of_date: pd.Timestamp,
    universe_mode: str,
    top_n: int | None = None,
    candidate_source: str = "unknown",
) -> dict[str, object]:
    """Build one signal-date universe diagnostic row."""
    date = pd.Timestamp(as_of_date)
    snapshot = enriched_bars[enriched_bars["date"] == date].copy()
    selected = select_universe_on(enriched_bars, date, universe_mode, top_n)
    eligible = snapshot[snapshot["eligible"]] if "eligible" in snapshot else snapshot.iloc[0:0]
    configured_top_n = int(top_n or 0)

    avg_amount = selected["avg_amount"] if "avg_amount" in selected else pd.Series(dtype=float)
    industry_coverage = _coverage_rate(snapshot, "industry")
    fallback_rate = float(snapshot["listed_days_fallback"].astype(bool).mean()) if "listed_days_fallback" in snapshot and not snapshot.empty else 1.0
    return {
        "date": date,
        "raw_count": int(len(snapshot)),
        "eligible_count": int(len(eligible)),
        "selected_universe_count": int(len(selected)),
        "configured_top_n": configured_top_n,
        "raw_to_top_n_ratio": _ratio(len(snapshot), configured_top_n),
        "selected_to_top_n_ratio": _ratio(len(selected), configured_top_n),
        "candidate_pool_limited": bool(configured_top_n > 0 and len(snapshot) < configured_top_n),
        "st_count": int(snapshot.get("is_st", pd.Series(False, index=snapshot.index)).astype(bool).sum()),
        "paused_count": int(snapshot.get("is_paused", pd.Series(False, index=snapshot.index)).astype(bool).sum()),
        "limit_buy_blocked_count": _limit_buy_blocked_count(snapshot),
        "listed_days_fallback_rate": fallback_rate,
        "industry_coverage_rate": industry_coverage,
        "avg_amount_median": float(avg_amount.median()) if not avg_amount.empty else 0.0,
        "avg_amount_min": float(avg_amount.min()) if not avg_amount.empty else 0.0,
        "universe_mode": universe_mode,
        "candidate_source": candidate_source,
        "possible_selection_bias": possible_selection_bias(universe_mode, candidate_source),
    }


def build_universe_diagnostics(
    enriched_bars: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    universe_mode: str,
    top_n: int | None = None,
    candidate_source: str = "unknown",
) -> pd.DataFrame:
    """Build universe diagnostics for all signal dates."""
    rows = [
        universe_diagnostic_row(enriched_bars, date, universe_mode, top_n, candidate_source)
        for date in signal_dates
    ]
    if not rows:
        return pd.DataFrame(columns=UNIVERSE_DIAGNOSTIC_COLUMNS)
    return pd.DataFrame(rows)[UNIVERSE_DIAGNOSTIC_COLUMNS]


def daily_universe_size(diagnostics: pd.DataFrame) -> pd.DataFrame:
    """Return the compact daily universe-size report."""
    columns = [
        "date",
        "raw_count",
        "eligible_count",
        "selected_universe_count",
        "configured_top_n",
        "raw_to_top_n_ratio",
        "selected_to_top_n_ratio",
        "candidate_pool_limited",
        "universe_mode",
        "candidate_source",
        "possible_selection_bias",
    ]
    if diagnostics.empty:
        return pd.DataFrame(columns=columns)
    return diagnostics[columns].copy()


def _eligible_snapshot(enriched_bars: pd.DataFrame, as_of_date: pd.Timestamp) -> pd.DataFrame:
    date = pd.Timestamp(as_of_date)
    snapshot = enriched_bars[enriched_bars["date"] == date].copy()
    if snapshot.empty or "eligible" not in snapshot:
        return snapshot.iloc[0:0]
    return snapshot[snapshot["eligible"]].copy()


def _coverage_rate(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = frame[column].fillna("").astype(str).str.strip()
    return float((values != "").mean())


def _limit_buy_blocked_count(frame: pd.DataFrame) -> int:
    if frame.empty or "open" not in frame.columns or "limit_up" not in frame.columns:
        return 0
    open_price = pd.to_numeric(frame["open"], errors="coerce")
    limit_up = pd.to_numeric(frame["limit_up"], errors="coerce")
    return int((open_price >= limit_up).fillna(False).sum())


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator / denominator)
