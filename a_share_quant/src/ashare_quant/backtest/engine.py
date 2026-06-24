"""Daily semi-event-driven A-share backtest engine."""

from __future__ import annotations

import logging

import pandas as pd

from ashare_quant.backtest.broker import PositionBook
from ashare_quant.backtest.cost import CostModel
from ashare_quant.backtest.matching import can_trade, round_lot
from ashare_quant.backtest.metrics import compute_metrics
from ashare_quant.backtest.result import BacktestResult
from ashare_quant.config import AppConfig
from ashare_quant.data.base import validate_bars

LOGGER = logging.getLogger(__name__)


class BacktestEngine:
    """Run a long-only daily backtest with A-share trading constraints."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.cost_model = CostModel(config.cost)

    def run(self, bars: pd.DataFrame, targets: pd.DataFrame) -> BacktestResult:
        """Execute target weights and return equity, trades, positions, metrics."""
        data = validate_bars(bars)
        targets = targets.copy()
        if not targets.empty:
            targets["date"] = pd.to_datetime(targets["date"])

        by_date = {date: frame.set_index("symbol") for date, frame in data.groupby("date")}
        target_by_date = {date: frame for date, frame in targets.groupby("date")}
        days = sorted(by_date)

        cash = float(self.config.backtest.initial_cash)
        book = PositionBook()
        cumulative_cost = 0.0
        prev_net = cash
        prev_gross = cash

        equity_rows: list[dict[str, object]] = []
        trade_rows: list[dict[str, object]] = []
        position_rows: list[dict[str, object]] = []

        start_date = pd.Timestamp(self.config.backtest.start_date) if self.config.backtest.start_date else None
        end_date = pd.Timestamp(self.config.backtest.end_date) if self.config.backtest.end_date else None

        for date in days:
            if start_date is not None and date < start_date:
                continue
            if end_date is not None and date > end_date:
                continue
            day_bars = by_date[date]
            turnover_value = 0.0
            day_cost = 0.0

            if date in target_by_date:
                trade_result = self._rebalance(date, day_bars, target_by_date[date], cash, book)
                cash = trade_result["cash"]
                turnover_value = trade_result["turnover_value"]
                day_cost = trade_result["day_cost"]
                cumulative_cost += day_cost
                trade_rows.extend(trade_result["trades"])

            close_value = self._mark_to_market(book, day_bars, "close")
            net_equity = cash + close_value
            gross_equity = net_equity + cumulative_cost
            turnover = turnover_value / prev_net if prev_net > 0 else 0.0
            daily_return = net_equity / prev_net - 1.0 if prev_net > 0 else 0.0
            gross_return = gross_equity / prev_gross - 1.0 if prev_gross > 0 else 0.0

            equity_rows.append(
                {
                    "date": date,
                    "cash": cash,
                    "net_equity": net_equity,
                    "gross_equity": gross_equity,
                    "daily_return": daily_return,
                    "gross_return": gross_return,
                    "turnover": turnover,
                    "cost": day_cost,
                    "drawdown": 0.0,
                }
            )
            position_rows.extend(self._position_snapshot(date, book, day_bars, net_equity))
            prev_net = net_equity
            prev_gross = gross_equity

        equity_curve = pd.DataFrame(equity_rows)
        if not equity_curve.empty:
            equity_curve["drawdown"] = equity_curve["net_equity"] / equity_curve["net_equity"].cummax() - 1.0
        trades_df = pd.DataFrame(trade_rows)
        positions_df = pd.DataFrame(position_rows)
        metrics = compute_metrics(
            equity_curve,
            trades_df,
            initial_cash=float(self.config.backtest.initial_cash),
        )
        return BacktestResult(equity_curve=equity_curve, trades=trades_df, positions=positions_df, metrics=metrics)

    def _portfolio_value_at_open(self, cash: float, book: PositionBook, day_bars: pd.DataFrame) -> float:
        return cash + self._mark_to_market(book, day_bars, self.config.backtest.trade_price)

    def _mark_to_market(self, book: PositionBook, day_bars: pd.DataFrame, price_col: str) -> float:
        total = 0.0
        for symbol in book.symbols():
            if symbol in day_bars.index:
                total += book.get(symbol) * float(day_bars.loc[symbol, price_col])
        return total

    def _rebalance(
        self,
        date: pd.Timestamp,
        day_bars: pd.DataFrame,
        target_frame: pd.DataFrame,
        cash: float,
        book: PositionBook,
    ) -> dict[str, object]:
        target_weights = target_frame.set_index("symbol")["target_weight"].astype(float)
        open_value = self._portfolio_value_at_open(cash, book, day_bars)
        lot_size = int(self.config.backtest.lot_size)
        price_col = self.config.backtest.trade_price
        symbols = sorted(set(book.symbols()) | set(target_weights.index))

        orders: list[tuple[str, str, int]] = []
        for symbol in symbols:
            if symbol not in day_bars.index:
                continue
            price = float(day_bars.loc[symbol, price_col])
            current_shares = book.get(symbol)
            target_value = open_value * float(target_weights.get(symbol, 0.0))
            target_shares = round_lot(target_value / price, lot_size)
            delta = target_shares - current_shares
            if delta < 0:
                orders.append(("sell", symbol, abs(delta)))
            elif delta > 0:
                orders.append(("buy", symbol, delta))

        trades: list[dict[str, object]] = []
        turnover_value = 0.0
        day_cost = 0.0

        for side, symbol, requested in sorted(orders, key=lambda item: 0 if item[0] == "sell" else 1):
            row = day_bars.loc[symbol]
            if not can_trade(row, side, price_col):
                LOGGER.debug("Order blocked by matching rules: %s %s on %s", side, symbol, date.date())
                continue

            shares = round_lot(requested, lot_size)
            if side == "sell":
                shares = min(shares, book.available_to_sell(symbol, date, self.config.backtest.t_plus_one))
            if shares <= 0:
                continue

            price = float(row[price_col])
            cost = self.cost_model.calculate(side, price, shares)
            if side == "buy":
                shares, cost = self._fit_buy_to_cash(cash, price, shares, lot_size)
                if shares <= 0:
                    continue
                cash -= cost.execution_value + cost.commission + cost.stamp_tax + cost.transfer_fee
                book.buy(symbol, shares, date)
            else:
                cash += cost.execution_value - cost.commission - cost.stamp_tax - cost.transfer_fee
                book.sell(symbol, shares)

            turnover_value += cost.raw_value
            day_cost += cost.total_cost
            trades.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "side": side,
                    "shares": shares,
                    "price": cost.raw_price,
                    "execution_price": cost.execution_price,
                    "raw_value": cost.raw_value,
                    "execution_value": cost.execution_value,
                    "commission": cost.commission,
                    "stamp_tax": cost.stamp_tax,
                    "transfer_fee": cost.transfer_fee,
                    "slippage": cost.slippage,
                    "total_cost": cost.total_cost,
                    "cash_after": cash,
                }
            )

        return {"cash": cash, "turnover_value": turnover_value, "day_cost": day_cost, "trades": trades}

    def _fit_buy_to_cash(self, cash: float, price: float, shares: int, lot_size: int):
        while shares > 0:
            cost = self.cost_model.calculate("buy", price, shares)
            cash_needed = cost.execution_value + cost.commission + cost.transfer_fee
            if cash_needed <= cash:
                return shares, cost
            shares -= lot_size
        return 0, self.cost_model.calculate("buy", price, lot_size)

    def _position_snapshot(
        self,
        date: pd.Timestamp,
        book: PositionBook,
        day_bars: pd.DataFrame,
        net_equity: float,
    ) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for symbol in book.symbols():
            if symbol not in day_bars.index:
                continue
            shares = book.get(symbol)
            close = float(day_bars.loc[symbol, "close"])
            market_value = shares * close
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "shares": shares,
                    "close": close,
                    "market_value": market_value,
                    "weight": market_value / net_equity if net_equity > 0 else 0.0,
                    "industry": day_bars.loc[symbol, "industry"] if "industry" in day_bars.columns else "",
                    "market_cap": day_bars.loc[symbol, "market_cap"] if "market_cap" in day_bars.columns else 0.0,
                }
            )
        return rows
