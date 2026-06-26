# Alpha158 LightGBM Baseline

Run: `f1575a29fcf843debabaf788ec2fb082`  
Data: 799 symbols, 1470581 rows, 2018-01-02 to 2026-06-24
Universe: eligible_only; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.025180 |
| ICIR | 0.232605 |
| Rank IC | 0.012686 |
| Rank ICIR | 0.109591 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 30.92% |
| Excess information ratio with cost | 2.480 |
| Excess max drawdown with cost | -6.04% |
| Excess annualized return without cost | 36.25% |
| Excess information ratio without cost | 2.907 |
| Excess max drawdown without cost | -5.75% |
| Account total return | 139.57% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.400664 |
| Total cost sum | 2076845520.81 |
| Average positions | 49.89 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | 0.04% | 11.23% |
| group_2 | 0.09% | 23.49% |
| group_3 | 0.12% | 30.36% |
| group_4 | 0.14% | 35.94% |
| group_5 | 0.21% | 52.27% |
| group_5_minus_1 | 0.16% | 41.05% |

## Notes

- Requested symbols: 800; downloaded symbols: 799; missing: 689009.SH.
- Selected universe count: avg 706.62, min 548, max 799.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=eligible_only; no dynamic liquidity top-N filter was applied.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
