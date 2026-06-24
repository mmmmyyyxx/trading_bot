from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from ashare_quant.config import AppConfig, FactorConfig
from ashare_quant.data.akshare_provider import AKShareProvider
from ashare_quant.data.universe import add_universe_flags
from ashare_quant.factors.composite import industry_neutral_momentum_factor
from ashare_quant.pipeline import _symbols_from_akshare_spot
from ashare_quant.research.pipeline import _industry_momentum_fallback_rate
from ashare_quant.research.walk_forward import run_walk_forward
from ashare_quant.strategy.multi_factor_rotation import MultiFactorRotationStrategy


def _rows(symbols: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    for symbol_index, symbol in enumerate(symbols):
        for day_index, date in enumerate(dates):
            close = 10.0 + symbol_index + day_index * (0.02 + symbol_index * 0.005)
            rows.append(
                {
                    "date": date,
                    "symbol": symbol,
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 100000 + day_index,
                    "amount": 100000000.0 + symbol_index * 1000000,
                    "adj_factor": 1.0,
                    "is_paused": False,
                    "is_st": False,
                    "limit_up": close * 1.1,
                    "limit_down": close * 0.9,
                    "list_date": pd.Timestamp("2020-01-01"),
                    "list_date_fallback": False,
                    "industry": "IndustryA" if symbol_index < 2 else "IndustryB",
                    "industry_fallback": False,
                }
            )
    return pd.DataFrame(rows)


def test_akshare_enrichment_recomputes_constraints_and_metadata() -> None:
    provider = AKShareProvider.__new__(AKShareProvider)
    provider._metadata = {
        "000001.SZ": {
            "is_st": False,
            "industry": "Bank",
            "list_date": pd.Timestamp("1991-04-03"),
        },
        "000002.SZ": {
            "is_st": True,
            "industry": "RealEstate",
            "list_date": pd.Timestamp("1991-01-29"),
        },
    }
    bars = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "symbol": "000001.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 1000,
                "is_st": False,
                "is_paused": False,
                "limit_up": 999,
                "limit_down": 0,
            },
            {
                "date": "2025-01-02",
                "symbol": "000002.SZ",
                "open": 20,
                "high": 21,
                "low": 19,
                "close": 20,
                "volume": 0,
                "amount": 0,
                "is_st": False,
                "is_paused": False,
                "limit_up": 999,
                "limit_down": 0,
            },
        ]
    )

    enriched = provider.enrich_bars(bars)
    first = enriched.set_index("symbol").loc["000001.SZ"]
    st_stock = enriched.set_index("symbol").loc["000002.SZ"]

    assert first["industry"] == "Bank"
    assert first["list_date"] == pd.Timestamp("1991-04-03")
    assert first["limit_up"] == 11.0
    assert st_stock["is_st"]
    assert st_stock["is_paused"]
    assert st_stock["limit_up"] == 21.0


def test_listed_days_uses_list_date_and_st_is_filtered() -> None:
    bars = pd.DataFrame(
        [
            {
                "date": "2025-01-02",
                "symbol": "000001.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 100000000,
                "adj_factor": 1.0,
                "is_paused": False,
                "is_st": False,
                "limit_up": 11,
                "limit_down": 9,
                "list_date": "2020-01-01",
                "list_date_fallback": False,
            },
            {
                "date": "2025-01-02",
                "symbol": "000002.SZ",
                "open": 10,
                "high": 11,
                "low": 9,
                "close": 10,
                "volume": 100,
                "amount": 100000000,
                "adj_factor": 1.0,
                "is_paused": False,
                "is_st": True,
                "limit_up": 10.5,
                "limit_down": 9.5,
                "list_date": "2020-01-01",
                "list_date_fallback": False,
            },
        ]
    )

    enriched = add_universe_flags(bars, min_listed_days=252, min_amount=1, liquidity_window=1)
    by_symbol = enriched.set_index("symbol")

    assert by_symbol.loc["000001.SZ", "listed_days"] > 1800
    assert not by_symbol.loc["000001.SZ", "listed_days_fallback"]
    assert by_symbol.loc["000001.SZ", "eligible"]
    assert not by_symbol.loc["000002.SZ", "eligible"]


def test_spot_universe_uses_amount_ranking(monkeypatch) -> None:
    fake_akshare = SimpleNamespace(
        stock_zh_a_spot_em=lambda: pd.DataFrame(
            {
                "\u4ee3\u7801": ["000001", "000002", "600000"],
                "\u540d\u79f0": ["A", "B", "C"],
                "\u6210\u4ea4\u989d": [1.0, 3.0, 2.0],
            }
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake_akshare)
    config = AppConfig()
    config.data.max_symbols = 2

    assert _symbols_from_akshare_spot(config) == ["000002.SZ", "600000.SH"]


def test_market_filter_uses_benchmark_not_stock_price_average(monkeypatch) -> None:
    config = AppConfig()
    config.risk.market_filter = True
    config.risk.market_filter_benchmark = "csi500"
    config.risk.market_filter_window = 3
    config.risk.defensive_exposure = 0.5
    dates = pd.to_datetime(["2025-01-01", "2025-01-02", "2025-01-03"])
    bars = _rows(["000001.SZ", "000002.SZ"], pd.DatetimeIndex(dates))
    bars.loc[bars["date"] == dates[-1], "close"] = 100.0

    benchmark = pd.DataFrame(
        {
            "date": dates,
            "benchmark": "csi500",
            "benchmark_name": "CSI500",
            "source": "akshare",
            "close": [100.0, 90.0, 80.0],
            "return": [0.0, -0.1, -0.111111],
            "equity": [1.0, 0.9, 0.8],
        }
    )
    monkeypatch.setattr("ashare_quant.strategy.multi_factor_rotation.load_benchmarks", lambda config, bars: benchmark)

    weights = pd.DataFrame({"symbol": ["000001.SZ"], "target_weight": [1.0]})
    filtered = MultiFactorRotationStrategy(config)._apply_market_filter(weights, bars, dates[-1])

    assert filtered["target_weight"].iloc[0] == 0.5


def test_industry_momentum_fallback_rate_is_reported() -> None:
    dates = pd.bdate_range("2025-01-01", periods=5)
    bars = _rows(["000001.SZ", "000002.SZ", "000003.SZ"], dates)
    bars.loc[bars["symbol"] == "000003.SZ", "industry"] = ""
    factor = industry_neutral_momentum_factor(bars, FactorConfig(momentum_window=2, momentum_skip=0))

    rate = _industry_momentum_fallback_rate(factor)

    assert 0.0 < rate < 1.0


def test_walk_forward_outputs_nonempty_ir(monkeypatch) -> None:
    dates = pd.bdate_range("2025-01-01", periods=90)
    bars = _rows(["000001.SZ", "000002.SZ", "000003.SZ", "000004.SZ"], dates)
    benchmark_return = pd.Series(0.0002, index=dates)
    benchmark = pd.DataFrame(
        {
            "date": dates,
            "benchmark": "hs300",
            "benchmark_name": "HS300",
            "source": "akshare",
            "close": (1.0 + benchmark_return).cumprod() * 1000,
            "return": benchmark_return.values,
            "equity": (1.0 + benchmark_return).cumprod().values,
        }
    )
    monkeypatch.setattr("ashare_quant.research.walk_forward.load_benchmarks", lambda config, bars: benchmark)

    config = AppConfig()
    config.data.min_listed_days = 1
    config.data.min_amount = 1
    config.data.liquidity_top_pct = None
    config.factors.momentum_window = 5
    config.factors.momentum_skip = 1
    config.factors.trend_window = 5
    config.factors.volatility_window = 5
    config.strategy.top_k = 2
    config.strategy.max_weight = 0.5
    config.strategy.rebalance_frequency = "M"
    config.strategy.weighting = "equal_weight"
    config.backtest.lot_size = 1
    config.risk.market_filter = False

    result = run_walk_forward(config, bars, train_months=[1], test_months=[1])

    assert not result.empty
    assert "oos_information_ratio" in result.columns
    assert result["oos_information_ratio"].notna().any()
