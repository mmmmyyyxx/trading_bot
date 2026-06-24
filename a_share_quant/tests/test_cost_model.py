from __future__ import annotations

from ashare_quant.backtest.cost import CostModel
from ashare_quant.config import CostConfig


def test_cost_model_has_configurable_a_share_fees() -> None:
    model = CostModel(
        CostConfig(
            commission_rate=0.001,
            min_commission=5.0,
            stamp_tax_rate=0.001,
            transfer_fee_rate=0.00002,
            slippage_bps=10.0,
        )
    )

    buy = model.calculate("buy", raw_price=10.0, shares=1000)
    sell = model.calculate("sell", raw_price=10.0, shares=1000)

    assert round(buy.commission, 2) == 10.00
    assert round(buy.stamp_tax, 2) == 0.00
    assert round(buy.transfer_fee, 2) == 0.20
    assert round(buy.slippage, 2) == 10.00
    assert round(sell.stamp_tax, 2) == 10.00
    assert sell.total_cost > buy.total_cost

