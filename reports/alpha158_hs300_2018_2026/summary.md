# Alpha158 LightGBM Baseline

Run: `70769ed138494478b56f26e03895cd66`  
Data: 300 symbols, 567733 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.030360 |
| ICIR | 0.178009 |
| Rank IC | 0.012832 |
| Rank ICIR | 0.077555 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 16.50% |
| Benchmark information ratio | 1.066 |
| Benchmark max drawdown | -10.80% |
| Excess annualized return with cost | 35.49% |
| Excess information ratio with cost | 2.445 |
| Excess max drawdown with cost | -11.05% |
| Excess annualized return without cost | 40.79% |
| Excess information ratio without cost | 2.810 |
| Excess max drawdown without cost | -10.45% |
| Account total return | 106.82% |
| Benchmark total return | 25.62% |
| Average daily turnover | 0.398710 |
| Total cost sum | 1862227255.23 |
| Average positions | 49.95 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.01% | 2.40% |
| group_2 | 0.05% | 13.82% |
| group_3 | 0.09% | 23.15% |
| group_4 | 0.12% | 30.74% |
| group_5 | 0.21% | 52.82% |
| group_5_minus_1 | 0.20% | 50.42% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 100.00% |
| Dynamic liquidity top-N | n/a |
| Max selected universe count | 300 |
| Selected count reached top-N | n/a |
| Data sufficient for dynamic top-N | n/a |

eligible_only universe; dynamic liquidity top-N was not requested.

## Data Quality

| Check | Value |
|---|---:|
| data_quality_status | warning |
| unknown_source_ratio | 0.00% |
| selected_unknown_source_ratio | 0.00% |
| amount_estimated_ratio | 0.00% |
| invalid_ohlc_ratio | 0.36% |
| invalid_amount_ratio | 0.00% |
| invalid_limit_ratio | 1.64% |
| vwap_unit_outlier_ratio | 1.53% |
| duplicate_rows | 0 |
| data_source_distribution | eastmoney=567733 |

## Industry Metadata Quality

| Check | Value |
|---|---:|
| industry_quality_status | passed |
| symbol_level_coverage | 100.00% |
| selected_universe_coverage | 100.00% |
| position_weighted_unknown | 0.20% |
| industry_source_top | eastmoney_board_industry |

This result should be interpreted as a data-quality-sensitive research result, not a validated strategy result.

## Notes

- Requested symbols: 300; downloaded symbols: 300; missing: none.
- Selected universe count: avg 273.63, min 222, max 300.
- Bar data sources: eastmoney=567733; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.

## Data Quality Warning Explanation

HS300 data quality status is warning, not passed. Key ratios are:

- invalid_ohlc_ratio: 0.003584
- invalid_limit_ratio: 0.016407
- vwap_unit_outlier_ratio: 0.015342
- extreme_amount_jump_ratio: 0.000111

Detail files are available under `reports/alpha158_hs300_2018_2026/data_quality/`:

- invalid_ohlc_rows.csv: 2035 rows, 2034 selected rows.
- invalid_limit_rows.csv: 9315 rows, 9013 selected rows.
- vwap_unit_outlier_rows.csv: 8710 rows, 8622 selected rows.
- selected_quality_by_year.csv: max yearly selected warning ratio 0.042610.
- position_quality_overlap.csv: invalid-limit overlap with exported positions totals 189 position rows; invalid-limit absolute weight sum 3.973436.

Interpretation: these warnings are not catastrophic, but they are not cosmetic either. Limit-field anomalies do overlap exported positions, so HS300 results should be interpreted as data-quality-sensitive Qlib baseline results until the affected rows are corrected, excluded, or checked against a stricter A-share exchange/order filter.
