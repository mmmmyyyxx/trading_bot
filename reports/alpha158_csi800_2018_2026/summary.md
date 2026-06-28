# Alpha158 LightGBM Baseline

Run: `be6dc72314ea4ee7ba880586b320743f`  
Data: 800 symbols, 1471949 rows, 2018-01-02 to 2026-06-24
Data type: `real_akshare`; synthetic: `False`; mock: `False`
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.023760 |
| ICIR | 0.222260 |
| Rank IC | 0.018499 |
| Rank ICIR | 0.167725 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 38.86% |
| Excess information ratio with cost | 2.906 |
| Excess max drawdown with cost | -5.67% |
| Excess annualized return without cost | 44.17% |
| Excess information ratio without cost | 3.303 |
| Excess max drawdown without cost | -5.58% |
| Account total return | 168.30% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.399728 |
| Total cost sum | 2101372483.11 |
| Average positions | 49.94 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.08% | 20.78% |
| group_2 | 0.09% | 23.83% |
| group_3 | 0.10% | 26.35% |
| group_4 | 0.11% | 28.09% |
| group_5 | 0.22% | 56.11% |
| group_5_minus_1 | 0.14% | 35.33% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 100.00% |
| Dynamic liquidity top-N | n/a |
| Max selected universe count | 800 |
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
| invalid_ohlc_ratio | 0.27% |
| invalid_amount_ratio | 0.00% |
| invalid_limit_ratio | 1.69% |
| vwap_unit_outlier_ratio | 1.17% |
| duplicate_rows | 0 |
| data_source_distribution | eastmoney=1471949 |

## Industry Metadata Quality

| Check | Value |
|---|---:|
| industry_quality_status | passed |
| symbol_level_coverage | 100.00% |
| selected_universe_coverage | 100.00% |
| position_weighted_unknown | 0.19% |
| industry_source_top | akshare_metadata_cache |

This result should be interpreted as a data-quality-sensitive research result, not a validated strategy result.

## Notes

- Requested symbols: 800; downloaded symbols: 800; missing: none.
- Selected universe count: avg 707.25, min 548, max 800.
- Bar data sources: eastmoney=1471949; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
