# Qlib A-share Research Project

This repository is now a clean Qlib-based A-share research scaffold. The old
custom `a_share_quant` backtest engine and research pipeline have been removed;
only the useful A-share data adapter, filter, benchmark, cost, and diagnostics
ideas were migrated.

## Scope

- AKShare daily bar download and metadata enrichment.
- A-share symbol normalization for `600000.SH`, `SH600000`, `sh600000`, and
  plain six-digit codes.
- ST, paused, limit-up/limit-down, listing-age, amount, and dynamic liquidity
  filters.
- AKShare index benchmarks for HS300, CSI500, and CSI1000.
- Qlib-compatible CSV and binary data dump.
- Qlib baseline configs for Alpha158 + LightGBM and reversal + low volatility.
- Lightweight diagnostics for IC, Rank IC, factor groups, benchmark comparison,
  turnover, max drawdown, and out-of-sample splits.

## Layout

```text
configs/
  qlib_alpha158_lgb.yaml
  qlib_reversal_lowvol.yaml
scripts/
  prepare_akshare_data.py
  dump_qlib_data.py
  fetch_benchmarks.py
  run_alpha158_pipeline.py
  run_qlib_workflow.py
  export_alpha158_results.py
  export_qlib_records.py
  apply_signal_mask.py
  run_diagnostics.py
ashare_adapter/
  akshare_downloader.py
  benchmarks.py
  config.py
  cost.py
  diagnostics.py
  factors.py
  filters.py
  metadata.py
  qlib_converter.py
  signal_mask.py
  universe.py
tests/
data/
reports/
```

## Install

For adapter and smoke tests:

```powershell
python -m pip install -e .[test]
```

For live data and full Qlib workflows:

```powershell
python -m pip install -e .[data,qlib,test]
```

The intended runtime is the existing conda environment `ql`.

## Minimal Flow

Prepare AKShare bars:

```powershell
python scripts/prepare_akshare_data.py `
  --symbols 600000.SH 000001.SZ `
  --start-date 2022-01-01 `
  --end-date 2023-12-31 `
  --output data/ashare_bars.parquet
```

Dump Qlib data:

```powershell
python scripts/dump_qlib_data.py `
  --input data/ashare_bars.parquet `
  --qlib-dir data/qlib_cn_ashare `
  --market all
```

Fetch benchmark series and add them to the same Qlib directory:

```powershell
python scripts/fetch_benchmarks.py `
  --start-date 2022-01-01 `
  --end-date 2023-12-31 `
  --output data/benchmarks.parquet `
  --qlib-dir data/qlib_cn_ashare
```

Run the Qlib Alpha158 baseline after Qlib is installed:

```powershell
python scripts/run_qlib_workflow.py --config configs/qlib_alpha158_lgb.yaml
```

Run local diagnostics from a score file:

```powershell
python scripts/run_diagnostics.py `
  --bars data/ashare_bars.parquet `
  --scores reports/predictions.csv `
  --output-dir reports
```

Run the integrated Alpha158 pipeline:

```powershell
python scripts/run_alpha158_pipeline.py `
  --symbols-file data/cache/hs300_symbols_full.txt `
  --max-symbols 300 `
  --start-date 2018-01-01 `
  --end-date 2024-12-31 `
  --benchmark-key hs300 `
  --output-dir reports/alpha158_hs300_full
```

Export a completed Qlib recorder and run local diagnostics:

```powershell
python scripts/export_qlib_records.py `
  --run-dir mlruns/<experiment_id>/<run_id> `
  --bars data/alpha158_hs300_full_bars.parquet `
  --benchmarks data/benchmarks.parquet `
  --output-dir reports/alpha158_hs300_full/qlib_records `
  --apply-mask `
  --run-diagnostics
```

## A-share Data Notes

Qlib binary features are numeric.  The converter writes numeric fields such as
`open`, `high`, `low`, `close`, `volume`, `amount`, `factor`, `is_st`,
`is_paused`, `limit_up`, `limit_down`, `listed_days`, `avg_amount`,
`eligible`, and `selected`.
Non-numeric metadata such as `industry` and original `list_date` are preserved
under `metadata/instruments.parquet` or `metadata/instruments.csv`.

The universe filters are backward-looking.  Dynamic liquidity uses rolling
average amount computed per symbol up to the current date, then selects the
top-N eligible names cross-sectionally on that same signal date.

The Qlib configs and generated runtime configs use `ExpressionDFilter` with
`$selected > 0.5`, so the dynamic A-share universe is applied during dataset
loading.  `apply_signal_mask.py` and `export_qlib_records.py --apply-mask`
provide a second diagnostics-layer check by masking any non-selected prediction
scores to `NaN`.

Current Qlib backtests still use Qlib's simplified `limit_threshold` exchange
setting.  The per-stock `limit_up`/`limit_down` fields are written into Qlib
data for later custom exchange or order-filter work, but they are not yet a
full replacement for A-share board-specific trading constraints.

## References

- Qlib official Alpha158 + LightGBM workflow pattern:
  https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
- Qlib official CSV-to-bin format implementation:
  https://github.com/microsoft/qlib/blob/main/scripts/dump_bin.py
