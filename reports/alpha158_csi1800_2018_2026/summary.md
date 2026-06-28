# Alpha158 LightGBM Baseline

Run: `5db8734e009043579bc3daa0dfa35894`  
Data: 1800 symbols, 3200983 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.029260 |
| ICIR | 0.370537 |
| Rank IC | 0.019608 |
| Rank ICIR | 0.213148 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 28.69% |
| Benchmark information ratio | 1.271 |
| Benchmark max drawdown | -17.73% |
| Excess annualized return with cost | 46.12% |
| Excess information ratio with cost | 3.293 |
| Excess max drawdown with cost | -5.64% |
| Excess annualized return without cost | 51.57% |
| Excess information ratio without cost | 3.681 |
| Excess max drawdown without cost | -5.20% |
| Account total return | 185.26% |
| Benchmark total return | 47.60% |
| Average daily turnover | 0.410077 |
| Total cost sum | 2328328643.44 |
| Average positions | 49.87 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.07% | 17.46% |
| group_2 | 0.10% | 26.26% |
| group_3 | 0.14% | 35.23% |
| group_4 | 0.15% | 36.82% |
| group_5 | 0.21% | 52.75% |
| group_5_minus_1 | 0.14% | 35.30% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 100.00% |
| Dynamic liquidity top-N | n/a |
| Max selected universe count | 1800 |
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
| invalid_ohlc_ratio | 0.13% |
| invalid_amount_ratio | 0.00% |
| invalid_limit_ratio | 1.59% |
| vwap_unit_outlier_ratio | 0.84% |
| duplicate_rows | 0 |
| data_source_distribution | eastmoney=3200983 |

## Industry Metadata Quality

| Check | Value |
|---|---:|
| industry_quality_status | passed |
| symbol_level_coverage | 100.00% |
| selected_universe_coverage | 100.00% |
| position_weighted_unknown | 0.05% |
| industry_source_top | akshare_metadata_cache |

This result should be interpreted as a data-quality-sensitive research result, not a validated strategy result.

## Notes

- Requested symbols: 1800; downloaded symbols: 1800; missing: none.
- Selected universe count: avg 1529.12, min 1124, max 1800.
- Bar data sources: eastmoney=3200983; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
