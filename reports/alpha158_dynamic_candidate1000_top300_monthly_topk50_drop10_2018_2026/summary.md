# Alpha158 LightGBM Baseline

Run: `ba467adc407b47c3898e2df0275a9fff`
Data: 1000 symbols, 1628405 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: dynamic_liquidity_top300; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.044068 |
| ICIR | 0.328556 |
| Rank IC | 0.054150 |
| Rank ICIR | 0.489679 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 22.45% |
| Excess information ratio with cost | 1.632 |
| Excess max drawdown with cost | -11.45% |
| Excess annualized return without cost | 22.71% |
| Excess information ratio without cost | 1.652 |
| Excess max drawdown without cost | -11.38% |
| Account total return | 111.26% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.020945 |
| Total cost sum | 84984841.74 |
| Average positions | 47.17 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | -0.06% | -14.65% |
| group_2 | 0.07% | 17.72% |
| group_3 | 0.15% | 38.02% |
| group_4 | 0.16% | 41.47% |
| group_5 | 0.28% | 71.59% |
| group_5_minus_1 | 0.34% | 86.25% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 100.00% |
| Dynamic liquidity top-N | 300 |
| Max selected universe count | 300 |
| Selected count reached top-N | yes |
| Data sufficient for dynamic top-N | yes |

dynamic top300 selected count reached the configured target.

## Data Quality

| Check | Value |
|---|---:|
| data_quality_status | passed |
| unknown_source_ratio | 0.00% |
| selected_unknown_source_ratio | 0.00% |
| amount_estimated_ratio | 0.00% |
| invalid_ohlc_ratio | 0.07% |
| invalid_amount_ratio | 0.00% |
| invalid_limit_ratio | 1.57% |
| vwap_unit_outlier_ratio | 0.46% |
| duplicate_rows | 0 |
| data_source_distribution | eastmoney=1628405 |

## Industry Metadata Quality

| Check | Value |
|---|---:|
| industry_quality_status | passed |
| symbol_level_coverage | 100.00% |
| selected_universe_coverage | 100.00% |
| position_weighted_unknown | 0.18% |
| industry_source_top | akshare_metadata_cache |

## Notes

- Requested symbols: 1000; downloaded symbols: 1000; missing: none.
- Selected universe count: avg 290.04, min 268, max 300.
- Bar data sources: eastmoney=1628405; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=dynamic_liquidity_top300; verify the candidate universe construction separately.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
