"""Top-K stock selection and target-weight construction."""

from __future__ import annotations

import pandas as pd

from ashare_quant.portfolio.constraints import apply_long_only, apply_max_weight, normalize_if_needed


def _equal_weights(symbols: list[str]) -> pd.Series:
    if not symbols:
        return pd.Series(dtype=float)
    return pd.Series(1.0 / len(symbols), index=symbols, dtype=float)


def _inverse_vol_weights(snapshot: pd.DataFrame) -> pd.Series:
    vol = snapshot.set_index("symbol")["volatility"].replace(0, pd.NA).dropna()
    if vol.empty:
        return _equal_weights(snapshot["symbol"].tolist())
    inv = 1.0 / vol.astype(float)
    return inv / inv.sum()


def build_target_weights(
    factor_scores: pd.DataFrame,
    as_of_date: pd.Timestamp,
    eligible_symbols: list[str],
    top_k: int,
    weighting: str,
    max_weight: float,
) -> pd.DataFrame:
    """Build target weights from one signal-date factor cross-section."""
    if top_k <= 0:
        raise ValueError("top_k must be positive.")

    snapshot = factor_scores[
        (factor_scores["date"] == pd.Timestamp(as_of_date))
        & (factor_scores["symbol"].isin(eligible_symbols))
        & factor_scores["composite_score"].notna()
    ].copy()
    return build_target_weights_from_snapshot(snapshot, top_k, weighting, max_weight)


def build_target_weights_from_snapshot(
    snapshot: pd.DataFrame,
    top_k: int,
    weighting: str,
    max_weight: float,
) -> pd.DataFrame:
    """Build target weights from a pre-filtered factor cross-section."""
    if top_k <= 0:
        raise ValueError("top_k must be positive.")
    if snapshot.empty:
        return pd.DataFrame(columns=["symbol", "target_weight"])

    selected = snapshot.sort_values("composite_score", ascending=False).head(top_k)
    symbols = selected["symbol"].tolist()
    if weighting == "inverse_vol_weight":
        weights = _inverse_vol_weights(selected)
    elif weighting == "equal_weight":
        weights = _equal_weights(symbols)
    else:
        raise ValueError(f"Unsupported weighting method: {weighting}")

    weights = weights.reindex(symbols).fillna(0.0)
    weights = normalize_if_needed(apply_max_weight(apply_long_only(weights), max_weight))
    return pd.DataFrame({"symbol": weights.index, "target_weight": weights.values})

