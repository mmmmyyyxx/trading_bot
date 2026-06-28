# Alpha158 LightGBM Baseline

Run: `bb7fe07c6a444d44ab3803cdf573cee2`
Data: 1999 symbols, 3268352 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: dynamic_liquidity_top450; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.054937 |
| ICIR | 0.470987 |
| Rank IC | 0.054887 |
| Rank ICIR | 0.534382 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 44.85% |
| Excess information ratio with cost | 3.009 |
| Excess max drawdown with cost | -11.21% |
| Excess annualized return without cost | 50.13% |
| Excess information ratio without cost | 3.363 |
| Excess max drawdown without cost | -10.75% |
| Account total return | 191.05% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.397877 |
| Total cost sum | 2083708583.38 |
| Average positions | 49.98 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | -0.11% | -26.76% |
| group_2 | 0.10% | 26.33% |
| group_3 | 0.12% | 30.86% |
| group_4 | 0.18% | 44.33% |
| group_5 | 0.31% | 78.32% |
| group_5_minus_1 | 0.42% | 105.08% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 99.95% |
| Dynamic liquidity top-N | 450 |
| Max selected universe count | 450 |
| Selected count reached top-N | yes |
| Data sufficient for dynamic top-N | yes |

dynamic top450 selected count reached the configured target.

## Data Quality

| Check | Value |
|---|---:|
| data_quality_status | passed |
| unknown_source_ratio | 0.00% |
| selected_unknown_source_ratio | 0.00% |
| amount_estimated_ratio | 0.00% |
| invalid_ohlc_ratio | 0.05% |
| invalid_amount_ratio | 0.00% |
| invalid_limit_ratio | 1.52% |
| vwap_unit_outlier_ratio | 0.38% |
| duplicate_rows | 0 |
| data_source_distribution | eastmoney=3268352 |

## Industry Metadata Quality

| Check | Value |
|---|---:|
| industry_quality_status | passed |
| symbol_level_coverage | 100.00% |
| selected_universe_coverage | 100.00% |
| position_weighted_unknown | 0.32% |
| industry_source_top | akshare_metadata_cache |

## Notes

- Requested symbols: 2000; downloaded symbols: 1999; missing: 001399.SZ.
- Selected universe count: avg 434.19, min 398, max 450.
- Bar data sources: eastmoney=3268352; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=dynamic_liquidity_top450; verify the candidate universe construction separately.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
