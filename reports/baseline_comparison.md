# Baseline Comparison

Data: HS300 current-constituent universe, 298 downloaded symbols, 2018-01-02 to 2024-12-31. Test/backtest period is 2023-2024. Universe mode is `eligible_only`: `$selected > 0.5` applies ST/paused/listing-age/amount eligibility, but this run did not enable dynamic liquidity top-N.

| Baseline | IC | Rank IC | Excess Ann. With Cost | Excess IR With Cost | Excess MDD With Cost |
|---|---:|---:|---:|---:|---:|
| Alpha158 + LightGBM | 0.004596 | -0.010204 | 18.33% | 1.469 | -10.81% |
| Reversal + LowVol Ridge 1d | -0.011476 | -0.004231 | 14.92% | 1.053 | -17.95% |
| Reversal + LowVol Ridge 5d | -0.008099 | -0.004468 | 15.40% | 1.071 | -18.25% |
| Reversal + LowVol Ridge 20d | 0.007154 | 0.001960 | 15.98% | 1.105 | -18.53% |

## Multi-Benchmark Diagnostics

Alpha158 benchmark comparison:

| benchmark   |   strategy_return |   benchmark_return |   excess_return |   tracking_error |   information_ratio |     beta |   max_drawdown |   relative_drawdown |
|:------------|------------------:|-------------------:|----------------:|-----------------:|--------------------:|---------:|---------------:|--------------------:|
| csi1000     |          0.439508 |         -0.0725414 |        0.646561 |         0.132744 |             2.02313 | 0.794881 |      -0.266481 |          -0.102159  |
| csi500      |          0.439508 |         -0.0386449 |        0.633835 |         0.113989 |             2.30048 | 0.941467 |      -0.266481 |          -0.0780165 |
| hs300       |          0.439508 |          0.0120919 |        0.592253 |         0.128257 |             1.9532  | 1.14597  |      -0.266481 |          -0.109366  |

Reversal + LowVol Ridge 1d benchmark comparison:

| benchmark   |   strategy_return |   benchmark_return |   excess_return |   tracking_error |   information_ratio |     beta |   max_drawdown |   relative_drawdown |
|:------------|------------------:|-------------------:|----------------:|-----------------:|--------------------:|---------:|---------------:|--------------------:|
| csi1000     |          0.338062 |         -0.0725414 |        0.501991 |         0.147294 |             1.512   | 0.794972 |        -0.2951 |          -0.124713  |
| csi500      |          0.338062 |         -0.0386449 |        0.490431 |         0.130639 |             1.65631 | 0.941604 |        -0.2951 |          -0.0924107 |
| hs300       |          0.338062 |          0.0120919 |        0.451514 |         0.145644 |             1.40522 | 1.13537  |        -0.2951 |          -0.168231  |

Reversal + LowVol Ridge 5d benchmark comparison:

| benchmark   |   strategy_return |   benchmark_return |   excess_return |   tracking_error |   information_ratio |     beta |   max_drawdown |   relative_drawdown |
|:------------|------------------:|-------------------:|----------------:|-----------------:|--------------------:|---------:|---------------:|--------------------:|
| csi1000     |          0.350423 |         -0.0725414 |        0.516501 |         0.148131 |             1.53811 | 0.797607 |      -0.292992 |          -0.125255  |
| csi500      |          0.350423 |         -0.0386449 |        0.504577 |         0.132246 |             1.67501 | 0.943414 |      -0.292992 |          -0.0952938 |
| hs300       |          0.350423 |          0.0120919 |        0.46497  |         0.147846 |             1.41902 | 1.13473  |      -0.292992 |          -0.170878  |

Reversal + LowVol Ridge 20d benchmark comparison:

| benchmark   |   strategy_return |   benchmark_return |   excess_return |   tracking_error |   information_ratio |     beta |   max_drawdown |   relative_drawdown |
|:------------|------------------:|-------------------:|----------------:|-----------------:|--------------------:|---------:|---------------:|--------------------:|
| csi1000     |          0.365933 |         -0.0725414 |        0.533757 |         0.147568 |             1.58336 | 0.801551 |      -0.295777 |          -0.123208  |
| csi500      |          0.365933 |         -0.0386449 |        0.521406 |         0.132373 |             1.7173  | 0.946733 |      -0.295777 |          -0.0960961 |
| hs300       |          0.365933 |          0.0120919 |        0.481062 |         0.148657 |             1.45036 | 1.13675  |      -0.295777 |          -0.173184  |

## Qlib Record Exports

- Alpha158: `reports/alpha158_hs300_full/qlib_records/`
- Reversal 1d: `reports/reversal_lowvol_hs300_full/qlib_records/`
- Reversal 5d: `reports/reversal_lowvol_5d_hs300_full/qlib_records/`
- Reversal 20d: `reports/reversal_lowvol_20d_hs300_full/qlib_records/`

## Notes

- All baselines use Qlib `ExpressionDFilter` with `$selected > 0.5` during dataset loading.
- In these full HS300 runs, `selected` equals the eligible universe because `dynamic_liquidity_top_n` was not enabled. Dynamic top-N runs should be compared separately.
- `export_qlib_records.py --apply-mask` is also available as a diagnostics-layer check. For Alpha158 it did not add newly masked rows because Qlib had already filtered the prediction universe.
- Qlib backtest still uses simplified `limit_threshold`; per-stock `limit_up`/`limit_down` fields are available in data but not yet used by a custom exchange/order filter.
