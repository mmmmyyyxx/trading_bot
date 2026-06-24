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
    momentum: 0.35
    trend: 0.25
    volatility: 0.25
    liquidity: 0.15
```

注意：波动率因子在标准化后取反，因此低波动股票得分更高。

## 6. 调仓逻辑

当前策略为月频多因子轮动：

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
D:\conda\envs_dirs\DL\python.exe scripts\run_research.py --config configs\default.yaml
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

当前参数网格包括：

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

## 14. 后续扩展方向

建议按以下顺序扩展：

1. 接入真实 AKShare 数据并校验字段。
2. 增加真实指数成分历史和交易日历。
3. 增加前复权、后复权、不复权的一致性校验。
4. 增加样本内/样本外和 walk-forward 测试。
5. 增加行业中性、市值中性、风险暴露控制。
6. 接入基本面数据，补充质量和价值因子。
7. 在研究稳定后，再扩展 paper trading。
