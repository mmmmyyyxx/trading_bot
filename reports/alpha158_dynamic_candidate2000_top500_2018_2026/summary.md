# Alpha158 LightGBM Baseline

Run: `d16ce9def249450ba365927bf4383140`  
Data: 1999 symbols, 3268352 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: dynamic_liquidity_top500; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.054374 |
| ICIR | 0.469516 |
| Rank IC | 0.055355 |
| Rank ICIR | 0.532677 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 47.84% |
| Excess information ratio with cost | 3.149 |
| Excess max drawdown with cost | -13.26% |
| Excess annualized return without cost | 53.17% |
| Excess information ratio without cost | 3.499 |
| Excess max drawdown without cost | -12.64% |
| Account total return | 204.87% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.401074 |
| Total cost sum | 2170104689.01 |
| Average positions | 49.92 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | -0.10% | -25.71% |
| group_2 | 0.10% | 24.13% |
| group_3 | 0.14% | 35.33% |
| group_4 | 0.18% | 45.52% |
| group_5 | 0.30% | 76.38% |
| group_5_minus_1 | 0.41% | 102.08% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 99.95% |
| Dynamic liquidity top-N | 500 |
| Max selected universe count | 499 |
| Selected count reached top-N | no |
| Data sufficient for dynamic top-N | no |

data insufficient for intended dynamic top500; max selected universe count is 499.

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
| position_weighted_unknown | 0.18% |
| industry_source_top | akshare_metadata_cache |

## Notes

- Requested symbols: 2000; downloaded symbols: 1999; missing: 001399.SZ.
- Selected universe count: avg 482.98, min 443, max 499.
- Bar data sources: eastmoney=3268352; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=dynamic_liquidity_top500; verify the candidate universe construction separately.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
- Data insufficient for intended dynamic liquidity top500: max selected universe count is 499, below 500.
