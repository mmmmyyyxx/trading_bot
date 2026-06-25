# 方法说明

本文说明当前 A 股量化研究与回测系统 MVP 的设计方法、策略逻辑、回测规则和无未来函数约束。

## 1. 系统目标

系统优先解决三个问题：

1. 能在本地离线跑通完整研究流程。
2. 回测逻辑清晰，交易成本和 A 股约束显式建模。
3. 因子、组合、回测、报告模块解耦，方便后续扩展真实数据、机器学习因子和 paper trading。

当前版本不是实盘交易系统，不连接真实券商接口，也不提供收益承诺。

## 2. 数据层

标准行情字段为：

```text
date, symbol, open, high, low, close, volume, amount,
adj_factor, is_paused, is_st, limit_up, limit_down
```

默认数据源为 `AKShareProvider`，只用于获取真实 A 股日频数据。系统不再生成模拟行情；如果 AKShare 不可用且本地没有真实缓存，下载、回测或诊断流程会失败。

AKShare 数据需要包含：

- 停牌标记
- ST 标记
- 涨停价
- 跌停价
- 成交量和成交额

真实数据源：

- `AKShareProvider`
- `TushareProvider` 预留

Tushare token 只从环境变量读取，不写入代码。

## 3. 股票池过滤

股票池过滤由 `data/universe.py` 完成。当前规则包括：

- 剔除 ST 股票
- 剔除停牌股票
- 剔除上市交易日不足 `min_listed_days` 的股票
- 剔除过去窗口平均成交额低于 `min_amount` 的股票

过滤只使用当前信号日及之前已经存在的数据，不读取未来日期信息。

当前支持三种股票池模式：

```text
fixed_symbols：只在配置给定的 symbols 内过滤。
current_snapshot：候选股票集合来自当前快照，适合快速调试，但报告会标记 possible_selection_bias=true。
dynamic_liquidity：每个调仓信号日按过去窗口平均成交额动态选池，默认研究模式。
```

`dynamic_liquidity` 在每个 signal_date 使用 `universe_liquidity_window` 个历史交易日的 `amount` 均值，剔除 ST、停牌、上市天数不足和成交额不足的股票，再按平均成交额选取前 `universe_top_n`。报告会输出：

```text
reports/universe_diagnostics.csv
reports/daily_universe_size.csv
```

需要注意：动态选池解决的是调仓日选股时的成交额未来函数；如果本地缓存本身只包含某个当前快照候选集合，仍应在研究结论中说明候选下载范围的限制。`universe_diagnostics.csv` 会额外输出：

```text
configured_top_n
raw_to_top_n_ratio
selected_to_top_n_ratio
candidate_pool_limited
```

这些字段用于判断候选缓存数量是否小于配置的动态池目标数量。

候选下载源由 `data.candidate_source` 控制：

```text
cache：默认值，研究时使用本地真实缓存中的全部股票，避免无意触发大规模下载。
akshare_metadata：使用 AKShare 股票代码/名称元数据生成候选列表，不按当前成交额排序。
current_snapshot：使用 AKShare 当前 spot 成交额快照，仅适合快速调试，报告会标记 possible_selection_bias=true。
```

扩展候选缓存时可以显式运行：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\download_data.py --config configs\default.yaml --refresh --batch-size 100
```

如果只想先刷新候选元数据而不马上重建整个缓存，也可以显式覆盖：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\download_data.py --config configs\default.yaml --set data.candidate_source=akshare_metadata --set data.max_symbols=3000
```

这一步仍不是历史指数成分或退市全样本，只是避免候选下载阶段直接按当前成交额排序；严格历史全市场研究仍需要后续接入更完整的历史候选集合。

## 4. 因子设计

当前实现四类日频因子。

### 4.1 动量因子

过去 `120` 个交易日收益率，并跳过最近 `20` 个交易日：

```text
momentum_t = close_{t-20} / close_{t-140} - 1
```

跳过最近 20 日是为了降低短期反转噪声。

### 4.2 趋势因子

收盘价相对过去 `120` 日均线的位置：

```text
trend_t = close_t / MA(close, 120)_t - 1
```

数值越高，说明价格越强于中期均线。

### 4.3 波动率因子

过去 `60` 日收益率标准差：

```text
volatility_t = std(return, 60)_t
```

低波动更优，因此综合打分时会反向处理。

### 4.4 流动性因子

过去 `20` 日平均成交额：

```text
liquidity_t = mean(amount, 20)_t
```

成交额越高，流动性越好。

## 5. 横截面标准化和综合打分

每个交易日单独做横截面 z-score：

```text
z_i,t = (factor_i,t - mean(factor_t)) / std(factor_t)
```

综合分数：

```text
score =
  w_momentum  * z_momentum
+ w_trend     * z_trend
- w_volatility* z_volatility
+ w_liquidity * z_liquidity
```

默认权重在 `configs/default.yaml` 中配置：

```yaml
factors:
  weights:
    volatility: 0.60
    industry_momentum: 0.40
    momentum: 0.0
    trend: 0.0
    liquidity: 0.0
```

注意：波动率因子在标准化后取反，因此低波动股票得分更高。

命名策略会覆盖默认因子权重：

```text
defensive_low_vol：0.70 * low_volatility + 0.30 * industry_momentum，默认 inverse_vol_weight。
offensive_momentum：0.70 * industry_momentum + 0.20 * momentum + 0.10 * liquidity，默认 equal_weight。
balanced_multi_factor：0.40 * industry_momentum + 0.40 * low_volatility + 0.20 * trend，默认 equal_weight。
```

当前 `quality.py` 和 `value.py` 仅保留接口占位。由于尚未接入稳定基本面数据，报告中标记：

```text
quality_factor_available = false
value_factor_available = false
```

## 6. 调仓逻辑

当前策略为命名多因子轮动：

1. 每月最后一个交易日收盘后计算因子和股票池。
2. 按综合分数排序。
3. 选择前 `top_k` 只股票。
4. 生成目标权重。
5. 下一交易日开盘执行调仓。

这意味着信号日和交易日严格错开，避免使用当天收盘后才知道的信息在当天成交。

## 7. 权重构建

支持两种权重方式：

### 7.1 等权

```text
weight_i = 1 / N
```

### 7.2 逆波动率加权

```text
weight_i = (1 / volatility_i) / sum(1 / volatility)
```

随后应用单票最大权重约束：

```text
weight_i <= max_weight
```

如果权重被上限截断，剩余部分保留为现金，不强行再分配。

## 8. 回测撮合规则

回测采用日频半事件驱动流程：

1. 读取当日行情。
2. 如果当日有目标权重，则按开盘价生成买卖订单。
3. 先卖后买。
4. 应用停牌、涨跌停和 T+1 限制。
5. 计算手续费、印花税、过户费、滑点。
6. 更新现金、持仓和净值。
7. 用收盘价记录每日权益。

当前默认不允许卖空。

## 9. A 股交易约束

当前初步支持：

- T+1：当天买入的股票当天不可卖出。
- 涨停不可买入。
- 跌停不可卖出。
- 停牌不可交易。
- ST 股票可在股票池过滤阶段剔除。
- 买卖数量按 `lot_size` 向下取整，默认 `100` 股。

## 10. 成本模型

费用全部来自配置文件，不在代码中写死：

```yaml
cost:
  commission_rate: 0.0003
  min_commission: 5.0
  stamp_tax_rate: 0.0005
  transfer_fee_rate: 0.00001
  slippage_bps: 2.0
```

买入成本：

```text
成交金额 + 佣金 + 过户费 + 滑点影响
```

卖出收入：

```text
成交金额 - 佣金 - 印花税 - 过户费 - 滑点影响
```

报告中同时保留：

- 净收益：扣除交易成本后的权益表现
- 毛收益：将累计成本加回后的近似表现

## 11. 绩效指标

当前输出：

| 指标字段 | 中文名称 | 含义 |
| --- | --- | --- |
| `total_return` | 净总收益率 | 扣除交易成本后，最终净值相对初始资金的累计收益率。 |
| `gross_total_return` | 毛总收益率 | 将累计交易成本加回后的近似累计收益率，用于观察成本拖累。 |
| `annual_return` | 年化收益率 | 把回测期净收益按 252 个交易日折算到一年的收益率。 |
| `annual_volatility` | 年化波动率 | 每日净收益率标准差按 252 个交易日年化后的波动水平。 |
| `sharpe` | 夏普比率 | 年化超额收益相对年化波动的比值；当前版本默认无风险利率为 0。 |
| `max_drawdown` | 最大回撤 | 回测期间净值从历史高点到后续低点的最大跌幅。 |
| `calmar` | Calmar 比率 | 年化收益率除以最大回撤绝对值，用于衡量收益和回撤的关系。 |
| `win_rate` | 胜率 | 日收益率大于 0 的交易日占比。 |
| `turnover` | 累计换手率 | 每日成交金额相对组合权益的换手率累计值。 |
| `average_turnover` | 平均日换手率 | 回测期间每日换手率的平均值。 |
| `total_cost` | 累计交易成本 | 佣金、印花税、过户费和滑点影响的合计金额。 |
| `benchmark_return` | 基准收益率 | 如果提供基准数据，则表示基准在同一时期的累计收益率。 |

报告生成时会额外输出中文说明文件：

```text
reports/backtest_summary_cn.md
```

## 12. 无未来函数约束

系统通过以下方式降低未来函数风险：

1. 所有滚动因子只使用当前日期及之前的数据。
2. 调仓信号在信号日收盘后生成。
3. 订单在下一交易日执行。
4. 股票池过滤只使用信号日及以前数据。
5. 测试中包含 no-lookahead 检查：修改未来价格后，过去日期的因子结果不得变化。

## 13. 后续扩展方向

## 13. 研究诊断模块

当前系统新增了研究诊断流水线：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\run_research.py --config configs\default.yaml
```

它用于判断策略是否真的存在 alpha 来源，而不是只看最终回测收益。

### 13.1 Benchmark 对比

系统尝试获取：

- 沪深300
- 中证500
- 中证1000

Benchmark 只使用 AKShare 真实指数数据。如果 AKShare 指数接口不可用，研究诊断会失败，不再生成模拟 benchmark。

### 13.2 Rank IC 分析

对每个因子计算未来 `1`、`5`、`20` 日收益的 Rank IC：

```text
Rank IC = SpearmanCorr(factor_rank_t, future_return_rank_t)
```

输出：

- IC 均值
- IC 标准差
- ICIR
- 正 IC 占比
- 有效样本数量

波动率因子按“低波动更好”调整方向。

### 13.3 因子分组收益

每个交易日按因子把股票分成 5 组：

```text
Group 1 = 低分组
...
Group 5 = 高分组
```

有效因子通常应表现为高分组收益高于低分组收益。波动率因子的高分组表示低波动股票。

### 13.4 单因子回测

系统会分别只启用一个因子做 top-K 回测：

- momentum
- trend
- volatility
- liquidity

这样可以判断组合收益到底来自哪个因子，或者哪个因子在拖累。

### 13.5 参数网格和样本外验证

日常研究参数网格默认使用较小但完整报告的诊断组合，避免每次运行都变成大规模实验。每个实际测试组合都会完整输出样本内和样本外指标，不只报告最优结果。

完整候选可以通过 `run_parameter_grid()` 和 `run_walk_forward_selection()` 的参数显式传入。建议的大规模候选包括：

```text
top_k: [10, 20, 30, 50]
rebalance: [weekly, monthly]
weighting: [equal_weight, inverse_vol_weight]
momentum_window: [60, 120, 180]
skip_window: [5, 20]
```

每个组合都会输出样本内和样本外指标，避免只报告最佳回测。

研究诊断输出文件：

- `reports/research_report.md`
- `reports/benchmark_summary.csv`
- `reports/benchmark_returns.csv`
- `reports/factor_ic.csv`
- `reports/factor_ic_daily.csv`
- `reports/factor_group_summary.csv`
- `reports/factor_group_returns.csv`
- `reports/single_factor_backtests.csv`
- `reports/parameter_grid.csv`

### 13.6 Rolling OOS 与 walk-forward selection

系统区分两类样本外诊断：

```text
rolling_oos_eval：固定当前参数，在滚动 OOS 窗口中评估稳定性。
walk_forward_selection：每个训练窗口内比较候选参数，再把选出的参数固定到下一测试窗口评估。
```

输出文件：

```text
reports/walk_forward.csv
reports/rolling_oos_eval.csv
reports/walk_forward_selection.csv
```

`walk_forward_selection.csv` 至少包含训练窗口、测试窗口、被选择策略、top_k、权重方式、动量窗口、skip、训练评分和测试期收益、超额、Sharpe、IR、回撤、Calmar、beta、上涨/下跌捕获。

### 13.7 策略线和暴露诊断

研究诊断会分别运行：

```text
defensive_low_vol
offensive_momentum
balanced_multi_factor
```

并输出相对 `hs300`、`csi500`、`csi1000` 的收益、超额、IR、beta、up_capture、down_capture 和月度跑赢率：

```text
reports/strategy_comparison.csv
```

暴露诊断输出：

```text
reports/exposure_report.csv
reports/top_holdings.csv
reports/industry_exposure.csv
```

其中包括组合相对三大 benchmark 的 rolling beta、平均持仓波动率、行业 top1/top3 集中度、现金权重和前十大持仓集中度。若没有真实市值字段，则 `market_cap_available=false`。

## 14. 后续扩展方向

建议按以下顺序扩展：

1. 接入历史指数成分或更完整的历史全市场候选集合。
2. 增加真实市值、质量和价值基本面字段，并报告缺失率。
3. 增加前复权、后复权、不复权的一致性校验。
4. 增加行业中性、市值中性、风险暴露控制。
5. 扩展更长历史样本，覆盖 2018-2026 的不同市场阶段。
6. 在研究稳定后，再扩展 paper trading。
