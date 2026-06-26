# Alpha158 LightGBM Baseline

Run: `d3c5cf1f39214c238213403312b9c2d7`  
Data: 940 symbols, 1583002 rows, 2018-01-02 to 2026-06-24
Universe: dynamic_liquidity_top_300; selected filter: `$selected > 0.5`

## Signal

| Metric | Value |
|---|---:|
| IC | 0.044454 |
| ICIR | 0.329830 |
| Rank IC | 0.056283 |
| Rank ICIR | 0.502017 |
| Test days | 353 |

## Portfolio

| Metric | Value |
|---|---:|
| Benchmark annualized return | 31.49% |
| Benchmark information ratio | 1.464 |
| Benchmark max drawdown | -14.86% |
| Excess annualized return with cost | 33.06% |
| Excess information ratio with cost | 2.681 |
| Excess max drawdown with cost | -10.98% |
| Excess annualized return without cost | 38.39% |
| Excess information ratio without cost | 3.113 |
| Excess max drawdown without cost | -10.49% |
| Account total return | 148.18% |
| Benchmark total return | 54.44% |
| Average daily turnover | 0.401174 |
| Total cost sum | 1952933658.07 |
| Average positions | 49.93 |

## Group Returns

| Group | Mean Daily Return | Simple Annualized |
|---|---:|---:|
| group_1 | -0.04% | -11.28% |
| group_2 | 0.07% | 18.81% |
| group_3 | 0.15% | 36.91% |
| group_4 | 0.15% | 37.77% |
| group_5 | 0.29% | 72.46% |
| group_5_minus_1 | 0.33% | 83.73% |

## Data Sufficiency

| Check | Value |
|---|---:|
| Candidate coverage | 94.00% |
| Dynamic liquidity top-N | 300 |
| Max selected universe count | 300 |
| Selected count reached top-N | yes |
| Data sufficient for dynamic top-N | yes |

dynamic top300 selected count reached the configured target.

## Notes

- Requested symbols: 1000; downloaded symbols: 940; missing: 920000.BJ, 920002.BJ, 920009.BJ, 920035.BJ, 920036.BJ, 920057.BJ, 920060.BJ, 920062.BJ, 920069.BJ, 920076.BJ, 920087.BJ, 920091.BJ, 920139.BJ, 920158.BJ, 920160.BJ, 920171.BJ, 920180.BJ, 920186.BJ, 920206.BJ, 920208.BJ, 920211.BJ, 920225.BJ, 920239.BJ, 920260.BJ, 920267.BJ, 920274.BJ, 920284.BJ, 920339.BJ, 920371.BJ, 920394.BJ, ... (+30 more).
- Selected universe count: avg 290.20, min 268, max 300.
- Bar data sources: tencent_tx=1296978, unknown=286024; amount-estimated rows: 0.
- This is a baseline research backtest result, not investment advice.

## Caveats

- Results inherit the survivorship properties of the supplied symbol universe; current-constituent or current-listed universes are not historical membership backtests.
- selected_mode=dynamic_liquidity_top_300; verify the candidate universe construction separately.
- The 2026 period is year-to-date, not a complete calendar year.
- Qlib baseline backtests use the configured uniform limit_threshold and do not fully enforce per-stock A-share board/ST limit rules.
- Industry and active-exposure diagnostics depend on metadata coverage; inspect unknown industry weight before using industry conclusions.
- Bar data uses mixed sources; verify source-specific price/volume/amount conventions before interpreting liquidity-sensitive results.
