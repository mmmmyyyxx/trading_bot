"""Qlib exchange extensions for A-share trading constraints."""

from __future__ import annotations

import pandas as pd
from qlib.backtest.exchange import Exchange


class AShareExchange(Exchange):
    """Exchange that blocks orders using per-stock A-share limit fields.

    Qlib's built-in float ``limit_threshold`` applies one uniform percentage
    to all stocks. This exchange uses the dumped ``$limit_up``, ``$limit_down``,
    and ``$is_paused`` fields so ST, main-board, STAR/ChiNext, and BJ names can
    be represented by their own daily limits in the data.
    """

    def __init__(
        self,
        limit_price_buffer: float = 0.001,
        block_paused: bool = True,
        preserve_qlib_limit: bool = False,
        subscribe_fields: list | None = None,
        **kwargs,
    ) -> None:
        self.limit_price_buffer = float(limit_price_buffer)
        self.block_paused = bool(block_paused)
        self.preserve_qlib_limit = bool(preserve_qlib_limit)
        fields = set(subscribe_fields or [])
        fields.update({"$limit_up", "$limit_down", "$is_paused"})
        super().__init__(subscribe_fields=sorted(fields), **kwargs)

    def get_quote_from_qlib(self) -> None:
        """Load quote data, then replace limit flags with A-share field rules."""

        super().get_quote_from_qlib()
        frame = self.quote_df
        close = pd.to_numeric(frame.get("$close"), errors="coerce")
        limit_up = pd.to_numeric(frame.get("$limit_up"), errors="coerce")
        limit_down = pd.to_numeric(frame.get("$limit_down"), errors="coerce")
        paused = pd.to_numeric(frame.get("$is_paused", 0.0), errors="coerce").fillna(0.0).gt(0.5)
        suspended = close.isna()

        buffer = max(0.0, self.limit_price_buffer)
        buy_limited = close.notna() & limit_up.notna() & close.ge(limit_up * (1.0 - buffer))
        sell_limited = close.notna() & limit_down.notna() & close.le(limit_down * (1.0 + buffer))
        if self.block_paused:
            buy_limited = buy_limited | paused
            sell_limited = sell_limited | paused
        buy_limited = buy_limited | suspended
        sell_limited = sell_limited | suspended

        if self.preserve_qlib_limit:
            buy_limited = buy_limited | frame["limit_buy"].fillna(False).astype(bool)
            sell_limited = sell_limited | frame["limit_sell"].fillna(False).astype(bool)
        frame["limit_buy"] = buy_limited.astype(bool)
        frame["limit_sell"] = sell_limited.astype(bool)


def ashare_exchange_kwargs(
    start_time: str,
    end_time: str,
    codes: str = "all",
    deal_price: str = "close",
    open_cost: float = 0.00031,
    close_cost: float = 0.00081,
    min_cost: float = 5.0,
    limit_threshold: float | None = 0.095,
    limit_price_buffer: float = 0.001,
) -> dict:
    """Build Qlib ``exchange_kwargs`` for the custom A-share exchange."""

    return {
        "exchange": {
            "class": "AShareExchange",
            "module_path": "ashare_adapter.exchange",
            "kwargs": {
                "freq": "day",
                "start_time": start_time,
                "end_time": end_time,
                "codes": codes,
                "deal_price": deal_price,
                "open_cost": open_cost,
                "close_cost": close_cost,
                "min_cost": min_cost,
                "limit_threshold": limit_threshold,
                "limit_price_buffer": limit_price_buffer,
            },
        }
    }
