from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_quant.backtest.engine import BacktestEngine
from ashare_quant.config import AppConfig
from ashare_quant.config import load_config
from ashare_quant.pipeline import run_backtest_pipeline


def test_backtest_pipeline_runs_offline_and_writes_reports(tmp_path: Path) -> None:
    config = load_config("configs/default.yaml")
    config.report.output_dir = str(tmp_path / "reports")

    result = run_backtest_pipeline(config, refresh_data=False, write_outputs=True)

    assert not result.equity_curve.empty
    assert not result.positions.empty
    assert "total_return" in result.metrics
    assert (tmp_path / "reports" / "backtest_summary.json").exists()
    assert (tmp_path / "reports" / "equity_curve.csv").exists()
    assert (tmp_path / "reports" / "trades.csv").exists()
    assert (tmp_path / "reports" / "positions.csv").exists()


def test_backtest_can_skip_position_snapshots() -> None:
    dates = pd.bdate_range("2025-01-01", periods=5)
    bars = pd.DataFrame(
        [
            {
                "date": date,
                "symbol": "000001.SZ",
                "open": 10.0,
                "high": 10.5,
                "low": 9.5,
                "close": 10.0 + idx * 0.1,
                "volume": 1000,
                "amount": 1000000.0,
                "adj_factor": 1.0,
                "is_paused": False,
                "is_st": False,
                "limit_up": 11.0,
                "limit_down": 9.0,
            }
            for idx, date in enumerate(dates)
        ]
    )
    targets = pd.DataFrame({"date": [dates[0]], "symbol": ["000001.SZ"], "target_weight": [1.0]})
    config = AppConfig()
    config.backtest.lot_size = 1
    config.backtest.save_positions = False

    result = BacktestEngine(config).run(bars, targets)

    assert not result.equity_curve.empty
    assert result.positions.empty
    assert "total_return" in result.metrics
