# Alpha158 LightGBM Baseline

Run: `c6c59f06bcb24ccca6a3daa5cabfc292`  
Data: 1800 symbols, 3200985 rows, 2018-01-02 to 2026-06-24
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.033674 |
| ICIR | 0.398584 |
| Rank IC | 0.020275 |
| Rank ICIR | 0.192130 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 28.69% |
| Benchmark information ratio | 1.271 |
| Benchmark max drawdown | -17.73% |
| Excess annualized return with cost | 41.59% |
| Excess information ratio with cost | 3.224 |
| Excess max drawdown with cost | -6.25% |
| Excess annualized return without cost | 47.00% |
| Excess information ratio without cost | 3.643 |
| Excess max drawdown without cost | -6.18% |
| Account total return | 167.36% |
| Benchmark total return | 47.60% |
| Average daily turnover | 0.407020 |
| Total cost sum | 2274598804.22 |
| Average positions | 49.93 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.04% | 9.20% |
| group_2 | 0.11% | 26.73% |
| group_3 | 0.14% | 35.87% |
| group_4 | 0.15% | 37.88% |
| group_5 | 0.23% | 57.85% |
| group_5_minus_1 | 0.19% | 48.65% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 100.00% |
| Dynamic liquidity top-N | n/a |
| Max selected universe count | 1800 |
| Selected count reached top-N | n/a |
| Data sufficient for dynamic top-N | n/a |

eligible_only universe; dynamic liquidity top-N was not requested.

## Notes

- Requested symbols: 1800; downloaded symbols: 1800; missing: none.
- Selected universe count: avg 1529.12, min 1124, max 1800.
- Bar data sources: tencent_tx=1730404, unknown=1470581; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
- Bar data uses mixed sources; verify source-specific price/volume/amount conventions before interpreting liquidity-sensitive results.
