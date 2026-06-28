from __future__ import annotations

import pandas as pd
import pytest

from ashare_adapter.akshare_downloader import validate_bars
from ashare_adapter.data_quality import selected_universe_quality, validate_ashare_bars_quality, write_data_quality_report


def test_unknown_data_source_and_legacy_missing_are_flagged() -> None:
    bars = _bars()
    bars = bars.drop(columns=["data_source"], errors="ignore")

    row_quality, summary = validate_ashare_bars_quality(validate_bars(bars))

    assert set(row_quality["data_source"]) == {"legacy_unknown"}
    assert row_quality["quality_flags"].str.contains("legacy_missing_data_source").all()
    assert float(summary.loc[0, "unknown_source_ratio"]) == 1.0
    assert summary.loc[0, "quality_status"] == "failed"


def test_invalid_ohlc_duplicate_and_limit_are_detected() -> None:
    bars = _bars()
    bars.loc[0, "high"] = 1.0
    bars.loc[1, "limit_up"] = 1.0
    bars = pd.concat([bars, bars.iloc[[0]]], ignore_index=True)

    row_quality, summary = validate_ashare_bars_quality(bars)

    assert row_quality["quality_flags"].str.contains("invalid_ohlc").any()
    assert row_quality["quality_flags"].str.contains("invalid_limit").any()
    assert row_quality["quality_flags"].str.contains("duplicate_date_symbol").any()
    assert int(summary.loc[0, "duplicate_rows"]) == 2
    assert summary.loc[0, "quality_status"] == "failed"


def test_pause_flag_mismatch_is_warning_flag() -> None:
    bars = _bars()
    bars.loc[0, "volume"] = 0
    bars.loc[0, "amount"] = 0
    bars.loc[0, "is_paused"] = False

    row_quality, summary = validate_ashare_bars_quality(bars)

    assert row_quality.loc[0, "quality_flags"].find("pause_flag_mismatch") >= 0
    assert float(summary.loc[0, "pause_flag_mismatch_ratio"]) > 0


def test_extreme_amount_jump_is_reported(tmp_path) -> None:
    bars = pd.concat([_bars(), _bars()], ignore_index=True)
    bars.loc[2:, "date"] = pd.Timestamp("2024-01-03")
    bars.loc[2, "amount"] = bars.loc[0, "amount"] * 50

    row_quality, summary = validate_ashare_bars_quality(bars)
    report = write_data_quality_report(bars, tmp_path / "quality")

    assert row_quality["quality_flags"].str.contains("extreme_amount_jump").any()
    assert float(summary.loc[0, "extreme_amount_jump_ratio"]) > 0
    assert report["reports"]["extreme_amount_jump_rows"].endswith("extreme_amount_jump_rows.csv")
    assert (tmp_path / "quality" / "extreme_amount_jump_rows.csv").exists()


def test_selected_universe_quality_only_counts_selected_rows() -> None:
    bars = _bars()
    bars.loc[bars["symbol"] == "000002.SZ", "selected"] = False
    bars.loc[bars["symbol"] == "000002.SZ", "data_source"] = "legacy_unknown"

    quality = selected_universe_quality(bars)

    assert quality["selected_count"].iloc[0] == 1
    assert quality["unknown_source_count"].iloc[0] == 0


def test_data_quality_report_can_fail_on_error(tmp_path) -> None:
    bars = _bars().drop(columns=["data_source"])

    with pytest.raises(RuntimeError):
        write_data_quality_report(bars, tmp_path / "quality", fail_on_error=True)


def _bars() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "symbol": ["000001.SZ", "000002.SZ"],
            "open": [10.0, 20.0],
            "high": [10.5, 20.5],
            "low": [9.8, 19.8],
            "close": [10.2, 20.2],
            "volume": [1000.0, 2000.0],
            "amount": [10_200.0, 40_400.0],
            "factor": [1.0, 1.0],
            "is_paused": [False, False],
            "is_st": [False, False],
            "limit_up": [11.0, 22.0],
            "limit_down": [9.0, 18.0],
            "list_date": pd.to_datetime(["2020-01-01", "2020-01-01"]),
            "industry": ["bank", "tech"],
            "selected": [True, True],
            "eligible": [True, True],
            "data_source": ["eastmoney", "eastmoney"],
            "amount_estimated": [False, False],
        }
    )
