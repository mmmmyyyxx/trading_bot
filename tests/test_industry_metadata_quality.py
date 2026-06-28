from __future__ import annotations

import pandas as pd

from ashare_adapter.industry_metadata import (
    industry_coverage_report,
    industry_quality_status,
    resolve_industry_sources,
    write_industry_coverage_report,
)


def test_industry_source_priority_overwrites_by_priority() -> None:
    existing = pd.DataFrame({"symbol": ["000001.SZ"], "industry": ["old"], "industry_source": ["existing_cache"]})
    eastmoney = pd.DataFrame({"symbol": ["000001.SZ"], "industry": ["board"], "industry_source": ["eastmoney_board_industry"]})
    cninfo = pd.DataFrame({"symbol": ["000001.SZ"], "industry": ["cninfo"], "industry_source": ["cninfo_industry_change"]})

    resolved = resolve_industry_sources(existing=existing, cninfo=cninfo, eastmoney=eastmoney, overwrite=True)

    assert resolved.loc[0, "industry"] == "cninfo"
    assert resolved.loc[0, "source_priority"] == 1


def test_industry_source_priority_respects_no_overwrite() -> None:
    existing = pd.DataFrame({"symbol": ["000001.SZ"], "industry": ["old"], "industry_source": ["existing_cache"]})
    cninfo = pd.DataFrame({"symbol": ["000001.SZ", "000002.SZ"], "industry": ["cninfo", "tech"], "industry_source": ["cninfo_industry_change", "cninfo_industry_change"]})

    resolved = resolve_industry_sources(existing=existing, cninfo=cninfo, overwrite=False)

    assert resolved.loc[resolved["symbol"] == "000001.SZ", "industry"].iloc[0] == "old"
    assert resolved.loc[resolved["symbol"] == "000002.SZ", "industry"].iloc[0] == "tech"


def test_industry_coverage_report_quality_status_and_position_unknown(tmp_path) -> None:
    bars = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "symbol": ["000001.SZ", "000002.SZ"],
            "industry": ["bank", ""],
            "industry_source": ["cninfo_industry_change", ""],
            "selected": [True, True],
        }
    )
    positions = pd.DataFrame(
        {
            "date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "symbol": ["000001.SZ", "000002.SZ"],
            "weight": [0.8, 0.2],
        }
    )

    report = industry_coverage_report(bars, positions=positions)
    summary = write_industry_coverage_report(bars, tmp_path / "industry", positions=positions)

    assert report["summary"]["unknown_symbol_count"] == 1
    assert report["summary"]["unknown_position_weight_avg"] == 0.2
    assert summary["quality_status"] == "failed"
    assert (tmp_path / "industry" / "industry_coverage_summary.json").exists()


def test_industry_quality_thresholds() -> None:
    assert industry_quality_status(
        {"symbol_level_coverage": 0.96, "selected_universe_coverage": 0.96, "unknown_position_weight_avg": 0.05}
    ) == "passed"
    assert industry_quality_status(
        {"symbol_level_coverage": 0.85, "selected_universe_coverage": 0.85, "unknown_position_weight_avg": 0.2}
    ) == "warning"
    assert industry_quality_status(
        {"symbol_level_coverage": 0.7, "selected_universe_coverage": 0.85, "unknown_position_weight_avg": 0.2}
    ) == "failed"
