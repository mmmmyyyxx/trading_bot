# A 股量化研究与回测系统 MVP

这是一个面向 A 股日频策略研究的个人量化系统 MVP。项目目标是工程可运行、可测试、可扩展，并尽量避免未来函数；不是投资建议，也不承诺收益。

默认配置只使用 AKShare 真实 A 股日频数据。若 AKShare 不可用且本地没有真实缓存，流程会失败，不再自动生成模拟行情。

```text
读取/生成数据 -> 缓存 -> 因子计算 -> 组合构建 -> 回测 -> 绩效报告 -> 测试
```

## 1. 使用环境

请继续使用你的 DL 环境，不需要创建新环境：

```powershell
D:\Anaconda\envs\DL\python.exe
```

进入项目目录：

```powershell
cd "D:\myx\grade_one\experiments\trading_bot\a_share_quant"
```

## 2. 安装依赖

如果依赖尚未安装，在 DL 环境中执行：

```powershell
D:\Anaconda\envs\DL\python.exe -m pip install -r requirements.txt
```

说明：

- `sqlite` 使用 Python 标准库，不需要额外安装。
- `akshare` 用于真实 A 股日频数据。
- 不要新建 conda/venv 环境，直接在 DL 环境中运行即可。

## 3. 运行测试

```powershell
D:\Anaconda\envs\DL\python.exe -m pytest
```

当前测试覆盖：

- 费用模型
- 绩效指标
- 调仓权重约束
- 无未来函数检查
- 动态流动性股票池诊断
- 命名策略 profile 和 walk-forward selection
- 真实缓存数据完整回测 smoke test

## 4. 下载或生成数据

默认配置优先使用 AKShare 数据，会生成标准化 A 股日频字段并写入 sqlite 缓存：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\download_data.py --config configs\default.yaml
```

输出位置：

```text
data/cache/bars.sqlite
```

如果 AKShare 实时接口不可用，系统可以继续读取已有的真实数据缓存；如果缓存也不存在，则会直接报错。

## 5. 运行回测

```powershell
D:\Anaconda\envs\DL\python.exe scripts\run_backtest.py --config configs\default.yaml
```

支持命令行覆盖配置，例如：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\run_backtest.py --config configs\default.yaml --set strategy.top_k=3 --set strategy.max_weight=0.3
```

## 6. 生成报告

```powershell
D:\Anaconda\envs\DL\python.exe scripts\generate_report.py --config configs\default.yaml
```

报告默认输出到：

```text
reports/
```

包含：

- `backtest_summary.json`：绩效指标
- `backtest_summary_cn.md`：绩效指标中文解释
- `equity_curve.csv`：每日净值、毛净值、回撤、换手、费用
- `trades.csv`：成交记录
- `positions.csv`：每日持仓
- `yearly_performance.csv`：逐年收益和回撤
- `industry_exposure.csv`：行业暴露；若真实数据无行业字段则为空表
- `universe_diagnostics.csv`：股票池构造、可选数量、行业覆盖和偏差标记
- `daily_universe_size.csv`：每个调仓信号日的股票池规模
- `exposure_report.csv`：beta、行业集中度、现金和前十大集中度
- `top_holdings.csv`：每日前十大持仓
- `equity_curve.png`：净值曲线图
- `drawdown.png`：回撤图

## 7. 运行研究诊断

当基础回测跑通后，可以运行研究诊断模块，检查因子是否真的有效：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\run_research.py --config configs\default.yaml
```

研究诊断会输出：

- `research_report.md`：中文研究诊断报告
- `benchmark_summary.csv`：沪深300、中证500、中证1000 对比
- `factor_ic.csv`：因子 Rank IC 汇总
- `factor_ic_daily.csv`：每日 Rank IC 序列
- `factor_group_summary.csv`：因子分组收益汇总
- `factor_group_returns.csv`：因子分组净值序列
- `single_factor_backtests.csv`：单因子 top-K 回测对比
- `parameter_grid.csv`：参数网格样本内/样本外结果
- `rolling_oos_eval.csv` / `walk_forward.csv`：固定参数 rolling OOS 评估
- `walk_forward_selection.csv`：训练窗口选参、下一测试窗口验证
- `strategy_comparison.csv`：防守、进攻、平衡策略相对 hs300/csi500/csi1000 的对比
- `exposure_report.csv`：组合暴露诊断

## 8. 绩效指标中文解释

报告中的核心指标含义如下：

| 指标字段 | 中文名称 | 含义 |
| --- | --- | --- |
| `total_return` | 净总收益率 | 扣除交易成本后，最终净值相对初始资金的累计收益率。 |
| `gross_total_return` | 毛总收益率 | 将累计交易成本加回后的近似累计收益率，用于观察成本拖累。 |
| `annual_return` | 年化收益率 | 把回测期净收益按 252 个交易日折算到一年的收益率。 |
| `annual_volatility` | 年化波动率 | 每日净收益率标准差按 252 个交易日年化后的波动水平。 |
| `sharpe` | 夏普比率 | 年化超额收益相对年化波动的比值；当前默认无风险利率为 0。 |
| `max_drawdown` | 最大回撤 | 回测期间净值从历史高点到后续低点的最大跌幅。 |
| `calmar` | Calmar 比率 | 年化收益率除以最大回撤绝对值，用于衡量收益和回撤的关系。 |
| `win_rate` | 胜率 | 日收益率大于 0 的交易日占比。 |
| `turnover` | 累计换手率 | 每日成交金额相对组合权益的换手率累计值。 |
| `average_turnover` | 平均日换手率 | 回测期间每日换手率的平均值。 |
| `total_cost` | 累计交易成本 | 佣金、印花税、过户费和滑点影响的合计金额。 |
| `benchmark_return` | 基准收益率 | 如果提供基准数据，则表示基准在同一时期的累计收益率。 |

每次生成报告时，系统也会写出：

```text
reports/backtest_summary_cn.md
```

## 9. 主要配置

配置文件：

```text
configs/default.yaml
```

常用参数：

- `data.provider`：数据源，默认 `akshare`
- `data.adjust`：复权方式，默认 `qfq`
- `data.universe_mode`：`fixed_symbols`、`current_snapshot` 或 `dynamic_liquidity`
- `data.candidate_source`：候选下载源，`cache`、`akshare_metadata` 或 `current_snapshot`
- `data.universe_top_n`：动态股票池最多保留数量
- `data.universe_liquidity_window`：动态股票池滚动成交额窗口
- `data.universe_min_amount`：动态股票池最低平均成交额
- `data.min_listed_days`：上市最少交易日
- `data.min_amount`：最低成交额过滤
- `strategy.name`：`defensive_low_vol`、`offensive_momentum` 或 `balanced_multi_factor`
- `strategy.top_k`：每次选股数量
- `strategy.weighting`：`equal_weight` 或 `inverse_vol_weight`
- `strategy.max_weight`：单票最大权重
- `backtest.initial_cash`：初始资金
- `cost.commission_rate`：佣金
- `cost.stamp_tax_rate`：印花税
- `cost.transfer_fee_rate`：过户费
- `cost.slippage_bps`：滑点，单位 bps

## 10. 项目结构

```text
a_share_quant/
  requirements.txt
  README.md
  method.md
  configs/default.yaml
  scripts/
    download_data.py
    run_backtest.py
    generate_report.py
    run_research.py
  src/ashare_quant/
    data/
    factors/
    portfolio/
    backtest/
    strategy/
    research/
    report/
    utils/
  tests/
  reports/
```

## 11. 当前局限

- AKShare adapter 为 MVP 级别实现，真实环境中需要进一步校验字段和接口稳定性。
- 指数成分历史、退市历史、真实停牌/ST 历史暂未完整接入。
- `dynamic_liquidity` 避免调仓日使用未来成交额，但如果本地缓存候选股票数量小于 `universe_top_n`，`universe_diagnostics.csv` 会通过 `candidate_pool_limited` 和 `raw_to_top_n_ratio` 标记候选池容量限制。
- 扩展候选缓存时可以显式使用 AKShare 元数据股票列表，而不是当前成交额快照：

```powershell
D:\Anaconda\envs\DL\python.exe scripts\download_data.py --config configs\default.yaml --set data.candidate_source=akshare_metadata --set data.max_symbols=800
```

- 当前不接入实盘或 paper trading 下单接口。
