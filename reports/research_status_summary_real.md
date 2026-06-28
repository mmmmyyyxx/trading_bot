# Research Status Summary Real AKShare

All formal tables referenced here use `data_type=real_akshare`, `synthetic_data=False`, and `mock_data=False`.

## Current Real-Data Experiment Scope
Formal universe expansion currently covers 6 rows: hs300_current_2018_2026, dynamic_candidate1000_top300_2018_2026, csi800_current_2018_2026, csi1800_current_2018_2026, dynamic_candidate2000_top500_2018_2026, dynamic_candidate2000_top450_2018_2026.

## Universe Expansion Main Results
| universe_name                          | result_role                     | selected_mode            |   data_sufficient_for_dynamic_top_n |   excess_annualized_return_with_cost |   excess_information_ratio_with_cost | data_quality_status   | industry_quality_status   |
|:---------------------------------------|:--------------------------------|:-------------------------|------------------------------------:|-------------------------------------:|-------------------------------------:|:----------------------|:--------------------------|
| hs300_current_2018_2026                | primary_current_constituent     | eligible_only            |                                 nan |                             0.354934 |                              2.44544 | warning               | passed                    |
| dynamic_candidate1000_top300_2018_2026 | primary_dynamic_candidate       | dynamic_liquidity_top300 |                                   1 |                             0.307874 |                              2.38256 | passed                | passed                    |
| csi800_current_2018_2026               | primary_current_constituent     | eligible_only            |                                 nan |                             0.388565 |                              2.90627 | warning               | passed                    |
| csi1800_current_2018_2026              | primary_current_constituent     | eligible_only            |                                 nan |                             0.461181 |                              3.29258 | warning               | passed                    |
| dynamic_candidate2000_top500_2018_2026 | supplementary_insufficient_topn | dynamic_liquidity_top500 |                                   0 |                             0.47839  |                              3.1495  | passed                | passed                    |
| dynamic_candidate2000_top450_2018_2026 | primary_dynamic_large_candidate | dynamic_liquidity_top450 |                                   1 |                             0.448465 |                              3.0094  | passed                | passed                    |

## Rolling OOS Stability
| universe_name                          |   positive_excess_windows |   positive_excess_ratio |   min_excess_annualized |   y2026_excess |   y2026_IR | conclusion_tag                      |
|:---------------------------------------|--------------------------:|------------------------:|------------------------:|---------------:|-----------:|:------------------------------------|
| dynamic_candidate1000_top300_2018_2026 |                         4 |                     0.8 |              -0.0680957 |     -0.0680957 |  -0.583656 | mostly_positive_but_recent_weakness |
| dynamic_candidate2000_top450_2018_2026 |                         5 |                     1   |               0.0221773 |      0.197384  |   1.59584  | stable_positive                     |
| hs300_current_2018_2026                |                         5 |                     1   |               0.184365  |      0.184365  |   1.71845  | stable_positive                     |

## Low-Turnover Workflow Results
| scenario              |   excess_annualized_return_with_cost |   excess_information_ratio_with_cost |   turnover |        cost | data_quality_status   | industry_quality_status   |
|:----------------------|-------------------------------------:|-------------------------------------:|-----------:|------------:|:----------------------|:--------------------------|
| topk50_drop1          |                             0.305551 |                              1.96264 |  0.0424368 | 2.22808e+08 | passed                | passed                    |
| weekly_topk50_drop10  |                             0.330974 |                              2.55811 |  0.0816381 | 3.89186e+08 | passed                | passed                    |
| monthly_topk50_drop10 |                             0.224479 |                              1.63228 |  0.0209446 | 8.49848e+07 | passed                | passed                    |

## Low-Turnover Rolling Stability
| scenario              |   positive_excess_windows |   positive_excess_ratio |   mean_excess_annualized |   y2026_excess |   mean_turnover | conclusion_tag                      |
|:----------------------|--------------------------:|------------------------:|-------------------------:|---------------:|----------------:|:------------------------------------|
| monthly_topk50_drop10 |                         3 |                     0.6 |              -0.0186475  |      -0.370704 |       0.0214806 | mostly_positive_but_recent_weakness |
| weekly_topk50_drop10  |                         4 |                     0.8 |               0.00364481 |      -0.374373 |       0.0823529 | mostly_positive_but_recent_weakness |

## AShareExchange Rolling Stability
| exchange_scenario             |   positive_excess_windows |   positive_excess_ratio |   mean_excess_annualized |   min_excess_annualized |   y2026_excess |   mean_turnover | conclusion_tag                      |
|:------------------------------|--------------------------:|------------------------:|-------------------------:|------------------------:|---------------:|----------------:|:------------------------------------|
| ashare_exchange_buffer_0.000  |                         4 |                     0.8 |                0.0616113 |              -0.129694  |     -0.129694  |        0.387447 | mostly_positive_but_recent_weakness |
| ashare_exchange_buffer_0.001  |                         4 |                     0.8 |                0.0535945 |              -0.161594  |     -0.161594  |        0.385717 | mostly_positive_but_recent_weakness |
| uniform_limit_threshold_0.095 |                         4 |                     0.8 |                0.0917086 |              -0.0680957 |     -0.0680957 |        0.399668 | mostly_positive_but_recent_weakness |

## Data Quality And Industry Quality
| universe_name                          | data_quality_status   | industry_quality_status   |   unknown_source_ratio |   invalid_limit_ratio |
|:---------------------------------------|:----------------------|:--------------------------|-----------------------:|----------------------:|
| csi800_current_2018_2026               | warning               | passed                    |                      0 |             0.0168831 |
| csi1800_current_2018_2026              | warning               | passed                    |                      0 |             0.015911  |
| dynamic_candidate2000_top500_2018_2026 | passed                | passed                    |                      0 |             0.0151798 |

## Historical Constituents Preparation
HS300 historical membership coverage status: `insufficient_historical_membership`. Historical membership available: `False`. Current snapshot symbols: `300`. Project AKShare helpers expose current constituents only; no complete historical membership endpoint is available here.

## Caveats
- Current-constituent and current-listed candidate bias remain unless historical membership is supplied.
- Dynamic top500 is supplementary because the selected universe did not fully reach the intended top-N target.
- 2026 windows are YTD and should not be interpreted as complete calendar-year tests.
- Uniform Qlib limit thresholds remain a simplification; AShareExchange rolling improves realism but is still part of the research validation stack.
- IC, beta, industry exposure, and rolling diagnostics should be read together before making strategy conclusions.

## Next Steps
- Prioritize historical index constituent coverage for HS300, then CSI500 and CSI1000.
- Promote top450 and low-turnover rolling results into the main narrative only after reviewing 2026YTD weakness.
- Continue improving A-share exchange/order constraints and compare against the uniform-limit baseline.
