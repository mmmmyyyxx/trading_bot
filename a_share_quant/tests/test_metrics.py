from __future__ import annotations

import pandas as pd
import pytest

from ashare_quant.backtest.metrics import compute_metrics


def test_metrics_report_net_gross_drawdown_and_turnover() -> None:
    equity = pd.DataFrame(
        {
            "date": pd.date_range("2023-01-01", periods=4),
            "net_equity": [100.0, 102.0, 101.0, 104.0],
            "gross_equity": [100.0, 102.2, 101.4, 104.5],
            "daily_return": [0.0, 0.02, -0.0098039, 0.029703],
            "turnover": [0.0, 0.3, 0.1, 0.2],
        }
    )
    trades = pd.DataFrame({"total_cost": [0.2, 0.3]})

    metrics = compute_metrics(equity, trades, initial_cash=100.0)

    assert metrics["total_return"] == pytest.approx(0.04)
    assert metrics["gross_total_return"] == pytest.approx(0.045)
    assert metrics["max_drawdown"] < 0
    assert metrics["turnover"] == pytest.approx(0.6)
    assert metrics["total_cost"] == pytest.approx(0.5)
