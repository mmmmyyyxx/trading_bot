from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from ashare_quant.config import AppConfig
from ashare_quant.data.base import ProviderUnavailable
from ashare_quant.data.storage import SQLiteStorage
from ashare_quant.data.universe import add_universe_flags, build_universe_diagnostics, select_universe_on
from ashare_quant.pipeline import (
    _fetch_akshare_metadata_symbols,
    _fetch_bars_in_batches,
    _load_candidate_symbols_file,
    _symbols_from_metadata_frame,
    load_market_data,
)
from ashare_quant.research.walk_forward_selection import run_walk_forward_selection
from ashare_quant.research.strategy_compare import _evaluation_fields
from ashare_quant.strategy.profiles import get_strategy_profile
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


def _minimal_bars(symbols: list[str], date: str = "2025-01-02") -> pd.DataFrame:
    rows = []
    for index, symbol in enumerate(symbols):
        close = 10.0 + index
        rows.append(
            {
                "date": date,
                "symbol": symbol,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": 1000,
                "amount": 100000000.0,
                "adj_factor": 1.0,
                "is_paused": False,
                "is_st": False,
                "limit_up": close * 1.1,
                "limit_down": close * 0.9,
            }
        )
    return pd.DataFrame(rows)


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
    for strategy_name in ["reversal_low_vol", "defensive_low_vol", "offensive_momentum", "balanced_multi_factor"]:
        config = _loose_config()
        config.strategy.name = strategy_name
        targets = MultiFactorRotationStrategy(config).generate_targets(bars)
        assert not targets.empty
        assert targets["target_weight"].max() <= config.strategy.max_weight


def test_strategy_profile_defaults_are_balanced_and_no_liquidity_alpha() -> None:
    config = _loose_config()

    assert config.strategy.name == "reversal_low_vol"
    assert get_strategy_profile("reversal_low_vol").factor_weights["short_term_reversal"] == 0.50
    assert get_strategy_profile("reversal_low_vol").factor_weights["volatility"] == 0.30
    assert get_strategy_profile("offensive_momentum").factor_weights["liquidity"] == 0.0
    assert get_strategy_profile("offensive_momentum").factor_weights["industry_momentum"] == 0.80


def test_strategy_evaluation_fields_split_defensive_and_return_seeking() -> None:
    defensive = _evaluation_fields(
        "defensive_low_vol",
        {"max_drawdown": -0.10, "calmar": 0.5},
        {"beta": 0.5, "down_capture": 0.7},
    )
    balanced = _evaluation_fields(
        "balanced_multi_factor",
        {},
        {"excess_return": 0.02, "information_ratio": 0.3, "monthly_win_rate_vs_benchmark": 0.6},
    )

    assert defensive["evaluation_class"] == "defensive"
    assert defensive["acceptance_pass"] is True
    assert balanced["evaluation_class"] == "return_seeking"
    assert balanced["acceptance_pass"] is True


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


def test_candidate_symbols_file_respects_max_symbols(tmp_path) -> None:
    config = AppConfig()
    config.data.max_symbols = 2
    path = tmp_path / "candidate_symbols.txt"
    path.write_text("000001.SZ\n600000.SH\n688001.SH\n", encoding="utf-8")

    symbols = _load_candidate_symbols_file(path, config)

    assert symbols == ["000001.SZ", "600000.SH"]


def test_storage_load_bars_supports_column_projection(tmp_path) -> None:
    cache_path = tmp_path / "bars.sqlite"
    SQLiteStorage(cache_path).save_bars(_minimal_bars(["000001.SZ", "000002.SZ"]))

    bars = SQLiteStorage(cache_path).load_bars(columns=["date", "symbol", "close"], validate=False)

    assert list(bars.columns) == ["date", "symbol", "close"]
    assert set(bars["symbol"]) == {"000001.SZ", "000002.SZ"}


def test_akshare_metadata_refresh_rebuilds_stale_candidate_file(monkeypatch, tmp_path) -> None:
    config = AppConfig()
    config.data.max_symbols = 3
    config.data.candidate_symbols_path = str(tmp_path / "candidate_symbols.txt")
    stale_path = tmp_path / "candidate_symbols.txt"
    stale_path.write_text("000001.SZ\n", encoding="utf-8")
    fake_akshare = SimpleNamespace(
        stock_info_a_code_name=lambda: pd.DataFrame(
            {
                "code": ["600000", "000002", "300001", "688001"],
                "name": ["浦发银行", "万科A", "ST测试", "华兴源创"],
            }
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)

    symbols = _fetch_akshare_metadata_symbols(config, refresh=True)

    assert symbols == ["000002.SZ", "600000.SH", "688001.SH"]
    assert stale_path.read_text(encoding="utf-8").splitlines() == symbols


def test_fetch_bars_in_batches_skips_failed_batches() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def fetch_bars(self, symbols, start_date, end_date, adjust="qfq"):
            batch = list(symbols)
            self.calls.append(batch)
            if batch[0] == "000003.SZ":
                raise ProviderUnavailable("batch failed")
            return _minimal_bars(batch)

    provider = FakeProvider()
    symbols = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ", "000005.SZ"]

    bars = _fetch_bars_in_batches(provider, symbols, "2025-01-01", "2025-01-31", "qfq", batch_size=2)

    assert provider.calls == [["000001.SZ", "000002.SZ"], ["000003.SZ", "000004.SZ"], ["000005.SZ"]]
    assert set(bars["symbol"]) == {"000001.SZ", "000002.SZ", "000005.SZ"}


def test_fetch_bars_in_batches_supports_parallel_workers() -> None:
    class FakeProvider:
        def fetch_bars(self, symbols, start_date, end_date, adjust="qfq"):
            return _minimal_bars(list(symbols))

    symbols = ["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"]

    bars = _fetch_bars_in_batches(
        FakeProvider(),
        symbols,
        "2025-01-01",
        "2025-01-31",
        "qfq",
        batch_size=1,
        workers=2,
    )

    assert set(bars["symbol"]) == set(symbols)


def test_fetch_bars_in_batches_uses_symbol_level_parallel_when_available() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.parallel_calls: list[list[str]] = []

        def fetch_bars(self, symbols, start_date, end_date, adjust="qfq"):
            raise AssertionError("batch fetch should not be used")

        def fetch_bars_parallel(self, symbols, start_date, end_date, adjust="qfq", max_workers=1, retry=0, sleep=0.0):
            self.parallel_calls.append(list(symbols))
            return _minimal_bars(list(symbols))

    provider = FakeProvider()
    symbols = ["000001.SZ", "000002.SZ", "000003.SZ"]

    bars = _fetch_bars_in_batches(
        provider,
        symbols,
        "2025-01-01",
        "2025-01-31",
        "qfq",
        batch_size=100,
        workers=2,
    )

    assert provider.parallel_calls == [symbols]
    assert set(bars["symbol"]) == set(symbols)


def test_non_refresh_large_candidate_file_uses_existing_full_cache(tmp_path) -> None:
    cache_path = tmp_path / "bars.sqlite"
    SQLiteStorage(cache_path).save_bars(_minimal_bars(["000001.SZ", "300001.SZ"]))
    candidate_path = tmp_path / "candidate_symbols.txt"
    candidate_path.write_text("000001.SZ\n000002.SZ\n000003.SZ\n", encoding="utf-8")
    config = AppConfig()
    config.data.provider = "tushare"
    config.data.universe_type = "all_a_share_liquid"
    config.data.universe_mode = "dynamic_liquidity"
    config.data.candidate_source = "akshare_metadata"
    config.data.candidate_symbols_path = str(candidate_path)
    config.data.cache_path = str(cache_path)
    config.data.start_date = "2025-01-01"
    config.data.end_date = "2025-01-31"
    config.data.max_symbols = 3

    bars = load_market_data(config, refresh=False)

    assert set(bars["symbol"]) == {"000001.SZ", "300001.SZ"}
