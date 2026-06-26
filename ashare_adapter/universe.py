"""Dynamic A-share universe utilities."""

from __future__ import annotations

import pandas as pd

from ashare_adapter.config import UniverseConfig
from ashare_adapter.filters import add_filter_columns, filter_snapshot

UNIVERSE_DIAGNOSTIC_COLUMNS = [
    "date",
    "raw_count",
    "eligible_count",
    "selected_universe_count",
    "configured_top_n",
    "candidate_pool_limited",
    "st_count",
    "paused_count",
    "limit_buy_blocked_count",
    "listed_days_fallback_rate",
    "industry_coverage_rate",
    "avg_amount_median",
    "avg_amount_min",
]


def build_dynamic_universe(bars: pd.DataFrame, config: UniverseConfig) -> pd.DataFrame:
    """Return bars with backward-looking universe flags."""

    return add_filter_columns(bars, config)


def selected_symbols_on(enriched_bars: pd.DataFrame, date: object) -> list[str]:
    """Return the selected universe on a signal date."""

    snapshot = filter_snapshot(enriched_bars, date, selected_only=True)
    return snapshot["symbol"].astype(str).tolist()


def universe_diagnostic_row(enriched_bars: pd.DataFrame, date: object, top_n: int | None = None) -> dict[str, object]:
    """Build one universe diagnostic row."""

    target = pd.Timestamp(date)
    snapshot = enriched_bars[pd.to_datetime(enriched_bars["date"]) == target].copy()
    eligible = snapshot[snapshot.get("eligible", False).fillna(False).astype(bool)] if not snapshot.empty else snapshot
    selected = snapshot[snapshot.get("selected", False).fillna(False).astype(bool)] if not snapshot.empty else snapshot
    configured_top_n = int(top_n or 0)
    avg_amount = selected["avg_amount"] if "avg_amount" in selected.columns else pd.Series(dtype=float)
    return {
        "date": target,
        "raw_count": int(len(snapshot)),
        "eligible_count": int(len(eligible)),
        "selected_universe_count": int(len(selected)),
        "configured_top_n": configured_top_n,
        "candidate_pool_limited": bool(configured_top_n > 0 and len(eligible) < configured_top_n),
        "st_count": _bool_sum(snapshot, "is_st"),
        "paused_count": _bool_sum(snapshot, "is_paused"),
        "limit_buy_blocked_count": _limit_buy_blocked_count(snapshot),
        "listed_days_fallback_rate": _mean_bool(snapshot, "listed_days_fallback", default=1.0),
        "industry_coverage_rate": _coverage_rate(snapshot, "industry"),
        "avg_amount_median": float(avg_amount.median()) if not avg_amount.empty else 0.0,
        "avg_amount_min": float(avg_amount.min()) if not avg_amount.empty else 0.0,
    }


def build_universe_diagnostics(enriched_bars: pd.DataFrame, top_n: int | None = None) -> pd.DataFrame:
    """Build diagnostics for all dates in a universe-enriched bar frame."""

    rows = [universe_diagnostic_row(enriched_bars, date, top_n) for date in sorted(enriched_bars["date"].unique())]
    if not rows:
        return pd.DataFrame(columns=UNIVERSE_DIAGNOSTIC_COLUMNS)
    return pd.DataFrame(rows)[UNIVERSE_DIAGNOSTIC_COLUMNS]


def _bool_sum(frame: pd.DataFrame, column: str) -> int:
    if frame.empty or column not in frame.columns:
        return 0
    return int(frame[column].fillna(False).astype(bool).sum())


def _mean_bool(frame: pd.DataFrame, column: str, default: float = 0.0) -> float:
    if frame.empty or column not in frame.columns:
        return default
    return float(frame[column].fillna(False).astype(bool).mean())


def _coverage_rate(frame: pd.DataFrame, column: str) -> float:
    if frame.empty or column not in frame.columns:
        return 0.0
    values = frame[column].fillna("").astype(str).str.strip()
    return float((values != "").mean())


def _limit_buy_blocked_count(frame: pd.DataFrame) -> int:
    if frame.empty or not {"open", "limit_up"}.issubset(frame.columns):
        return 0
    return int((pd.to_numeric(frame["open"], errors="coerce") >= pd.to_numeric(frame["limit_up"], errors="coerce")).sum())
