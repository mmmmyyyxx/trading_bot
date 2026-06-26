# Alpha158 LightGBM Baseline

Run: `1b56b291d90f46d1959ddf2a33c781d3`  
Data: 300 symbols, 567733 rows, 2018-01-02 to 2026-06-24
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.025496 |
| ICIR | 0.186640 |
| Rank IC | 0.012490 |
| Rank ICIR | 0.088434 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 16.50% |
| Benchmark information ratio | 1.066 |
| Benchmark max drawdown | -10.80% |
| Excess annualized return with cost | 31.63% |
| Excess information ratio with cost | 2.695 |
| Excess max drawdown with cost | -10.41% |
| Excess annualized return without cost | 36.89% |
| Excess information ratio without cost | 3.144 |
| Excess max drawdown without cost | -9.80% |
| Account total return | 97.12% |
| Benchmark total return | 25.62% |
| Average daily turnover | 0.396250 |
| Total cost sum | 1792632443.68 |
| Average positions | 49.95 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.02% | 4.67% |
| group_2 | 0.06% | 15.73% |
| group_3 | 0.07% | 16.97% |
| group_4 | 0.14% | 36.09% |
| group_5 | 0.19% | 47.15% |
| group_5_minus_1 | 0.17% | 42.48% |

## Notes

- Requested symbols: 300; downloaded symbols: 300; missing: none.
- Selected universe count: avg 273.63, min 222, max 300.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
