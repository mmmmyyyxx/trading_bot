"""Order matching rules for daily A-share bars."""

from __future__ import annotations

import math

import pandas as pd


def can_trade(row: pd.Series, side: str, price_col: str = "open") -> bool:
    """Return whether an order can trade under pause and limit rules."""
    if bool(row.get("is_paused", False)):
        return False
    price = float(row[price_col])
    if side == "buy" and price >= float(row["limit_up"]):
        return False
    if side == "sell" and price <= float(row["limit_down"]):
        return False
    return True


def round_lot(shares: float, lot_size: int) -> int:
    """Round share quantity down to an A-share lot size."""
    if lot_size <= 0:
        raise ValueError("lot_size must be positive.")
    return int(math.floor(max(shares, 0.0) / lot_size) * lot_size)

