# 研究诊断报告

本报告用于诊断当前多因子策略是否存在可验证的 alpha 来源，而不是证明策略可以实盘盈利。

## 1. 当前配置

- 数据源：`akshare`，仅使用真实数据
- 回测区间：`2022-01-01` 到 `2026-06-24`
- 股票池模式：`dynamic_liquidity`，top_n：`3000`，liquidity_window：`20`
- 候选股票源：`akshare_metadata`
- possible_selection_bias：`False`
- 策略名称：`reversal_low_vol`
- 默认 top_k：`50`
- 默认调仓频率：`M`
- 默认权重方式：`equal_weight`
- industry_momentum fallback rate：`7.43%`
- industry_momentum low confidence：`False`
- quality_factor_available：`False`，value_factor_available：`False`

## 2. 股票池诊断

动态股票池只使用信号日及之前的滚动成交额、ST、停牌、上市天数等字段。若使用 current_snapshot，则候选股票集合可能来自当前流动性快照，报告会标记选择偏差风险。

- 平均 raw_count：`2857.17`
- 平均 eligible_count：`2144.52`
- 平均 selected_universe_count：`2144.52`
- 平均 raw_to_top_n_ratio：`95.24%`
- candidate_pool_limited：`True`
- 平均 industry_coverage_rate：`91.70%`
- 平均 listed_days_fallback_rate：`0.00%`
- possible_selection_bias：`False`

| date | raw_count | eligible_count | selected_universe_count | configured_top_n | raw_to_top_n_ratio | candidate_pool_limited | candidate_source | industry_coverage_rate | listed_days_fallback_rate | universe_mode | possible_selection_bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022-01-28 | 2580 | 1920 | 1920 | 3000 | 0.860000 | True | akshare_metadata | 0.908140 | 0.000000 | dynamic_liquidity | False |
| 2022-02-28 | 2591 | 1750 | 1750 | 3000 | 0.863667 | True | akshare_metadata | 0.908915 | 0.000000 | dynamic_liquidity | False |
| 2022-03-31 | 2607 | 1783 | 1783 | 3000 | 0.869000 | True | akshare_metadata | 0.909091 | 0.000000 | dynamic_liquidity | False |
| 2022-04-29 | 2622 | 1713 | 1713 | 3000 | 0.874000 | True | akshare_metadata | 0.909992 | 0.000000 | dynamic_liquidity | False |
| 2022-05-31 | 2634 | 1669 | 1669 | 3000 | 0.878000 | True | akshare_metadata | 0.910023 | 0.000000 | dynamic_liquidity | False |
| 2022-06-30 | 2645 | 1875 | 1875 | 3000 | 0.881667 | True | akshare_metadata | 0.910397 | 0.000000 | dynamic_liquidity | False |
| 2022-07-29 | 2662 | 1862 | 1862 | 3000 | 0.887333 | True | akshare_metadata | 0.910969 | 0.000000 | dynamic_liquidity | False |
| 2022-08-31 | 2691 | 1952 | 1952 | 3000 | 0.897000 | True | akshare_metadata | 0.911929 | 0.000000 | dynamic_liquidity | False |
| 2022-09-30 | 2712 | 1675 | 1675 | 3000 | 0.904000 | True | akshare_metadata | 0.913348 | 0.000000 | dynamic_liquidity | False |
| 2022-10-31 | 2724 | 1686 | 1686 | 3000 | 0.908000 | True | akshare_metadata | 0.913363 | 0.000000 | dynamic_liquidity | False |

## 3. Benchmark 对比

Benchmark 仅使用 AKShare 真实指数数据；如果真实指数不可用，研究诊断会失败而不是生成模拟数据。

| benchmark | benchmark_name | source | benchmark_return |
| --- | --- | --- | --- |
| csi1000 | 中证1000 | akshare | 0.101517 |
| csi500 | 中证500 | akshare | 0.202392 |
| hs300 | 沪深300 | akshare | 0.005135 |

## 4. 因子 Rank IC

Rank IC 衡量因子排序与未来收益排序的 Spearman 相关性。长期接近 0 说明排序能力弱；方向不稳定说明因子不稳。波动率因子按“低波动更好”做了方向调整。

| factor | horizon | ic_mean | ic_std | icir | positive_ic_ratio | observations | avg_count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| composite_score | 1 | 0.057535 | 0.156553 | 0.367511 | 0.660784 | 1020 | 2795.591176 |
| composite_score | 5 | 0.078473 | 0.146253 | 0.536553 | 0.719488 | 1016 | 2794.877953 |
| composite_score | 20 | 0.099458 | 0.147309 | 0.675166 | 0.740260 | 1001 | 2792.163836 |
| industry_momentum | 1 | -0.010814 | 0.126706 | -0.085348 | 0.469149 | 940 | 2833.121277 |
| industry_momentum | 5 | -0.021472 | 0.121236 | -0.177111 | 0.407051 | 936 | 2832.507479 |
| industry_momentum | 20 | -0.033946 | 0.124228 | -0.273254 | 0.412595 | 921 | 2830.170467 |
| liquidity | 1 | -0.055746 | 0.169689 | -0.328518 | 0.349670 | 1061 | 2850.659755 |
| liquidity | 5 | -0.086527 | 0.167858 | -0.515473 | 0.285714 | 1057 | 2850.099338 |
| liquidity | 20 | -0.128679 | 0.175942 | -0.731375 | 0.222649 | 1042 | 2848.001919 |
| momentum | 1 | -0.011548 | 0.155105 | -0.074456 | 0.474468 | 940 | 2833.121277 |
| momentum | 5 | -0.022893 | 0.148361 | -0.154309 | 0.417735 | 936 | 2832.507479 |
| momentum | 20 | -0.034132 | 0.153064 | -0.222995 | 0.444083 | 921 | 2830.170467 |
| short_term_reversal | 1 | 0.047928 | 0.168850 | 0.283847 | 0.626415 | 1060 | 2850.519811 |
| short_term_reversal | 5 | 0.066607 | 0.152612 | 0.436446 | 0.687500 | 1056 | 2849.959280 |
| short_term_reversal | 20 | 0.087078 | 0.146066 | 0.596153 | 0.725264 | 1041 | 2847.861671 |
| trend | 1 | -0.049963 | 0.178935 | -0.279224 | 0.383975 | 961 | 2836.300728 |
| trend | 5 | -0.074859 | 0.165480 | -0.452375 | 0.312435 | 957 | 2835.702194 |
| trend | 20 | -0.101336 | 0.162107 | -0.625119 | 0.277070 | 942 | 2833.426752 |
| volatility | 1 | 0.045400 | 0.215282 | 0.210888 | 0.580392 | 1020 | 2844.923529 |
| volatility | 5 | 0.062532 | 0.208750 | 0.299555 | 0.638780 | 1016 | 2844.364173 |
| volatility | 20 | 0.079805 | 0.207400 | 0.384786 | 0.694306 | 1001 | 2842.232767 |

## 5. 因子分组收益

将股票按因子分成 5 组。有效因子通常应表现为高分组收益稳定高于低分组收益。波动率因子的高分组表示低波动股票。

| factor | group | total_return | annual_return | avg_group_size | confidence |
| --- | --- | --- | --- | --- | --- |
| composite_score | 1 | -0.132811 | -0.034593 | 559.516667 | normal |
| composite_score | 2 | 1.023896 | 0.190273 | 558.903922 | normal |
| composite_score | 3 | 1.195557 | 0.214456 | 558.948039 | normal |
| composite_score | 4 | 1.034070 | 0.191748 | 558.903922 | normal |
| composite_score | 5 | 0.846465 | 0.163595 | 559.318627 | normal |
| industry_momentum | 1 | 0.750029 | 0.161868 | 567.035106 | normal |
| industry_momentum | 2 | 0.864606 | 0.181790 | 566.408511 | normal |
| industry_momentum | 3 | 0.752031 | 0.162224 | 566.458511 | normal |
| industry_momentum | 4 | 0.590499 | 0.132474 | 566.397872 | normal |
| industry_momentum | 5 | 0.399003 | 0.094188 | 566.821277 | normal |
| liquidity | 1 | 2.536026 | 0.349829 | 570.534402 | normal |
| liquidity | 2 | 1.446457 | 0.236751 | 569.908577 | normal |
| liquidity | 3 | 0.597245 | 0.117643 | 569.965127 | normal |
| liquidity | 4 | 0.086218 | 0.019837 | 569.908577 | normal |
| liquidity | 5 | -0.244925 | -0.064549 | 570.343073 | normal |
| momentum | 1 | 0.753632 | 0.162509 | 567.032979 | normal |
| momentum | 2 | 0.761193 | 0.163851 | 566.411702 | normal |
| momentum | 3 | 0.869044 | 0.182544 | 566.465957 | normal |
| momentum | 4 | 0.556174 | 0.125869 | 566.401064 | normal |
| momentum | 5 | 0.403231 | 0.095073 | 566.809574 | normal |
| short_term_reversal | 1 | -0.229594 | -0.060127 | 570.538679 | normal |
| short_term_reversal | 2 | 0.787846 | 0.148122 | 569.952830 | normal |
| short_term_reversal | 3 | 1.014054 | 0.181105 | 569.950943 | normal |
| short_term_reversal | 4 | 0.968915 | 0.174758 | 569.783019 | normal |
| short_term_reversal | 5 | 0.902077 | 0.165152 | 570.294340 | normal |
| trend | 1 | 1.248810 | 0.236777 | 567.661811 | normal |
| trend | 2 | 0.959744 | 0.192951 | 567.050989 | normal |
| trend | 3 | 0.745628 | 0.157301 | 567.063476 | normal |
| trend | 4 | 0.682610 | 0.146196 | 567.050989 | normal |
| trend | 5 | -0.087775 | -0.023802 | 567.473465 | normal |
| volatility | 1 | 0.145927 | 0.034225 | 569.399020 | normal |
| volatility | 2 | 0.783606 | 0.153681 | 568.774510 | normal |
| volatility | 3 | 1.001669 | 0.187030 | 568.788235 | normal |
| volatility | 4 | 0.905549 | 0.172685 | 568.774510 | normal |
| volatility | 5 | 0.719762 | 0.143338 | 569.187255 | normal |

## 6. 单因子 top-K 回测

每次只启用一个因子，检查到底是哪个因子贡献或拖累组合。

| factor | total_return | benchmark_return | excess_return | annual_return | sharpe | max_drawdown | turnover | total_cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liquidity | 0.026089 | 0.271386 | -0.245297 | 0.007766 | 0.143264 | -0.355759 | 23.562688 | 20193.600830 |
| momentum | -0.143962 | 0.271386 | -0.415348 | -0.045615 | -0.067276 | -0.315126 | 30.007277 | 24889.063760 |
| short_term_reversal | 0.066418 | 0.271386 | -0.204968 | 0.019502 | 0.200301 | -0.248736 | 58.229064 | 50037.406780 |
| trend | -0.081267 | 0.271386 | -0.352653 | -0.025137 | 0.061998 | -0.489357 | 37.806700 | 29182.239250 |
| volatility | 0.068334 | 0.271386 | -0.203052 | 0.020052 | 0.227687 | -0.134468 | 25.962674 | 25774.602170 |

## 7. 策略线对比

防守型、进攻型和平衡型策略分别回测，并对 hs300/csi500/csi1000 输出相对表现。防守策略主要看回撤、beta 和下跌捕获；进攻策略主要看超额、IR 和上涨捕获。

| strategy | benchmark | weighting | total_return | excess_return | sharpe | information_ratio | beta | up_capture | down_capture | monthly_win_rate_vs_benchmark | evaluation_class | acceptance_pass |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| reversal_low_vol | hs300 | equal_weight | 0.027024 | -0.244362 | 0.140652 | -0.357904 | 0.687593 | 0.615090 | 0.644446 | 0.452381 | return_seeking | False |
| reversal_low_vol | csi500 | equal_weight | 0.027024 | -0.457713 | 0.140652 | -0.701981 | 0.597037 | 0.562143 | 0.610343 | 0.500000 | return_seeking | False |
| reversal_low_vol | csi1000 | equal_weight | 0.027024 | -0.341889 | 0.140652 | -0.611528 | 0.581124 | 0.570360 | 0.606476 | 0.476190 | return_seeking | False |
| defensive_low_vol | hs300 | inverse_vol_weight | 0.055463 | -0.215923 | 0.197960 | -0.500378 | 0.445367 | 0.373969 | 0.384932 | 0.547619 | defensive | True |
| defensive_low_vol | csi500 | inverse_vol_weight | 0.055463 | -0.429274 | 0.197960 | -0.689875 | 0.306661 | 0.231743 | 0.241545 | 0.547619 | defensive | True |
| defensive_low_vol | csi1000 | inverse_vol_weight | 0.055463 | -0.313450 | 0.197960 | -0.523604 | 0.260337 | 0.199004 | 0.201454 | 0.523810 | defensive | True |
| offensive_momentum | hs300 | equal_weight | -0.081730 | -0.353116 | 0.015537 | -0.431761 | 0.847594 | 0.811883 | 0.887466 | 0.333333 | return_seeking | False |
| offensive_momentum | csi500 | equal_weight | -0.081730 | -0.566467 | 0.015537 | -0.834660 | 0.783072 | 0.773488 | 0.869755 | 0.452381 | return_seeking | False |
| offensive_momentum | csi1000 | equal_weight | -0.081730 | -0.450643 | 0.015537 | -0.811176 | 0.767863 | 0.759343 | 0.832697 | 0.309524 | return_seeking | False |
| balanced_multi_factor | hs300 | equal_weight | -0.150163 | -0.421549 | -0.133323 | -0.663495 | 0.710191 | 0.668416 | 0.764789 | 0.428571 | return_seeking | False |
| balanced_multi_factor | csi500 | equal_weight | -0.150163 | -0.634900 | -0.133323 | -1.053907 | 0.647095 | 0.621250 | 0.725013 | 0.476190 | return_seeking | False |
| balanced_multi_factor | csi1000 | equal_weight | -0.150163 | -0.519076 | -0.133323 | -0.925898 | 0.603237 | 0.610138 | 0.692227 | 0.333333 | return_seeking | False |

## 8. Market Regime Performance

Default-strategy returns are split by benchmark trend, volatility, and up/down months. Defensive profiles should be read through drawdown and down-capture; offensive and balanced profiles should be read through excess return and IR.

| benchmark | regime | sample_days | strategy_return | benchmark_return | excess_return | sharpe | information_ratio | max_drawdown | win_rate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| csi1000 | benchmark_above_ma120 | 444 | 0.230159 | 1.267687 | -1.037528 | 0.692163 | -1.990321 | -0.150307 | 0.509009 |
| csi1000 | benchmark_below_ma120 | 395 | -0.165129 | -0.382686 | 0.217557 | -0.483472 | 1.147301 | -0.276563 | 0.483544 |
| csi1000 | high_vol_market | 420 | 0.050257 | 0.445740 | -0.395483 | 0.244612 | -1.028269 | -0.158590 | 0.497619 |
| csi1000 | low_vol_market | 419 | -0.022121 | -0.031724 | 0.009603 | -0.023149 | 0.027747 | -0.219784 | 0.496420 |
| csi1000 | up_month | 428 | 0.688903 | 2.206233 | -1.517330 | 1.829683 | -2.095312 | -0.132609 | 0.535047 |
| csi1000 | down_month | 411 | -0.391899 | -0.563389 | 0.171491 | -1.306142 | 1.386250 | -0.415836 | 0.457421 |
| csi500 | benchmark_above_ma120 | 466 | 0.189203 | 1.468156 | -1.278953 | 0.565435 | -2.172485 | -0.150307 | 0.517167 |
| csi500 | benchmark_below_ma120 | 373 | -0.136376 | -0.389064 | 0.252688 | -0.415533 | 1.527344 | -0.276357 | 0.471850 |
| csi500 | high_vol_market | 420 | -0.072025 | 0.331351 | -0.403376 | -0.058384 | -1.061468 | -0.173482 | 0.490476 |
| csi500 | low_vol_market | 419 | 0.106736 | 0.132597 | -0.025861 | 0.521130 | -0.125860 | -0.176797 | 0.503580 |
| csi500 | up_month | 387 | 0.631335 | 2.244636 | -1.613301 | 1.869192 | -2.461259 | -0.132609 | 0.527132 |
| csi500 | down_month | 452 | -0.370440 | -0.535269 | 0.164829 | -1.114702 | 1.113548 | -0.395222 | 0.471239 |
| hs300 | benchmark_above_ma120 | 526 | 0.238223 | 0.727911 | -0.489688 | 0.624246 | -0.885872 | -0.150307 | 0.520913 |
| hs300 | benchmark_below_ma120 | 313 | -0.170566 | -0.261115 | 0.090549 | -0.636170 | 0.670038 | -0.304884 | 0.456869 |
| hs300 | high_vol_market | 420 | 0.057666 | 0.476753 | -0.419087 | 0.262047 | -0.970059 | -0.215849 | 0.514286 |
| hs300 | low_vol_market | 419 | -0.028972 | -0.135450 | 0.106478 | -0.056510 | 0.568137 | -0.255375 | 0.479714 |
| hs300 | up_month | 411 | 0.527413 | 1.256165 | -0.728753 | 1.566110 | -1.478146 | -0.132609 | 0.532847 |
| hs300 | down_month | 428 | -0.327605 | -0.434116 | 0.106511 | -0.972757 | 0.641635 | -0.373836 | 0.462617 |

## 8. 参数网格样本内/样本外

所有参数组合都会输出样本内和样本外结果。不要只看最优组合，应关注参数区域是否稳定。

| top_k | rebalance | weighting | momentum_window | skip_window | is_total_return | oos_total_return | is_sharpe | oos_sharpe | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 30 | M | equal_weight | 120 | 5 | -0.049200 | 0.142346 | -0.028201 | 0.556097 | ok |
| 30 | M | equal_weight | 60 | 5 | 0.010511 | 0.089306 | 0.119822 | 0.424205 | ok |
| 30 | M | inverse_vol_weight | 120 | 5 | -0.041408 | 0.085353 | -0.027470 | 0.415124 | ok |
| 30 | M | inverse_vol_weight | 120 | 20 | 0.033860 | 0.077055 | 0.180575 | 0.377096 | ok |
| 30 | M | equal_weight | 120 | 20 | 0.039903 | 0.070535 | 0.195734 | 0.341094 | ok |
| 50 | M | equal_weight | 60 | 5 | 0.035243 | 0.050596 | 0.184951 | 0.299677 | ok |
| 30 | M | inverse_vol_weight | 60 | 20 | 0.042344 | 0.050388 | 0.201936 | 0.284837 | ok |
| 50 | M | equal_weight | 120 | 5 | -0.022480 | 0.045499 | 0.022298 | 0.272761 | ok |
| 30 | M | inverse_vol_weight | 60 | 5 | 0.015379 | 0.026827 | 0.126696 | 0.207363 | ok |
| 50 | M | equal_weight | 120 | 20 | -0.006116 | 0.019845 | 0.075996 | 0.181636 | ok |
| 50 | M | inverse_vol_weight | 60 | 20 | 0.015288 | 0.018747 | 0.128572 | 0.173899 | ok |
| 50 | M | equal_weight | 60 | 20 | 0.022404 | 0.017168 | 0.151724 | 0.172090 | ok |
| 30 | M | equal_weight | 60 | 20 | 0.046454 | 0.010267 | 0.211414 | 0.160325 | ok |
| 50 | M | inverse_vol_weight | 120 | 20 | -0.011349 | 0.009928 | 0.052258 | 0.142325 | ok |
| 50 | M | inverse_vol_weight | 60 | 5 | 0.050802 | -0.002372 | 0.236259 | 0.075884 | ok |
| 50 | M | inverse_vol_weight | 120 | 5 | -0.024435 | -0.022715 | 0.004036 | -0.002708 | ok |

## 9. Rolling OOS 固定参数评估

这一节保留原固定参数滚动样本外评估，作用是检查当前参数在不同窗口的稳定性；它不是训练窗口选参。

| train_months | test_months | test_start | test_end | oos_total_return | oos_sharpe | oos_max_drawdown | oos_information_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | 3 | 2023-01-04 | 2023-04-04 | -0.023021 | -0.838292 | -0.056634 | -2.404935 |
| 12 | 3 | 2023-04-04 | 2023-07-04 | 0.037011 | 1.739730 | -0.025545 | 2.992317 |
| 12 | 3 | 2023-07-04 | 2023-10-04 | -0.014389 | -0.526453 | -0.041943 | 1.154937 |
| 12 | 3 | 2023-10-04 | 2024-01-04 | -0.000979 | -0.148971 | -0.035081 | 3.731931 |
| 12 | 3 | 2024-01-04 | 2024-04-04 | 0.084372 | 1.849525 | -0.069026 | 0.595744 |
| 12 | 3 | 2024-04-04 | 2024-07-04 | -0.089958 | -2.042548 | -0.100982 | -1.348658 |
| 12 | 3 | 2024-07-04 | 2024-10-04 | 0.074747 | 2.020628 | -0.059655 | -2.534806 |
| 12 | 3 | 2024-10-04 | 2025-01-04 | -0.126876 | -2.978552 | -0.137839 | -1.776501 |
| 12 | 3 | 2025-01-04 | 2025-04-04 | 0.078787 | 1.826397 | -0.054344 | 1.499375 |
| 12 | 3 | 2025-04-04 | 2025-07-04 | 0.038318 | 2.049366 | -0.023060 | 0.096408 |
| 12 | 3 | 2025-07-04 | 2025-10-04 | 0.078475 | 2.017386 | -0.060870 | -2.131936 |
| 12 | 3 | 2025-10-04 | 2026-01-04 | 0.007314 | 0.378168 | -0.065823 | 0.355470 |
| 12 | 3 | 2026-01-04 | 2026-04-04 | -0.040494 | -0.528431 | -0.120071 | 0.477690 |
| 12 | 3 | 2026-04-04 | 2026-06-24 | -0.112461 | -3.609025 | -0.135293 | -5.201257 |
| 12 | 6 | 2023-01-04 | 2023-07-04 | -0.029193 | -0.380150 | -0.114455 | -0.453826 |
| 12 | 6 | 2023-07-04 | 2024-01-04 | -0.018765 | -0.373753 | -0.058015 | 2.221002 |
| 12 | 6 | 2024-01-04 | 2024-07-04 | -0.010638 | -0.015661 | -0.102057 | -0.297697 |
| 12 | 6 | 2024-07-04 | 2025-01-04 | -0.042444 | -0.351150 | -0.139074 | -1.609166 |
| 12 | 6 | 2025-01-04 | 2025-07-04 | 0.106642 | 0.933792 | -0.180175 | 0.696584 |
| 12 | 6 | 2025-07-04 | 2026-01-04 | 0.102041 | 1.240165 | -0.076352 | -0.647608 |

## 10. Walk-forward Selection

- 平均 OOS 收益：`-0.038730`
- 平均 OOS Sharpe：`-0.482306`
- 平均 OOS IR：`-1.117543`
- 正收益窗口占比：`33.33%`
- 跑赢 benchmark 窗口占比：`0.00%`
- 最差 OOS 窗口：`2026-01-12` 到 `2026-06-24`，收益 `-0.100342`
- 被选择最多的策略：`reversal_low_vol`

| train_start | train_end | test_start | test_end | selected_strategy | selected_top_k | selected_weighting | train_score | test_total_return | test_excess_return | test_sharpe | test_ir | test_max_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2022-01-04 | 2023-01-04 | 2023-01-05 | 2023-07-05 | reversal_low_vol | 50 | equal_weight | 1.125834 | -0.030424 | -0.005283 | -0.399395 | -0.343197 | -0.114455 |
| 2023-07-06 | 2024-07-05 | 2024-07-08 | 2025-01-08 | defensive_low_vol | 30 | inverse_vol_weight | 1.513747 | 0.014575 | -0.099323 | 0.257152 | -1.115381 | -0.082079 |
| 2025-01-09 | 2026-01-09 | 2026-01-12 | 2026-06-24 | reversal_low_vol | 30 | inverse_vol_weight | 1.210576 | -0.100342 | -0.132305 | -1.304676 | -1.894051 | -0.117246 |

## 11. 暴露诊断

- 平均 beta to hs300：`0.701362`
- 平均 beta to csi500：`0.639678`
- 平均 beta to csi1000：`0.613108`
- 平均持仓波动率：`0.501405`
- 平均行业 top1 权重：`0.403854`
- 平均行业 top3 权重：`0.517863`
- 平均现金权重：`0.281862`
- 市值字段可用：`False`

## 12. 结论使用方式

1. 先看 benchmark 是否是真实数据。
2. 检查股票池模式和 possible_selection_bias。
3. 再看单因子 Rank IC 是否长期显著偏离 0。
4. 检查分组收益是否具备单调性。
5. 对比单因子回测和策略线对比，找出收益来源或拖累项。
6. 最后才看参数网格和 walk-forward selection，且必须同时看样本外和最差窗口。

详细 CSV 输出见同目录下的 `universe_diagnostics.csv`、`daily_universe_size.csv`、`strategy_comparison.csv`、`regime_performance.csv`、`walk_forward_selection.csv`、`exposure_report.csv`、`factor_ic.csv`、`factor_group_returns.csv`、`single_factor_backtests.csv`、`parameter_grid.csv`。
