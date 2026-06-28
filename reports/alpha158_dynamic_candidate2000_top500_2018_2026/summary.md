# Alpha158 LightGBM Baseline

Run: `23711ce6b42549a69a0e8ac95d99ec0a`  
Data: 1880 symbols, 3169631 rows, 2018-01-02 to 2026-06-24
Universe: dynamic_liquidity_top500; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.054562 |
| ICIR | 0.453779 |
| Rank IC | 0.057006 |
| Rank ICIR | 0.537234 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 28.69% |
| Benchmark information ratio | 1.271 |
| Benchmark max drawdown | -17.73% |
| Excess annualized return with cost | 41.55% |
| Excess information ratio with cost | 3.363 |
| Excess max drawdown with cost | -8.00% |
| Excess annualized return without cost | 46.87% |
| Excess information ratio without cost | 3.793 |
| Excess max drawdown without cost | -7.74% |
| Account total return | 167.47% |
| Benchmark total return | 47.60% |
| Average daily turnover | 0.400243 |
| Total cost sum | 2157583393.61 |
| Average positions | 49.92 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | -0.10% | -24.18% |
| group_2 | 0.11% | 28.14% |
| group_3 | 0.14% | 35.79% |
| group_4 | 0.17% | 41.72% |
| group_5 | 0.29% | 72.98% |
| group_5_minus_1 | 0.39% | 97.15% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 94.00% |
| Dynamic liquidity top-N | 500 |
| Max selected universe count | 500 |
| Selected count reached top-N | yes |
| Data sufficient for dynamic top-N | yes |

dynamic top500 selected count reached the configured target.

## Notes

- Requested symbols: 2000; downloaded symbols: 1880; missing: 001399.SZ, 920000.BJ, 920002.BJ, 920005.BJ, 920008.BJ, 920009.BJ, 920011.BJ, 920035.BJ, 920036.BJ, 920057.BJ, 920060.BJ, 920062.BJ, 920066.BJ, 920068.BJ, 920069.BJ, 920076.BJ, 920078.BJ, 920087.BJ, 920088.BJ, 920089.BJ, 920091.BJ, 920118.BJ, 920124.BJ, 920126.BJ, 920139.BJ, 920149.BJ, 920158.BJ, 920160.BJ, 920171.BJ, 920180.BJ, ... (+90 more).
- Selected universe count: avg 483.22, min 447, max 500.
- Bar data sources: tencent_tx=2609027, unknown=560604; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=dynamic_liquidity_top500; verify the candidate universe construction separately.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
- Bar data uses mixed sources; verify source-specific price/volume/amount conventions before interpreting liquidity-sensitive results.
