"""Small Qlib strategy adapters for A-share experiments."""

from __future__ import annotations

from qlib.backtest.decision import TradeDecisionWO
from qlib.contrib.strategy.signal_strategy import TopkDropoutStrategy


class PeriodicTopkDropoutStrategy(TopkDropoutStrategy):
    """TopkDropoutStrategy that only trades every N daily steps.

    This keeps the original Qlib strategy logic and only suppresses trade
    generation on non-rebalance dates. It is intended for turnover sensitivity
    checks, not as a new research alpha model.
    """

    def __init__(self, rebalance_step: int = 1, **kwargs) -> None:
        super().__init__(**kwargs)
        self.rebalance_step = max(1, int(rebalance_step))

    def generate_trade_decision(self, execute_result=None):
        trade_step = self.trade_calendar.get_trade_step()
        if trade_step % self.rebalance_step != 0:
            return TradeDecisionWO([], self)
        return super().generate_trade_decision(execute_result=execute_result)
