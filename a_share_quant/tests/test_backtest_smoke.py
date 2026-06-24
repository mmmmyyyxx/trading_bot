from __future__ import annotations

from pathlib import Path

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
