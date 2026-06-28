from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import yaml

from ashare_adapter.active_exposure import active_holdings, up_down_market_performance
from ashare_adapter.akshare_downloader import validate_bars
from ashare_adapter.benchmarks import dump_benchmarks_to_qlib
from ashare_adapter.config import UniverseConfig
from ashare_adapter.diagnostics import compute_group_returns, compute_ic, compute_turnover, split_oos
from ashare_adapter.factors import reversal_lowvol_scores
from ashare_adapter.industry_metadata import (
    industry_coverage,
    industry_unknown_by_date,
    industry_unknown_by_position,
    merge_industry_map,
    parse_cninfo_industry,
)
from ashare_adapter.manifest import build_run_manifest
from ashare_adapter.metadata import limit_rate, normalize_symbol, to_qlib_symbol, write_metadata_sidecar
from ashare_adapter.qlib_converter import dump_qlib_bin, prepare_qlib_frame
from ashare_adapter.signal_mask import apply_selected_mask, to_qlib_signal_frame
from ashare_adapter.sufficiency import assess_data_sufficiency, data_sufficiency_caveats
from ashare_adapter.universe import build_dynamic_universe, build_universe_diagnostics, selected_symbols_on
from scripts.build_expanded_universe import build_universe
from scripts.run_rolling_baselines import MODEL_SPECS, ROLLING_WINDOWS, build_workflow_config, parse_qrun_log
from scripts.run_rolling_baselines_2018_2026 import ROLLING_WINDOWS_2018_2026, _caveats, _merge_comparison
from scripts.write_rolling_stability_summary import summarize_stability


def test_symbol_and_limit_rules() -> None:
    assert normalize_symbol("sh600000") == "600000.SH"
    assert normalize_symbol("000001") == "000001.SZ"
    assert to_qlib_symbol("000001.SZ") == "SZ000001"
    assert limit_rate("600000.SH", False) == 0.10
    assert limit_rate("300001.SZ", False) == 0.20
    assert limit_rate("688001.SH", False) == 0.20
    assert limit_rate("830001.BJ", False) == 0.30
    assert limit_rate("000001.SZ", True) == 0.05


def test_universe_filters_are_backward_looking() -> None:
    bars = _make_bars(symbol_count=4, periods=8)
    bars.loc[(bars["date"] == bars["date"].min()) & (bars["symbol"] == "000004.SZ"), "is_st"] = True
    bars.loc[(bars["date"] == bars["date"].min()) & (bars["symbol"] == "000003.SZ"), "is_paused"] = True
    config = UniverseConfig(
        min_listed_days=2,
        min_amount=0,
        liquidity_window=3,
        dynamic_liquidity_top_n=2,
    )

    enriched = build_dynamic_universe(bars, config)
    first_date_symbols = selected_symbols_on(enriched, bars["date"].min())
    later_symbols = selected_symbols_on(enriched, bars["date"].unique()[3])

    assert first_date_symbols == []
    assert len(later_symbols) == 2
    assert later_symbols[0] == "000004.SZ"

    edited = bars.copy()
    cutoff = pd.Timestamp(bars["date"].unique()[3])
    edited.loc[edited["date"] > cutoff, "amount"] *= 100
    changed = build_dynamic_universe(edited, config)
    left = enriched.loc[enriched["date"] <= cutoff, ["date", "symbol", "avg_amount", "selected"]].reset_index(drop=True)
    right = changed.loc[changed["date"] <= cutoff, ["date", "symbol", "avg_amount", "selected"]].reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right)


def test_qlib_bin_dump_smoke(tmp_path) -> None:
    bars = _make_bars(symbol_count=2, periods=5)
    config = UniverseConfig(min_listed_days=1, min_amount=0, liquidity_window=2)
    frame = prepare_qlib_frame(bars, config)
    assert {"qlib_symbol", "eligible", "selected", "avg_amount", "vwap"}.issubset(frame.columns)

    qlib_dir = dump_qlib_bin(bars, tmp_path / "qlib", config)
    assert (qlib_dir / "calendars" / "day.txt").exists()
    assert (qlib_dir / "calendars" / "day_future.txt").exists()
    assert (qlib_dir / "instruments" / "all.txt").exists()
    close_bin = qlib_dir / "features" / "sz000001" / "close.day.bin"
    assert close_bin.exists()
    payload = np.fromfile(close_bin, dtype="<f4")
    assert payload[0] == 0.0
    assert len(payload) == 6
    for field in ["vwap", "eligible", "selected", "avg_amount", "limit_up", "limit_down"]:
        assert (qlib_dir / "features" / "sz000001" / f"{field}.day.bin").exists()
    assert (qlib_dir / "metadata" / "instruments.parquet").exists() or (qlib_dir / "metadata" / "instruments.csv").exists()

    benchmark_dir = dump_benchmarks_to_qlib(_make_benchmarks(), qlib_dir)
    assert benchmark_dir == qlib_dir
    assert (qlib_dir / "instruments" / "benchmarks.txt").exists()
    assert "SH000300" not in (qlib_dir / "instruments" / "all.txt").read_text(encoding="utf-8")
    bench_payload = np.fromfile(qlib_dir / "features" / "sh000300" / "close.day.bin", dtype="<f4")
    assert bench_payload[0] == 0.0


def test_diagnostics_smoke() -> None:
    bars = _make_bars(symbol_count=40, periods=90)
    scores = reversal_lowvol_scores(bars, reversal_window=3, volatility_window=5).dropna(subset=["score"])

    ic_summary, ic_daily = compute_ic(bars, scores, horizons=[1, 5], min_cross_section=20)
    group_summary, group_returns = compute_group_returns(bars, scores, n_groups=5, horizon=1)
    turnover = compute_turnover(_make_positions())
    oos = split_oos(_make_equity(), "2022-01-04")

    assert not ic_summary.empty
    assert {"ic", "rank_ic"}.issubset(ic_daily.columns)
    assert group_summary["group"].nunique() == 5
    assert not group_returns.empty
    assert turnover["turnover"].iloc[0] > 0
    assert set(oos["segment"]) == {"in_sample", "out_of_sample"}


def test_universe_diagnostics_columns() -> None:
    bars = _make_bars(symbol_count=3, periods=4)
    enriched = build_dynamic_universe(bars, UniverseConfig(min_listed_days=1, min_amount=0, dynamic_liquidity_top_n=2))
    diagnostics = build_universe_diagnostics(enriched, top_n=2)
    assert diagnostics["selected_universe_count"].max() == 2
    assert "listed_days_fallback_rate" in diagnostics.columns


def test_signal_mask_masks_non_selected_scores() -> None:
    bars = _make_bars(symbol_count=2, periods=2)
    bars["selected"] = True
    target_date = bars["date"].min()
    bars.loc[(bars["date"] == target_date) & (bars["symbol"] == "000002.SZ"), "selected"] = False
    predictions = pd.DataFrame(
        {
            "date": [target_date, target_date],
            "symbol": ["SZ000001", "SZ000002"],
            "score": [1.0, 2.0],
        }
    )

    masked = apply_selected_mask(predictions, bars)
    assert len(masked) == len(predictions)
    assert int(masked["score"].isna().sum()) == 1
    kept = masked.loc[masked["symbol"] == "000001.SZ", "score"].iloc[0]
    blocked = masked.loc[masked["symbol"] == "000002.SZ", "score"].iloc[0]
    signal = to_qlib_signal_frame(masked)

    assert kept == 1.0
    assert pd.isna(blocked)
    assert signal.index.names == ["datetime", "instrument"]
    assert ("SZ000001" in signal.index.get_level_values("instrument"))


def test_run_manifest_marks_eligible_only_when_top_n_is_absent(tmp_path) -> None:
    summary_path = tmp_path / "summary.json"
    runtime_config_path = tmp_path / "runtime.yaml"
    diagnostics_path = tmp_path / "universe_diagnostics.csv"

    summary_path.write_text(
        """
{
  "run": {"run_id": "abc", "experiment_id": "1"},
  "data": {
    "bars_path": "data/bars.parquet",
    "start": "2022-01-01",
    "end": "2022-12-31",
    "rows": 4,
    "requested_symbols": 2,
    "symbols": 2,
    "missing_symbols": [],
    "benchmarks": ["hs300"]
  }
}
""".strip(),
        encoding="utf-8",
    )
    runtime_config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": "SH000300",
                "task": {
                    "dataset": {
                        "kwargs": {
                            "handler": {
                                "kwargs": {
                                    "filter_pipe": [
                                        {
                                            "filter_type": "ExpressionDFilter",
                                            "rule_expression": "$selected > 0.5",
                                        }
                                    ]
                                }
                            },
                            "segments": {
                                "train": ["2020-01-01", "2020-12-31"],
                                "valid": ["2021-01-01", "2021-12-31"],
                                "test": ["2022-01-01", "2022-12-31"],
                            },
                        }
                    },
                    "record": [
                        {
                            "class": "PortAnaRecord",
                            "kwargs": {
                                "config": {
                                    "strategy": {"kwargs": {"topk": 50, "n_drop": 10}},
                                    "backtest": {
                                        "account": 100000000,
                                        "exchange_kwargs": {
                                            "open_cost": 0.00031,
                                            "close_cost": 0.00081,
                                            "min_cost": 5.0,
                                            "limit_threshold": 0.095,
                                            "deal_price": "close",
                                        },
                                    },
                                }
                            },
                        }
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=2),
            "selected_universe_count": [2, 1],
            "configured_top_n": [0, 0],
        }
    ).to_csv(diagnostics_path, index=False)

    manifest = build_run_manifest(summary_path, runtime_config_path, diagnostics_path, symbols_file="symbols.txt")

    assert manifest["universe"]["dynamic_liquidity_top_n"] is None
    assert manifest["universe"]["selected_mode"] == "eligible_only"
    assert manifest["universe"]["selected_filter"] == "$selected > 0.5"
    assert manifest["universe"]["avg_selected_universe_count"] == 1.5
    assert manifest["universe"]["data_sufficient_for_dynamic_top_n"] is None


def test_run_manifest_marks_dynamic_top_n_without_extra_separator(tmp_path) -> None:
    summary_path = tmp_path / "summary.json"
    runtime_config_path = tmp_path / "runtime.yaml"
    diagnostics_path = tmp_path / "universe_diagnostics.csv"

    summary_path.write_text(
        """
{
  "run": {"run_id": "abc", "experiment_id": "1"},
  "data": {"requested_symbols": 1000, "symbols": 940, "missing_symbols": []}
}
""".strip(),
        encoding="utf-8",
    )
    runtime_config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": "SH000905",
                "task": {
                    "dataset": {
                        "kwargs": {
                            "segments": {
                                "train": ["2018-01-01", "2020-12-31"],
                                "valid": ["2021-01-01", "2021-12-31"],
                                "test": ["2022-01-01", "2022-12-31"],
                            }
                        }
                    },
                    "record": [],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=2),
            "selected_universe_count": [300, 299],
            "configured_top_n": [300, 300],
        }
    ).to_csv(diagnostics_path, index=False)

    manifest = build_run_manifest(summary_path, runtime_config_path, diagnostics_path)

    assert manifest["universe"]["selected_mode"] == "dynamic_liquidity_top300"
    assert "selected_mode=dynamic_liquidity_top300" in manifest["caveats"][1]


def test_dynamic_top_n_sufficiency_marks_underfilled_candidate_pool() -> None:
    assessment = assess_data_sufficiency(
        data={"requested_symbols": 1000, "symbols": 158},
        universe={
            "dynamic_liquidity_top_n": 300,
            "avg_selected_universe_count": 137.35,
            "min_selected_universe_count": 102,
            "max_selected_universe_count": 158,
        },
    )
    caveats = data_sufficiency_caveats(assessment)

    assert assessment["candidate_symbol_coverage"] == 0.158
    assert assessment["selected_top_n_reached"] is False
    assert assessment["data_sufficient_for_dynamic_top_n"] is False
    assert any("below 300" in caveat for caveat in caveats)


def test_rolling_config_yaml_and_log_parse() -> None:
    config = build_workflow_config(
        provider_uri="data/qlib_alpha158_hs300_full",
        market="all",
        benchmark="SH000300",
        window=ROLLING_WINDOWS[0],
        spec=MODEL_SPECS["alpha158_lgb"],
        topk=50,
        n_drop=10,
        account=100000000,
        open_cost=0.00031,
        close_cost=0.00081,
        min_cost=5.0,
        limit_threshold=0.095,
        num_threads=2,
    )
    loaded = yaml.safe_load(yaml.safe_dump(config, sort_keys=False))
    filter_pipe = loaded["task"]["dataset"]["kwargs"]["handler"]["kwargs"]["filter_pipe"]
    parsed = parse_qrun_log("Experiment 123 starts running\nRecorder abcdef123 starts running under Experiment 123")

    assert loaded["task"]["dataset"]["kwargs"]["segments"]["test"] == ["2022-01-01", "2022-12-31"]
    assert filter_pipe[0]["rule_expression"] == "$selected > 0.5"
    assert parsed == {"experiment_id": "123", "run_id": "abcdef123"}


def test_reversal_rolling_config_cleans_infinite_features() -> None:
    config = build_workflow_config(
        provider_uri="data/qlib_alpha158_hs300_full",
        market="all",
        benchmark="SH000300",
        window=ROLLING_WINDOWS[0],
        spec=MODEL_SPECS["reversal_lowvol_1d"],
        topk=50,
        n_drop=10,
        account=100000000,
        open_cost=0.00031,
        close_cost=0.00081,
        min_cost=5.0,
        limit_threshold=0.095,
        num_threads=2,
    )
    handler = config["task"]["dataset"]["kwargs"]["handler"]["kwargs"]

    assert handler["infer_processors"][0]["class"] == "ProcessInf"
    assert handler["learn_processors"][0]["class"] == "ProcessInf"
    assert handler["learn_processors"][1]["kwargs"]["fields_group"] == "feature"


def test_rolling_config_can_use_ashare_exchange() -> None:
    config = build_workflow_config(
        provider_uri="data/qlib_alpha158_hs300_full",
        market="all",
        benchmark="SH000300",
        window=ROLLING_WINDOWS[0],
        spec=MODEL_SPECS["alpha158_lgb"],
        topk=50,
        n_drop=10,
        account=100000000,
        open_cost=0.00031,
        close_cost=0.00081,
        min_cost=5.0,
        limit_threshold=0.095,
        num_threads=2,
        use_ashare_exchange=True,
        limit_price_buffer=0.002,
    )
    exchange = config["task"]["record"][2]["kwargs"]["config"]["backtest"]["exchange_kwargs"]["exchange"]

    assert exchange["class"] == "AShareExchange"
    assert exchange["module_path"] == "ashare_adapter.exchange"
    assert exchange["kwargs"]["limit_price_buffer"] == 0.002


def test_rolling_config_can_use_periodic_rebalance() -> None:
    config = build_workflow_config(
        provider_uri="data/qlib_alpha158_hs300_full",
        market="all",
        benchmark="SH000300",
        window=ROLLING_WINDOWS[0],
        spec=MODEL_SPECS["alpha158_lgb"],
        topk=50,
        n_drop=10,
        account=100000000,
        open_cost=0.00031,
        close_cost=0.00081,
        min_cost=5.0,
        limit_threshold=0.095,
        num_threads=2,
        rebalance_step=5,
    )
    strategy = config["task"]["record"][2]["kwargs"]["config"]["strategy"]

    assert strategy["class"] == "PeriodicTopkDropoutStrategy"
    assert strategy["module_path"] == "ashare_adapter.strategy"
    assert strategy["kwargs"]["rebalance_step"] == 5


def test_run_manifest_reads_nested_ashare_exchange_costs(tmp_path) -> None:
    summary_path = tmp_path / "summary.json"
    runtime_config_path = tmp_path / "runtime.yaml"
    diagnostics_path = tmp_path / "universe_diagnostics.csv"
    summary_path.write_text(
        """
{
  "run": {"run_id": "abc", "experiment_id": "1"},
  "data": {
    "data_type": "real_akshare",
    "synthetic_data": false,
    "mock_data": false,
    "requested_symbols": 2,
    "symbols": 2,
    "missing_symbols": []
  }
}
""".strip(),
        encoding="utf-8",
    )
    runtime_config_path.write_text(
        yaml.safe_dump(
            {
                "benchmark": "SH000905",
                "task": {
                    "dataset": {
                        "kwargs": {
                            "handler": {"kwargs": {}},
                            "segments": {"train": ["2018", "2020"], "valid": ["2021", "2021"], "test": ["2022", "2022"]},
                        }
                    },
                    "record": [
                        {
                            "class": "PortAnaRecord",
                            "kwargs": {
                                "config": {
                                    "strategy": {"kwargs": {"topk": 50, "n_drop": 10, "rebalance_step": 5}},
                                    "backtest": {
                                        "account": 100000000,
                                        "exchange_kwargs": {
                                            "exchange": {
                                                "class": "AShareExchange",
                                                "kwargs": {
                                                    "open_cost": 0.00031,
                                                    "close_cost": 0.00081,
                                                    "min_cost": 5,
                                                    "limit_threshold": 0.095,
                                                    "limit_price_buffer": 0.001,
                                                    "deal_price": "close",
                                                },
                                            }
                                        },
                                    },
                                }
                            },
                        }
                    ],
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    pd.DataFrame({"date": pd.date_range("2022-01-01", periods=2), "selected_universe_count": [2, 2]}).to_csv(
        diagnostics_path, index=False
    )

    manifest = build_run_manifest(summary_path, runtime_config_path, diagnostics_path)

    assert manifest["portfolio"]["exchange_mode"] == "ashare_exchange"
    assert manifest["portfolio"]["cost"]["open_cost"] == 0.00031
    assert manifest["portfolio"]["rebalance_step"] == 5
    assert manifest["portfolio"]["limit_model"] == "ashare_exchange_limit_up_down_buffer_0.001"


def test_rolling_stability_marks_recent_weakness() -> None:
    rows = pd.DataFrame(
        {
            "data_type": ["real_akshare"] * 3,
            "synthetic_data": [False] * 3,
            "mock_data": [False] * 3,
            "download_source": ["akshare"] * 3,
            "universe_name": ["dynamic_candidate1000_top300_2018_2026"] * 3,
            "model": ["Alpha158 + LightGBM"] * 3,
            "model_key": ["alpha158_lgb"] * 3,
            "is_ytd": [False, False, True],
            "excess_annualized_return_with_cost": [0.1, 0.2, -0.01],
            "excess_information_ratio_with_cost": [1.0, 2.0, -0.1],
            "excess_max_drawdown_with_cost": [-0.1, -0.05, -0.02],
            "data_quality_status": ["passed"] * 3,
            "industry_quality_status": ["passed"] * 3,
        }
    )

    summary = summarize_stability(rows)

    assert summary.loc[0, "positive_excess_windows"] == 2
    assert summary.loc[0, "conclusion_tag"] == "mostly_positive_but_recent_weakness"


def test_rolling_2018_2026_windows_mark_ytd() -> None:
    assert len(ROLLING_WINDOWS_2018_2026) == 5
    assert ROLLING_WINDOWS_2018_2026[-1]["name"] == "2022_2026_ytd"
    assert ROLLING_WINDOWS_2018_2026[-1]["is_ytd"] is True


def test_rolling_2018_2026_comparison_merge_keeps_other_universes(tmp_path) -> None:
    path = tmp_path / "rolling.csv"
    pd.DataFrame(
        [
            {
                "universe_name": "hs300_current_2018_2026",
                "model_key": "alpha158_lgb",
                "benchmark": "SH000300",
                "train_start": "2018-01-01",
                "train_end": "2020-12-31",
                "valid_start": "2021-01-01",
                "valid_end": "2021-12-31",
                "test_start": "2022-01-01",
                "test_end": "2022-12-31",
                "IC": 0.1,
            }
        ]
    ).to_csv(path, index=False)

    merged = _merge_comparison(
        path,
        [
            {
                "universe_name": "csi800_current_2018_2026",
                "model_key": "alpha158_lgb",
                "benchmark": "SH000905",
                "train_start": "2018-01-01",
                "train_end": "2020-12-31",
                "valid_start": "2021-01-01",
                "valid_end": "2021-12-31",
                "test_start": "2022-01-01",
                "test_end": "2022-12-31",
                "IC": 0.2,
            }
        ],
    )

    assert set(merged["universe_name"]) == {"hs300_current_2018_2026", "csi800_current_2018_2026"}
    assert {"beta_hs300", "beta_csi500", "beta_csi1000", "industry_unknown_weight"}.issubset(merged.columns)


def test_rolling_2018_2026_caveats_mark_only_ytd_window() -> None:
    args = SimpleNamespace(universe_mode="current_constituent", selected_mode="eligible_only", limit_threshold=0.095)

    first = _caveats(args, ROLLING_WINDOWS_2018_2026[0])
    last = _caveats(args, ROLLING_WINDOWS_2018_2026[-1])

    assert "complete_calendar_test_window" in first
    assert "2026_ytd_window" not in first
    assert "2026_ytd_window" in last


def test_build_expanded_universe_from_current_listed_metadata(tmp_path) -> None:
    metadata_path = tmp_path / "metadata.parquet"
    pd.DataFrame(
        {
            "symbol": ["000001.SZ", "000002.SZ", "000003.SZ"],
            "name": ["a", "b", "c"],
            "is_st": [False, True, False],
            "industry": ["bank", "tech", "energy"],
            "list_date": pd.to_datetime(["1991-01-01", "1992-01-01", "1993-01-01"]),
        }
    ).to_parquet(metadata_path, index=False)

    meta = build_universe(
        "dynamic_candidate2_top1_2018_2026",
        output_dir=tmp_path / "universes",
        metadata_cache=metadata_path,
        candidate_pool_size=2,
    )
    symbols = (tmp_path / "universes" / "dynamic_candidate2_top1_2018_2026_symbols.txt").read_text(encoding="utf-8").splitlines()

    assert meta["universe_mode"] == "current_listed_candidate"
    assert symbols == ["000001.SZ", "000003.SZ"]


def test_active_exposure_smoke() -> None:
    positions = _make_positions()
    benchmarks = _make_benchmarks()
    holdings = active_holdings(positions, ["000001.SZ", "000002.SZ"])
    up_down = up_down_market_performance(_make_equity(), benchmarks)

    assert {"portfolio_weight", "benchmark_weight", "active_weight"}.issubset(holdings.columns)
    assert not up_down.empty


def test_metadata_sidecar_writes_industry_and_list_date(tmp_path) -> None:
    metadata = pd.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "name": ["平安银行"],
            "is_st": [False],
            "list_date": [pd.Timestamp("1991-04-03")],
            "industry": ["bank"],
            "industry_source": ["unit_test"],
            "industry_update_date": [pd.Timestamp("2024-01-02")],
        }
    )

    path = write_metadata_sidecar(metadata, tmp_path)
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)

    assert frame.loc[0, "qlib_symbol"] == "SZ000001"
    assert frame.loc[0, "industry"] == "bank"
    assert frame.loc[0, "industry_source"] == "unit_test"
    assert pd.Timestamp(frame.loc[0, "industry_update_date"]).date().isoformat() == "2024-01-02"
    assert pd.Timestamp(frame.loc[0, "list_date"]).date().isoformat() == "1991-04-03"


def test_industry_metadata_merge_and_coverage() -> None:
    metadata = pd.DataFrame(
        {
            "symbol": ["600000.SH", "000001.SZ"],
            "industry": ["", "bank"],
        }
    )
    industry_map = pd.DataFrame(
        {
            "symbol": ["600000.SH", "000001.SZ"],
            "industry": ["bank", "finance"],
            "industry_source": ["cninfo", "cninfo"],
            "industry_update_date": [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")],
        }
    )

    merged = merge_industry_map(metadata, industry_map, overwrite=False)
    coverage = industry_coverage(merged)

    assert merged.loc[merged["symbol"] == "600000.SH", "industry"].iloc[0] == "bank"
    assert merged.loc[merged["symbol"] == "600000.SH", "industry_source"].iloc[0] == "cninfo"
    assert merged.loc[merged["symbol"] == "000001.SZ", "industry"].iloc[0] == "bank"
    assert coverage["industry_nonempty"] == 2


def test_industry_unknown_reports() -> None:
    bars = _make_bars(symbol_count=2, periods=3)
    bars.loc[bars["symbol"] == "000002.SZ", "industry"] = ""
    bars["selected"] = True
    positions = pd.DataFrame(
        {
            "date": [bars["date"].min(), bars["date"].min()],
            "symbol": ["000001.SZ", "000002.SZ"],
            "weight": [0.4, 0.6],
        }
    )

    by_date = industry_unknown_by_date(bars)
    by_position = industry_unknown_by_position(positions, bars)

    assert by_date["unknown_selected_ratio"].iloc[0] == 0.5
    assert by_position["unknown_weight_ratio"].iloc[0] == 0.6


def test_parse_cninfo_industry_uses_latest_detailed_value() -> None:
    raw = pd.DataFrame(
        [
            ["old_short", "old_l1", "old_l2", "old_l3", "old_l4", "name", "code", "standard", "sid", "600000", "2020-01-01"],
            ["new_short", "new_l1", "new_l2", "new_l3", "new_l4", "name", "code", "standard", "sid", "600000", "2024-01-01"],
        ]
    )

    assert parse_cninfo_industry(raw) == "new_l4"


def _make_bars(symbol_count: int = 5, periods: int = 10) -> pd.DataFrame:
    dates = pd.date_range("2022-01-01", periods=periods, freq="D")
    rows = []
    for symbol_idx in range(1, symbol_count + 1):
        symbol = f"{symbol_idx:06d}.SZ"
        for day_idx, date in enumerate(dates):
            close = 10 + symbol_idx + day_idx * 0.1
            amount = symbol_idx * 1_000_000 + day_idx * 1000
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close - 0.1,
                    "high": close + 0.2,
                    "low": close - 0.2,
                    "close": close,
                    "volume": 10000 + symbol_idx,
                    "amount": amount,
                    "factor": 1.0,
                    "is_paused": False,
                    "is_st": False,
                    "limit_up": close * 1.1,
                    "limit_down": close * 0.9,
                    "list_date": pd.Timestamp("2021-01-01"),
                    "industry": "bank" if symbol_idx % 2 else "tech",
                }
            )
    return validate_bars(pd.DataFrame(rows))


def _make_positions() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.to_datetime(["2022-01-01", "2022-01-01", "2022-01-02", "2022-01-02"]),
            "symbol": ["000001.SZ", "000002.SZ", "000001.SZ", "000002.SZ"],
            "weight": [0.5, 0.5, 0.2, 0.8],
        }
    )


def _make_equity() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2022-01-01", periods=6, freq="D"),
            "equity": [1.0, 1.01, 1.0, 1.03, 1.04, 1.02],
        }
    )


def _make_benchmarks() -> pd.DataFrame:
    dates = pd.date_range("2022-01-01", periods=5, freq="D")
    close = pd.Series([4000, 4010, 4020, 4015, 4030], dtype=float)
    returns = close.pct_change().fillna(0.0)
    return pd.DataFrame(
        {
            "date": dates,
            "benchmark": "hs300",
            "benchmark_name": "HS300",
            "source": "synthetic",
            "close": close,
            "return": returns,
            "equity": (1.0 + returns).cumprod(),
        }
    )
