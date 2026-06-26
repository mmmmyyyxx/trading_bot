from __future__ import annotations

import numpy as np
import pandas as pd

from ashare_adapter.akshare_downloader import validate_bars
from ashare_adapter.benchmarks import dump_benchmarks_to_qlib
from ashare_adapter.config import UniverseConfig
from ashare_adapter.diagnostics import compute_group_returns, compute_ic, compute_turnover, split_oos
from ashare_adapter.factors import reversal_lowvol_scores
from ashare_adapter.metadata import limit_rate, normalize_symbol, to_qlib_symbol, write_metadata_sidecar
from ashare_adapter.qlib_converter import dump_qlib_bin, prepare_qlib_frame
from ashare_adapter.signal_mask import apply_selected_mask, to_qlib_signal_frame
from ashare_adapter.universe import build_dynamic_universe, build_universe_diagnostics, selected_symbols_on


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
    kept = masked.loc[masked["symbol"] == "000001.SZ", "score"].iloc[0]
    blocked = masked.loc[masked["symbol"] == "000002.SZ", "score"].iloc[0]
    signal = to_qlib_signal_frame(masked)

    assert kept == 1.0
    assert pd.isna(blocked)
    assert signal.index.names == ["datetime", "instrument"]
    assert ("SZ000001" in signal.index.get_level_values("instrument"))


def test_metadata_sidecar_writes_industry_and_list_date(tmp_path) -> None:
    metadata = pd.DataFrame(
        {
            "symbol": ["000001.SZ"],
            "name": ["平安银行"],
            "is_st": [False],
            "list_date": [pd.Timestamp("1991-04-03")],
            "industry": ["bank"],
        }
    )

    path = write_metadata_sidecar(metadata, tmp_path)
    frame = pd.read_parquet(path) if path.suffix == ".parquet" else pd.read_csv(path)

    assert frame.loc[0, "qlib_symbol"] == "SZ000001"
    assert frame.loc[0, "industry"] == "bank"
    assert pd.Timestamp(frame.loc[0, "list_date"]).date().isoformat() == "1991-04-03"


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
