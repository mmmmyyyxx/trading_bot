"""Configurable A-share cost model."""

from __future__ import annotations

from dataclasses import dataclass

from ashare_quant.config import CostConfig


@dataclass(frozen=True)
class CostBreakdown:
    """Detailed cost and execution-price output for one matched trade."""

    raw_price: float
    execution_price: float
    shares: int
    raw_value: float
    execution_value: float
    commission: float
    stamp_tax: float
    transfer_fee: float
    slippage: float
    total_cost: float


class CostModel:
    """Calculate commission, stamp tax, transfer fee, and slippage."""

    def __init__(self, config: CostConfig) -> None:
        self.config = config

    def calculate(self, side: str, raw_price: float, shares: int) -> CostBreakdown:
        """Return cost details for a buy or sell trade."""
        if shares <= 0:
            raise ValueError("shares must be positive.")
        side = side.lower()
        if side not in {"buy", "sell"}:
            raise ValueError("side must be 'buy' or 'sell'.")

        slip_mult = self.config.slippage_bps / 10_000.0
        execution_price = raw_price * (1.0 + slip_mult if side == "buy" else 1.0 - slip_mult)
        raw_value = raw_price * shares
        execution_value = execution_price * shares
        commission = max(raw_value * self.config.commission_rate, self.config.min_commission)
        stamp_tax = raw_value * self.config.stamp_tax_rate if side == "sell" else 0.0
        transfer_fee = raw_value * self.config.transfer_fee_rate
        slippage = abs(execution_value - raw_value)
        total_cost = commission + stamp_tax + transfer_fee + slippage
        return CostBreakdown(
            raw_price=float(raw_price),
            execution_price=float(execution_price),
            shares=int(shares),
            raw_value=float(raw_value),
            execution_value=float(execution_value),
            commission=float(commission),
            stamp_tax=float(stamp_tax),
            transfer_fee=float(transfer_fee),
            slippage=float(slippage),
            total_cost=float(total_cost),
        )

