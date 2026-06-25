from __future__ import annotations

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.data.universe import add_universe_flags, build_universe_diagnostics, select_universe_on
from ashare_quant.pipeline import _symbols_from_metadata_frame
from ashare_quant.research.walk_forward_selection import run_walk_forward_selection
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy
from tests.real_data import load_real_cached_bars


def _loose_config() -> AppConfig:
    config = AppConfig()
    config.data.universe_mode = "dynamic_liquidity"
    config.data.universe_top_n = 10
    config.data.min_listed_days = 1
    config.data.universe_min_amount = 0.0
    config.strategy.top_k = 3
    config.strategy.max_weight = 0.3
    config.risk.market_filter = False
    return config


def test_dynamic_liquidity_universe_ignores_future_amount_edits() -> None:
    config = _loose_config()
    bars = load_real_cached_bars()
    dates = sorted(pd.to_datetime(bars["date"]).unique())
    cutoff = pd.Timestamp(dates[min(120, len(dates) // 2)])

    enriched = add_universe_flags(
        bars,
        min_listed_days=config.data.min_listed_days,
        min_amount=config.data.universe_min_amount,
        liquidity_window=5,
        liquidity_top_pct=None,
    )
    baseline = select_universe_on(enriched, cutoff, "dynamic_liquidity", top_n=10)[["symbol", "avg_amount"]].reset_index(drop=True)

    edited = bars.copy()
    edited.loc[pd.to_datetime(edited["date"]) > cutoff, "amount"] *= 1000.0
    changed = add_universe_flags(
        edited,
        min_listed_days=config.data.min_listed_days,
        min_amount=config.data.universe_min_amount,
        liquidity_window=5,
        liquidity_top_pct=None,
    )
    changed_universe = select_universe_on(changed, cutoff, "dynamic_liquidity", top_n=10)[["symbol", "avg_amount"]].reset_index(drop=True)

    pd.testing.assert_frame_equal(baseline, changed_universe)


def test_current_snapshot_marks_selection_bias() -> None:
    config = _loose_config()
    bars = load_real_cached_bars()
    signal_date = pd.Timestamp(sorted(pd.to_datetime(bars["date"]).unique())[120])
    enriched = add_universe_flags(
        bars,
        min_listed_days=config.data.min_listed_days,
        min_amount=config.data.universe_min_amount,
        liquidity_window=5,
        liquidity_top_pct=None,
    )

    current = build_universe_diagnostics(enriched, [signal_date], "current_snapshot", top_n=10)
    dynamic = build_universe_diagnostics(enriched, [signal_date], "dynamic_liquidity", top_n=10)
    dynamic_snapshot_source = build_universe_diagnostics(
        enriched,
        [signal_date],
        "dynamic_liquidity",
        top_n=10,
        candidate_source="current_snapshot",
    )

    assert bool(current["possible_selection_bias"].iloc[0]) is True
    assert bool(dynamic["possible_selection_bias"].iloc[0]) is False
    assert bool(dynamic_snapshot_source["possible_selection_bias"].iloc[0]) is True


def test_universe_diagnostics_flag_candidate_pool_capacity() -> None:
    config = _loose_config()
    bars = load_real_cached_bars()
    signal_date = pd.Timestamp(sorted(pd.to_datetime(bars["date"]).unique())[120])
    enriched = add_universe_flags(
        bars,
        min_listed_days=config.data.min_listed_days,
        min_amount=config.data.universe_min_amount,
        liquidity_window=5,
        liquidity_top_pct=None,
    )

    diagnostics = build_universe_diagnostics(enriched, [signal_date], "dynamic_liquidity", top_n=10000)

    assert bool(diagnostics["candidate_pool_limited"].iloc[0]) is True
    assert diagnostics["raw_to_top_n_ratio"].iloc[0] < 1.0


def test_named_strategy_profiles_generate_targets() -> None:
    bars = load_real_cached_bars()
    for strategy_name in ["defensive_low_vol", "offensive_momentum", "balanced_multi_factor"]:
        config = _loose_config()
        config.strategy.name = strategy_name
        targets = MultiFactorRotationStrategy(config).generate_targets(bars)
        assert not targets.empty
        assert targets["target_weight"].max() <= config.strategy.max_weight


def test_walk_forward_selection_outputs_oos_rows() -> None:
    config = _loose_config()
    config.data.benchmark_symbol = "hs300"
    bars = load_real_cached_bars()

    result = run_walk_forward_selection(
        config,
        bars,
        train_months=6,
        test_months=3,
        strategy_names=["defensive_low_vol"],
        top_k_values=[3],
        weighting_values=["equal_weight"],
        rebalance_values=["M"],
        momentum_windows=[60],
        skip_windows=[5],
    )

    assert not result.empty
    assert {"selected_strategy", "test_total_return", "test_sharpe", "test_ir"}.issubset(result.columns)


def test_akshare_metadata_candidate_symbols_do_not_require_spot_amount() -> None:
    config = AppConfig()
    config.data.max_symbols = 3
    config.data.exclude_st = True
    raw = pd.DataFrame(
        {
            "code": ["600000", "000001", "300001", "688001"],
            "name": ["浦发银行", "平安银行", "ST测试", "华兴源创"],
        }
    )

    symbols = _symbols_from_metadata_frame(raw, config)

    assert symbols == ["000001.SZ", "600000.SH", "688001.SH"]
