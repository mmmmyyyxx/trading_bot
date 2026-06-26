"""A-share cost helpers for Qlib and local diagnostics."""

from __future__ import annotations

from dataclasses import dataclass

from ashare_adapter.config import CostConfig


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed cost output for one transaction."""

    raw_value: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    slippage: float
    total_cost: float


def qlib_exchange_kwargs(config: CostConfig) -> dict[str, float | str]:
    """Return Qlib backtest exchange settings."""

    return {
        "limit_threshold": 0.095,
        "deal_price": "close",
        "open_cost": float(config.open_cost),
        "close_cost": float(config.close_cost),
        "min_cost": float(config.min_cost),
    }


def calculate_trade_cost(side: str, price: float, shares: int, config: CostConfig) -> CostBreakdown:
    """Calculate commission, stamp tax, transfer fee, and slippage."""

    if shares <= 0:
        raise ValueError("shares must be positive.")
    side = side.lower()
    if side not in {"buy", "sell"}:
        raise ValueError("side must be 'buy' or 'sell'.")
    raw_value = float(price) * int(shares)
    commission = max(raw_value * config.commission_rate, config.min_cost)
    stamp_tax = raw_value * config.stamp_tax_rate if side == "sell" else 0.0
    transfer_fee = raw_value * config.transfer_fee_rate
    slippage = raw_value * config.slippage_bps / 10_000.0
    total_cost = commission + stamp_tax + transfer_fee + slippage
    return CostBreakdown(
        raw_value=raw_value,
        commission=float(commission),
        stamp_tax=float(stamp_tax),
        transfer_fee=float(transfer_fee),
        slippage=float(slippage),
        total_cost=float(total_cost),
    )
