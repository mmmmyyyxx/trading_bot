from __future__ import annotations

import pandas as pd
import pytest

from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers
from scripts.update_2018_2026_cache import update_cache


def test_real_data_manifest_requires_data_type() -> None:
    with pytest.raises(ValueError):
        assert_formal_report_uses_real_data("reports/alpha158_demo/summary.json", {"data": {}})

    assert_formal_report_uses_real_data("reports/alpha158_demo/summary.json", {"data": real_data_markers()})


def test_synthetic_results_not_written_to_formal_reports() -> None:
    payload = {"data": {"data_type": "synthetic", "synthetic_data": True, "mock_data": False}}

    with pytest.raises(ValueError):
        assert_formal_report_uses_real_data("reports/rolling_baseline_comparison_2018_2026_real.csv", payload)


def test_pipeline_refuses_synthetic_without_test_flag() -> None:
    with pytest.raises(ValueError):
        assert_formal_report_uses_real_data(
            "reports/universe_expansion_comparison.csv",
            {"data": {"data_type": "synthetic", "synthetic_data": True, "mock_data": False}},
        )


def test_download_failure_does_not_fallback_to_synthetic(monkeypatch, tmp_path) -> None:
    symbols_file = tmp_path / "symbols.txt"
    symbols_file.write_text("000001.SZ\n", encoding="utf-8")

    class FailingDownloader:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def fetch_bars(self, *args, **kwargs):
            raise RuntimeError("network unavailable")

    monkeypatch.setattr("scripts.update_2018_2026_cache.AKShareDownloader", FailingDownloader)

    with pytest.raises(RuntimeError, match="No bar rows available"):
        update_cache(
            symbols_file=symbols_file,
            output_bars=tmp_path / "bars.parquet",
            start_date="2024-01-01",
            end_date="2024-01-31",
            refresh_bars=True,
            workers=1,
        )

    assert not (tmp_path / "bars.parquet").exists()


def test_download_source_reports_are_written(monkeypatch, tmp_path) -> None:
    symbols_file = tmp_path / "symbols.txt"
    symbols_file.write_text("000001.SZ\n", encoding="utf-8")

    class ReportingDownloader:
        def __init__(self, *args, **kwargs) -> None:
            self.fetch_attempts = []

        def fetch_bars(self, *args, **kwargs):
            self.fetch_attempts = [
                {
                    "symbol": "000001.SZ",
                    "source": "eastmoney",
                    "attempt_order": 1,
                    "status": "failed",
                    "rows": 0,
                    "fallback_used": False,
                    "error": "temporary",
                },
                {
                    "symbol": "000001.SZ",
                    "source": "tencent_tx",
                    "attempt_order": 2,
                    "status": "success",
                    "rows": 2,
                    "fallback_used": True,
                    "error": "",
                },
            ]
            return pd.DataFrame(
                {
                    "date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
                    "symbol": ["000001.SZ", "000001.SZ"],
                    "open": [10.0, 10.2],
                    "high": [10.5, 10.4],
                    "low": [9.8, 10.0],
                    "close": [10.2, 10.3],
                    "volume": [1000.0, 1100.0],
                    "amount": [10200.0, 11330.0],
                    "factor": [1.0, 1.0],
                    "is_paused": [False, False],
                    "is_st": [False, False],
                    "limit_up": [11.0, 11.2],
                    "limit_down": [9.0, 9.2],
                    "list_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
                    "industry": ["bank", "bank"],
                    "data_source": ["tencent_tx", "tencent_tx"],
                    "amount_estimated": [False, False],
                }
            )

    monkeypatch.setattr("scripts.update_2018_2026_cache.AKShareDownloader", ReportingDownloader)

    update_cache(
        symbols_file=symbols_file,
        output_bars=tmp_path / "bars.parquet",
        start_date="2024-01-02",
        end_date="2024-01-03",
        refresh_bars=True,
        workers=1,
        download_summary=tmp_path / "reports" / "download_summary.json",
    )

    assert (tmp_path / "reports" / "download_source_summary.csv").exists()
    assert (tmp_path / "reports" / "download_failure_summary.csv").exists()
    fallback = pd.read_csv(tmp_path / "reports" / "source_fallback_summary.csv")
    assert bool(fallback.loc[0, "fallback_used"])


def test_formal_report_requires_real_data_manifest() -> None:
    formal_path = "reports/alpha158_hs300_2018_2026/run_manifest.json"
    with pytest.raises(ValueError):
        assert_formal_report_uses_real_data(
            formal_path,
            {"data": {"data_type": "real_akshare", "synthetic_data": True, "mock_data": False}},
        )


def test_synthetic_allowed_only_under_test_report_root() -> None:
    assert_formal_report_uses_real_data(
        "reports/synthetic_test_only/example/summary.json",
        {"data": {"data_type": "synthetic", "synthetic_data": True, "mock_data": False}},
        allow_synthetic_test=True,
    )
