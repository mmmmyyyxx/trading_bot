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
  write_run_manifest.py
  enrich_industry_metadata.py
  run_data_quality_audit.py
  run_exposure_diagnostics.py
  run_rolling_baselines.py
  run_diagnostics.py
ashare_adapter/
  akshare_downloader.py
  benchmarks.py
  config.py
  cost.py
  data_quality.py
  diagnostics.py
  exchange.py
  exposure.py
  factors.py
  filters.py
  industry_metadata.py
  manifest.py
  metadata.py
  qlib_converter.py
  report_policy.py
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

## Real Data Policy

Formal research reports must use real AKShare data. Synthetic, mock, random, or
generated data is allowed only for unit tests and must write to temporary
directories or `reports/synthetic_test_only/`.

Real runs must include these manifest fields:

```json
{
  "data_type": "real_akshare",
  "synthetic_data": false,
  "mock_data": false,
  "download_source": "akshare"
}
```

If AKShare bar or benchmark download fails, the pipeline must stop instead of
falling back to synthetic data. Reports generated from synthetic data must not
be used for strategy conclusions and must not be written to formal report paths
such as `reports/alpha158_*/summary.*`,
`reports/universe_expansion_comparison.*`, or
`reports/rolling_baseline_comparison*`.

Run a real-data smoke test before larger universes. Use 10-20 liquid A-share
symbols, real HS300 benchmark data, and a short 2023-2024 window. If this fails,
fix the data or network issue before running HS300, CSI800, dynamic liquidity,
or rolling OOS experiments.

## Data Quality

Every formal real-data run audits bars before Qlib binary dump:

```powershell
python scripts/run_data_quality_audit.py `
  --bars data/hs300_current_2018_2026_bars.parquet `
  --output-dir reports/alpha158_hs300_2018_2026/data_quality `
  --fail-on-error
```

The audit writes `data_quality_summary.json`, source/date/symbol summaries,
selected-universe quality, duplicate rows, VWAP unit checks, limit coverage, and
pause/ST coverage. A failed audit blocks `run_universe_expansion.py` unless
`--allow-low-quality-data` is explicitly used for caveated diagnostics.

Industry metadata coverage is reported separately under each run's `industry/`
directory. If coverage is insufficient, summaries state that industry
attribution is not reliable.

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

Write a lightweight run manifest for a completed baseline:

```powershell
python scripts/write_run_manifest.py `
  --summary reports/alpha158_hs300_full/summary.json `
  --runtime-config reports/alpha158_hs300_full/alpha158_lgb_runtime.yaml `
  --universe-diagnostics reports/alpha158_hs300_full/universe_diagnostics.csv `
  --symbols-file data/cache/hs300_symbols_full.txt `
  --output reports/run_manifest.json
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

Run exposure diagnostics from exported Qlib records:

```powershell
python scripts/run_exposure_diagnostics.py `
  --bars data/alpha158_hs300_full_bars.parquet `
  --equity reports/alpha158_hs300_full/qlib_records/equity.csv `
  --positions reports/alpha158_hs300_full/qlib_records/positions.csv `
  --benchmarks data/benchmarks.parquet `
  --benchmark-symbols-file data/cache/hs300_symbols_full.txt `
  --output-dir reports/alpha158_hs300_full/exposure
```

Enrich industry metadata for existing caches and bars:

```powershell
python scripts/enrich_industry_metadata.py `
  --metadata-cache data/cache/akshare_metadata.parquet `
  --bars data/csi800_current_2018_2026_bars.parquet `
  --qlib-dir data/qlib_csi800_2018_2026 `
  --refresh-cninfo `
  --workers 1
```

CNINFO enrichment is cacheable and can be run in batches.  On Windows, keep
`--workers 1` if AKShare's JavaScript runtime dependency is unstable under
threaded calls.

Generate rolling out-of-sample configs and a dry-run comparison table:

```powershell
python scripts/run_rolling_baselines.py
```

Add `--execute` to actually run all rolling Qlib workflows. The generated
configs cover 2018-2020/2021/2022, 2019-2021/2022/2023, and
2020-2022/2023/2024 train/valid/test windows for Alpha158 + LightGBM and the
reversal + low-volatility 1d/5d/20d baselines.

## Expanded 2018-2026 Validation

The next validation layer keeps the old 2018-2024 reports intact and writes new
outputs under separate names. Start with HS300 current constituents, then expand
to CSI800, CSI1800, and dynamic liquidity universes.

Build or refresh a symbol file:

```powershell
python scripts/build_expanded_universe.py `
  --universe-name hs300_current `
  --output-dir data/cache/expanded_universes
```

Run one Alpha158 universe expansion. This reuses existing bars when possible and
only fetches missing date ranges:

```powershell
python scripts/run_universe_expansion.py `
  --universe-name hs300_current_2018_2026 `
  --universe-mode current_constituent `
  --selected-mode eligible_only `
  --symbols-file data/cache/expanded_universes/hs300_current_symbols.txt `
  --existing-bars data/alpha158_hs300_full_bars.parquet `
  --bars-path data/hs300_current_2018_2026_bars.parquet `
  --qlib-dir data/qlib_hs300_2018_2026 `
  --output-dir reports/alpha158_hs300_2018_2026 `
  --start-date 2018-01-01 `
  --end-date 2026-06-24
```

Generate or execute the five-window 2018-2026 rolling OOS validation:

```powershell
python scripts/run_rolling_baselines_2018_2026.py `
  --provider-uri data/qlib_hs300_2018_2026 `
  --universe-name hs300_current_2018_2026 `
  --universe-mode current_constituent `
  --selected-mode eligible_only `
  --universe-diagnostics reports/alpha158_hs300_2018_2026/universe_diagnostics.csv
```

Add `--execute` to run Qlib. The fifth window is 2026 YTD and must not be
reported as a complete calendar year. Large artifacts remain ignored:
`mlruns/`, Qlib binary data, large predictions, and positions should not be
committed.

Add `--use-ashare-exchange` to generated rolling workflows to use the custom
`ashare_adapter.exchange.AShareExchange`.  This optional exchange blocks buys
at per-stock `limit_up`, blocks sells at per-stock `limit_down`, and blocks
paused names through `$is_paused`.  The default remains Qlib's uniform
`limit_threshold` so old reports are reproducible unless the flag is explicit.

## A-share Data Notes

Qlib binary features are numeric.  The converter writes numeric fields such as
`open`, `high`, `low`, `close`, `volume`, `amount`, `factor`, `is_st`,
`is_paused`, `limit_up`, `limit_down`, `listed_days`, `avg_amount`,
`eligible`, and `selected`.
Non-numeric metadata such as `industry` and original `list_date` are preserved
under `metadata/instruments.parquet` or `metadata/instruments.csv`.

The universe filters are backward-looking.  `eligible` is the base A-share
tradability filter: ST, paused, listing age, amount, and optional limit-buy
rules.  `selected` equals `eligible` when `dynamic_liquidity_top_n` is not set.
When `--dynamic-liquidity-top-n N` is provided, `selected` is further narrowed
to the top-N eligible names by rolling average amount on that signal date.

The current full HS300 baseline is `selected_mode=eligible_only` because
`dynamic_liquidity_top_n` was not enabled for that run.  Treat dynamic top-N
results separately in reports and manifests.

The Qlib configs and generated runtime configs use `ExpressionDFilter` with
`$selected > 0.5`, so the chosen A-share universe mode is applied during
dataset loading.  `apply_signal_mask.py` and `export_qlib_records.py
--apply-mask` provide a second diagnostics-layer check by masking any
non-selected prediction scores to `NaN`.

Current committed baseline reports still use Qlib's simplified
`limit_threshold` exchange setting unless their manifest says
`ashare_exchange_limit_up_down_buffer_*`.  The project now includes an optional
`AShareExchange` for new experiments that uses per-stock `limit_up`,
`limit_down`, and `is_paused` fields as an order filter.

Expanded-universe reports must keep these caveats visible: current-constituent
or current-listed survivorship bias, `eligible_only` versus dynamic top-N,
2026 YTD windows, simplified `limit_threshold`, and industry metadata coverage.

## References

- Qlib official Alpha158 + LightGBM workflow pattern:
  https://github.com/microsoft/qlib/blob/main/examples/benchmarks/LightGBM/workflow_config_lightgbm_Alpha158.yaml
- Qlib official CSV-to-bin format implementation:
  https://github.com/microsoft/qlib/blob/main/scripts/dump_bin.py
