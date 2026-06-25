# 研究诊断报告

本报告用于诊断当前多因子策略是否存在可验证的 alpha 来源，而不是证明策略可以实盘盈利。

## 1. 当前配置

- 数据源：`akshare`，仅使用真实数据
- 回测区间：`2024-06-01` 到 `2026-06-24`
- 股票池模式：`dynamic_liquidity`，top_n：`500`，liquidity_window：`20`
- 候选股票源：`cache`
- possible_selection_bias：`False`
- 策略名称：`defensive_low_vol`
- 默认 top_k：`50`
- 默认调仓频率：`M`
- 默认权重方式：`inverse_vol_weight`
- industry_momentum fallback rate：`0.00%`
- industry_momentum low confidence：`False`
- quality_factor_available：`False`，value_factor_available：`False`

## 2. 股票池诊断

动态股票池只使用信号日及之前的滚动成交额、ST、停牌、上市天数等字段。若使用 current_snapshot，则候选股票集合可能来自当前流动性快照，报告会标记选择偏差风险。

- 平均 raw_count：`299.48`
- 平均 eligible_count：`262.68`
- 平均 selected_universe_count：`262.68`
- 平均 raw_to_top_n_ratio：`59.90%`
- candidate_pool_limited：`True`
- 平均 industry_coverage_rate：`100.00%`
- 平均 listed_days_fallback_rate：`0.00%`
- possible_selection_bias：`False`

| date | raw_count | eligible_count | selected_universe_count | configured_top_n | raw_to_top_n_ratio | candidate_pool_limited | candidate_source | industry_coverage_rate | listed_days_fallback_rate | universe_mode | possible_selection_bias |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-28 | 300 | 183 | 183 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-07-31 | 300 | 174 | 174 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-08-30 | 300 | 185 | 185 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-09-30 | 300 | 227 | 227 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-10-31 | 300 | 294 | 294 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-11-29 | 299 | 293 | 293 | 500 | 0.598000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2024-12-31 | 298 | 289 | 289 | 500 | 0.596000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2025-01-27 | 300 | 245 | 245 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2025-02-28 | 300 | 261 | 261 | 500 | 0.600000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |
| 2025-03-31 | 299 | 273 | 273 | 500 | 0.598000 | True | cache | 1.000000 | 0.000000 | dynamic_liquidity | False |

## 3. Benchmark 对比

Benchmark 仅使用 AKShare 真实指数数据；如果真实指数不可用，研究诊断会失败而不是生成模拟数据。

| benchmark | benchmark_name | source | benchmark_return |
| --- | --- | --- | --- |
| csi1000 | 中证1000 | akshare | 0.663976 |
| csi500 | 中证500 | akshare | 0.676682 |
| hs300 | 沪深300 | akshare | 0.377366 |

## 4. 因子 Rank IC

Rank IC 衡量因子排序与未来收益排序的 Spearman 相关性。长期接近 0 说明排序能力弱；方向不稳定说明因子不稳。波动率因子按“低波动更好”做了方向调整。

| factor | horizon | ic_mean | ic_std | icir | positive_ic_ratio | observations | avg_count |
| --- | --- | --- | --- | --- | --- | --- | --- |
| composite_score | 1 | 0.038776 | 0.204853 | 0.189289 | 0.566210 | 438 | 299.303653 |
| composite_score | 5 | 0.051160 | 0.183426 | 0.278914 | 0.615207 | 434 | 299.297235 |
| composite_score | 20 | 0.068878 | 0.184319 | 0.373690 | 0.677804 | 419 | 299.272076 |
| industry_momentum | 1 | -0.005749 | 0.132132 | -0.043507 | 0.486034 | 358 | 299.298883 |
| industry_momentum | 5 | -0.013789 | 0.130642 | -0.105548 | 0.435028 | 354 | 299.290960 |
| industry_momentum | 20 | -0.025858 | 0.121005 | -0.213692 | 0.389381 | 339 | 299.259587 |
| liquidity | 1 | -0.048190 | 0.194697 | -0.247512 | 0.396660 | 479 | 299.475992 |
| liquidity | 5 | -0.079434 | 0.177545 | -0.447401 | 0.336842 | 475 | 299.471579 |
| liquidity | 20 | -0.123260 | 0.181823 | -0.677912 | 0.308696 | 460 | 299.454348 |
| momentum | 1 | -0.004741 | 0.163142 | -0.029062 | 0.488827 | 358 | 299.298883 |
| momentum | 5 | -0.012335 | 0.156284 | -0.078928 | 0.449153 | 354 | 299.290960 |
| momentum | 20 | -0.019740 | 0.143010 | -0.138035 | 0.442478 | 339 | 299.259587 |
| trend | 1 | -0.045965 | 0.159416 | -0.288335 | 0.390501 | 379 | 299.337731 |
| trend | 5 | -0.071783 | 0.159377 | -0.450397 | 0.328000 | 375 | 299.330667 |
| trend | 20 | -0.092941 | 0.158238 | -0.587349 | 0.283333 | 360 | 299.302778 |
| volatility | 1 | 0.037178 | 0.216083 | 0.172055 | 0.557078 | 438 | 299.426941 |
| volatility | 5 | 0.051372 | 0.196674 | 0.261202 | 0.610599 | 434 | 299.421659 |
| volatility | 20 | 0.070646 | 0.196933 | 0.358731 | 0.661098 | 419 | 299.400955 |

## 5. 因子分组收益

将股票按因子分成 5 组。有效因子通常应表现为高分组收益稳定高于低分组收益。波动率因子的高分组表示低波动股票。

| factor | group | total_return | annual_return | avg_group_size | confidence |
| --- | --- | --- | --- | --- | --- |
| composite_score | 1 | 0.297556 | 0.161679 | 59.979452 | normal |
| composite_score | 2 | 0.785126 | 0.395712 | 59.892694 | normal |
| composite_score | 3 | 0.759260 | 0.384040 | 59.568493 | normal |
| composite_score | 4 | 0.594030 | 0.307690 | 59.892694 | normal |
| composite_score | 5 | 0.456345 | 0.241461 | 59.970320 | normal |
| industry_momentum | 1 | -0.000614 | -0.000432 | 59.974860 | normal |
| industry_momentum | 2 | 0.190047 | 0.130292 | 59.899441 | normal |
| industry_momentum | 3 | 0.208597 | 0.142665 | 59.620112 | normal |
| industry_momentum | 4 | 0.104088 | 0.072187 | 59.837989 | normal |
| industry_momentum | 5 | 0.315288 | 0.212775 | 59.966480 | normal |
| liquidity | 1 | 1.136863 | 0.491057 | 59.997912 | normal |
| liquidity | 2 | 0.768100 | 0.349623 | 59.914405 | normal |
| liquidity | 3 | 0.508079 | 0.241275 | 59.653445 | normal |
| liquidity | 4 | 0.124321 | 0.063588 | 59.914405 | normal |
| liquidity | 5 | 0.118303 | 0.060589 | 59.995825 | normal |
| momentum | 1 | 0.026623 | 0.018667 | 59.977654 | normal |
| momentum | 2 | 0.067064 | 0.046752 | 59.902235 | normal |
| momentum | 3 | 0.265319 | 0.180157 | 59.553073 | normal |
| momentum | 4 | 0.102358 | 0.071005 | 59.899441 | normal |
| momentum | 5 | 0.361799 | 0.242807 | 59.966480 | normal |
| trend | 1 | 0.151887 | 0.098580 | 59.994723 | normal |
| trend | 2 | 0.180948 | 0.116932 | 59.881266 | normal |
| trend | 3 | 0.148539 | 0.096456 | 59.593668 | normal |
| trend | 4 | 0.249073 | 0.159370 | 59.881266 | normal |
| trend | 5 | 0.003870 | 0.002571 | 59.986807 | normal |
| volatility | 1 | 0.466455 | 0.246412 | 59.997717 | normal |
| volatility | 2 | 0.722004 | 0.367101 | 59.906393 | normal |
| volatility | 3 | 0.645613 | 0.331872 | 59.621005 | normal |
| volatility | 4 | 0.597330 | 0.309247 | 59.906393 | normal |
| volatility | 5 | 0.419244 | 0.223164 | 59.995434 | normal |

## 6. 单因子 top-K 回测

每次只启用一个因子，检查到底是哪个因子贡献或拖累组合。

| factor | total_return | benchmark_return | excess_return | annual_return | sharpe | max_drawdown | turnover | total_cost |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| liquidity | 0.175795 | 0.283230 | -0.107436 | 0.171375 | 1.020211 | -0.124915 | 7.412641 | 7600.196040 |
| momentum | 0.288794 | 0.283230 | 0.005564 | 0.281213 | 1.294993 | -0.150254 | 10.171471 | 10132.548740 |
| trend | 0.245484 | 0.283230 | -0.037746 | 0.239142 | 1.038302 | -0.159497 | 11.636984 | 11230.066120 |
| volatility | 0.032895 | 0.283230 | -0.250335 | 0.032118 | 0.295592 | -0.119961 | 7.956887 | 7879.082080 |

## 7. 策略线对比

防守型、进攻型和平衡型策略分别回测，并对 hs300/csi500/csi1000 输出相对表现。防守策略主要看回撤、beta 和下跌捕获；进攻策略主要看超额、IR 和上涨捕获。

| strategy | benchmark | weighting | total_return | excess_return | sharpe | information_ratio | beta | up_capture | down_capture | monthly_win_rate_vs_benchmark |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| defensive_low_vol | hs300 | inverse_vol_weight | 0.040192 | -0.243039 | 0.342467 | -1.444003 | 0.481538 | 0.410796 | 0.481761 | 0.461538 |
| defensive_low_vol | csi500 | inverse_vol_weight | 0.040192 | -0.512607 | 0.342467 | -2.138281 | 0.327352 | 0.280062 | 0.350552 | 0.230769 |
| defensive_low_vol | csi1000 | inverse_vol_weight | 0.040192 | -0.408479 | 0.342467 | -1.830144 | 0.334635 | 0.290514 | 0.347996 | 0.230769 |
| offensive_momentum | hs300 | equal_weight | 0.163391 | -0.119840 | 0.861831 | -0.649468 | 0.870659 | 0.858566 | 0.926728 | 0.384615 |
| offensive_momentum | csi500 | equal_weight | 0.163391 | -0.389408 | 0.861831 | -2.340209 | 0.733838 | 0.656431 | 0.775022 | 0.230769 |
| offensive_momentum | csi1000 | equal_weight | 0.163391 | -0.285280 | 0.861831 | -1.834964 | 0.750888 | 0.721553 | 0.823884 | 0.230769 |
| balanced_multi_factor | hs300 | equal_weight | 0.190876 | -0.092354 | 1.040230 | -0.471741 | 0.697407 | 0.719006 | 0.717761 | 0.307692 |
| balanced_multi_factor | csi500 | equal_weight | 0.190876 | -0.361922 | 1.040230 | -1.641927 | 0.555039 | 0.514715 | 0.557954 | 0.307692 |
| balanced_multi_factor | csi1000 | equal_weight | 0.190876 | -0.257795 | 1.040230 | -1.226830 | 0.550550 | 0.547638 | 0.572068 | 0.307692 |

## 8. 参数网格样本内/样本外

所有参数组合都会输出样本内和样本外结果。不要只看最优组合，应关注参数区域是否稳定。

| top_k | rebalance | weighting | momentum_window | skip_window | is_total_return | oos_total_return | is_sharpe | oos_sharpe | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | M | equal_weight | 60 | 20 | 0.138758 | -0.033996 | 2.299487 | -0.257050 | ok |
| 30 | M | equal_weight | 60 | 20 | 0.110681 | -0.060914 | 2.063123 | -0.478062 | ok |
| 50 | M | inverse_vol_weight | 60 | 20 | 0.143485 | -0.060423 | 2.637133 | -0.580811 | ok |
| 30 | M | equal_weight | 120 | 5 | 0.127353 | -0.088177 | 2.321260 | -0.789560 | ok |
| 50 | M | equal_weight | 120 | 5 | 0.173391 | -0.085020 | 3.072251 | -0.803711 | ok |
| 50 | M | equal_weight | 60 | 5 | 0.151899 | -0.086633 | 2.870021 | -0.859439 | ok |
| 30 | M | inverse_vol_weight | 60 | 20 | 0.114786 | -0.088447 | 2.379999 | -0.877753 | ok |
| 30 | M | equal_weight | 60 | 5 | 0.133949 | -0.092427 | 2.371369 | -0.913392 | ok |
| 50 | M | inverse_vol_weight | 120 | 5 | 0.165006 | -0.089788 | 3.147928 | -0.919266 | ok |
| 50 | M | inverse_vol_weight | 60 | 5 | 0.150164 | -0.089594 | 2.938145 | -0.936538 | ok |
| 30 | M | inverse_vol_weight | 120 | 5 | 0.121290 | -0.097018 | 2.391206 | -0.997420 | ok |
| 50 | M | equal_weight | 120 | 20 | 0.164353 | -0.106048 | 3.116553 | -1.000406 | ok |
| 30 | M | inverse_vol_weight | 60 | 5 | 0.126138 | -0.096791 | 2.440697 | -1.022277 | ok |
| 30 | M | equal_weight | 120 | 20 | 0.124925 | -0.111809 | 2.258952 | -1.027305 | ok |
| 50 | M | inverse_vol_weight | 120 | 20 | 0.157435 | -0.102986 | 3.107547 | -1.067073 | ok |
| 30 | M | inverse_vol_weight | 120 | 20 | 0.120930 | -0.108074 | 2.375941 | -1.133523 | ok |

## 9. Rolling OOS 固定参数评估

这一节保留原固定参数滚动样本外评估，作用是检查当前参数在不同窗口的稳定性；它不是训练窗口选参。

| train_months | test_months | test_start | test_end | oos_total_return | oos_sharpe | oos_max_drawdown | oos_information_ratio |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 12 | 3 | 2025-06-03 | 2025-09-03 | 0.088943 | 3.011523 | -0.035373 | -2.375814 |
| 12 | 3 | 2025-09-03 | 2025-12-03 | 0.031928 | 1.403644 | -0.050163 | 0.548810 |
| 12 | 3 | 2025-12-03 | 2026-03-03 | 0.040066 | 1.644962 | -0.030065 | 0.707577 |
| 12 | 3 | 2026-03-03 | 2026-06-03 | -0.033067 | -1.143769 | -0.052789 | -1.712911 |
| 12 | 3 | 2026-06-03 | 2026-06-24 | 0.000000 | 0.000000 | 0.000000 | -0.520629 |
| 12 | 6 | 2025-06-03 | 2025-12-03 | 0.126075 | 2.165242 | -0.050220 | -0.725154 |
| 12 | 6 | 2025-12-03 | 2026-06-03 | -0.013594 | -0.111943 | -0.083040 | -1.423956 |
| 12 | 6 | 2026-06-03 | 2026-06-24 | 0.000000 | 0.000000 | 0.000000 | -0.520629 |
| 24 | 3 | 2026-06-03 | 2026-06-24 | 0.000000 | 0.000000 | 0.000000 | -0.520629 |
| 24 | 6 | 2026-06-03 | 2026-06-24 | 0.000000 | 0.000000 | 0.000000 | -0.520629 |

## 10. Walk-forward Selection

- 平均 OOS 收益：`0.067874`
- 平均 OOS Sharpe：`1.097172`
- 平均 OOS IR：`-1.322043`
- 正收益窗口占比：`100.00%`
- 跑赢 benchmark 窗口占比：`0.00%`
- 最差 OOS 窗口：`2025-06-04` 到 `2025-12-04`，收益 `0.067874`
- 被选择最多的策略：`defensive_low_vol`

| train_start | train_end | test_start | test_end | selected_strategy | selected_top_k | selected_weighting | train_score | test_total_return | test_excess_return | test_sharpe | test_ir | test_max_drawdown |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2024-06-03 | 2025-06-03 | 2025-06-04 | 2025-12-04 | defensive_low_vol | 30 | equal_weight | 1.185793 | 0.067874 | -0.107330 | 1.097172 | -1.322043 | -0.066615 |

## 11. 暴露诊断

- 平均 beta to hs300：`0.547059`
- 平均 beta to csi500：`0.357988`
- 平均 beta to csi1000：`0.359405`
- 平均持仓波动率：`0.207542`
- 平均行业 top1 权重：`0.409515`
- 平均行业 top3 权重：`0.663153`
- 平均现金权重：`0.111998`
- 市值字段可用：`False`

## 12. 结论使用方式

1. 先看 benchmark 是否是真实数据。
2. 检查股票池模式和 possible_selection_bias。
3. 再看单因子 Rank IC 是否长期显著偏离 0。
4. 检查分组收益是否具备单调性。
5. 对比单因子回测和策略线对比，找出收益来源或拖累项。
6. 最后才看参数网格和 walk-forward selection，且必须同时看样本外和最差窗口。

详细 CSV 输出见同目录下的 `universe_diagnostics.csv`、`daily_universe_size.csv`、`strategy_comparison.csv`、`walk_forward_selection.csv`、`exposure_report.csv`、`factor_ic.csv`、`factor_group_returns.csv`、`single_factor_backtests.csv`、`parameter_grid.csv`。
