"""Markdown report for research diagnostics."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ashare_quant.config import AppConfig


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6f}"
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _table(frame: pd.DataFrame, columns: list[str], limit: int | None = None) -> list[str]:
    if frame.empty:
        return ["暂无数据。"]
    shown = frame.head(limit) if limit else frame
    lines = [
        "| " + " | ".join(columns) + " |",
        "| " + " | ".join("---" for _ in columns) + " |",
    ]
    for _, row in shown.iterrows():
        lines.append("| " + " | ".join(_fmt(row.get(col, "")) for col in columns) + " |")
    return lines


def write_research_report(
    output_dir: str | Path,
    config: AppConfig,
    benchmark_summary: pd.DataFrame,
    ic_summary: pd.DataFrame,
    group_summary: pd.DataFrame,
    single_factor_results: pd.DataFrame,
    parameter_grid: pd.DataFrame,
    industry_fallback_rate: float = 1.0,
    walk_forward: pd.DataFrame | None = None,
    walk_forward_selection: pd.DataFrame | None = None,
    universe_diagnostics: pd.DataFrame | None = None,
    strategy_comparison: pd.DataFrame | None = None,
    exposure_report: pd.DataFrame | None = None,
) -> None:
    """Write a Chinese research diagnostics report."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# 研究诊断报告",
        "",
        "本报告用于诊断当前多因子策略是否存在可验证的 alpha 来源，而不是证明策略可以实盘盈利。",
        "",
        "## 1. 当前配置",
        "",
        f"- 数据源：`{config.data.provider}`，仅使用真实数据",
        f"- 回测区间：`{config.data.start_date}` 到 `{config.data.end_date}`",
        f"- 股票池模式：`{config.data.universe_mode}`，top_n：`{config.data.universe_top_n}`，liquidity_window：`{config.data.universe_liquidity_window}`",
        f"- 候选股票源：`{config.data.candidate_source}`",
        f"- possible_selection_bias：`{_possible_bias(universe_diagnostics)}`",
        f"- 策略名称：`{config.strategy.name}`",
        f"- 默认 top_k：`{config.strategy.top_k}`",
        f"- 默认调仓频率：`{config.strategy.rebalance_frequency}`",
        f"- 默认权重方式：`{config.strategy.weighting}`",
        f"- industry_momentum fallback rate：`{industry_fallback_rate:.2%}`",
        f"- industry_momentum low confidence：`{industry_fallback_rate > 0.20}`",
        f"- quality_factor_available：`False`，value_factor_available：`False`",
        "",
        "## 2. 股票池诊断",
        "",
        "动态股票池只使用信号日及之前的滚动成交额、ST、停牌、上市天数等字段。若使用 current_snapshot，则候选股票集合可能来自当前流动性快照，报告会标记选择偏差风险。",
        "",
        *_universe_summary(universe_diagnostics),
        "",
        "## 3. Benchmark 对比",
        "",
        "Benchmark 仅使用 AKShare 真实指数数据；如果真实指数不可用，研究诊断会失败而不是生成模拟数据。",
        "",
        *_table(benchmark_summary, ["benchmark", "benchmark_name", "source", "benchmark_return"]),
        "",
        "## 4. 因子 Rank IC",
        "",
        "Rank IC 衡量因子排序与未来收益排序的 Spearman 相关性。长期接近 0 说明排序能力弱；方向不稳定说明因子不稳。波动率因子按“低波动更好”做了方向调整。",
        "",
        *_table(ic_summary, ["factor", "horizon", "ic_mean", "ic_std", "icir", "positive_ic_ratio", "observations", "avg_count"]),
        "",
        "## 5. 因子分组收益",
        "",
        "将股票按因子分成 5 组。有效因子通常应表现为高分组收益稳定高于低分组收益。波动率因子的高分组表示低波动股票。",
        "",
        *_table(group_summary, ["factor", "group", "total_return", "annual_return", "avg_group_size", "confidence"]),
        "",
        "## 6. 单因子 top-K 回测",
        "",
        "每次只启用一个因子，检查到底是哪个因子贡献或拖累组合。",
        "",
        *_table(
            single_factor_results,
            [
                "factor",
                "total_return",
                "benchmark_return",
                "excess_return",
                "annual_return",
                "sharpe",
                "max_drawdown",
                "turnover",
                "total_cost",
            ],
        ),
        "",
        "## 7. 策略线对比",
        "",
        "防守型、进攻型和平衡型策略分别回测，并对 hs300/csi500/csi1000 输出相对表现。防守策略主要看回撤、beta 和下跌捕获；进攻策略主要看超额、IR 和上涨捕获。",
        "",
        *_table(
            strategy_comparison if strategy_comparison is not None else pd.DataFrame(),
            [
                "strategy",
                "benchmark",
                "weighting",
                "total_return",
                "excess_return",
                "sharpe",
                "information_ratio",
                "beta",
                "up_capture",
                "down_capture",
                "monthly_win_rate_vs_benchmark",
            ],
        ),
        "",
        "## 8. 参数网格样本内/样本外",
        "",
        "所有参数组合都会输出样本内和样本外结果。不要只看最优组合，应关注参数区域是否稳定。",
        "",
        *_table(
            parameter_grid,
            [
                "top_k",
                "rebalance",
                "weighting",
                "momentum_window",
                "skip_window",
                "is_total_return",
                "oos_total_return",
                "is_sharpe",
                "oos_sharpe",
                "status",
            ],
            limit=20,
        ),
        "",
        "## 9. Rolling OOS 固定参数评估",
        "",
        "这一节保留原固定参数滚动样本外评估，作用是检查当前参数在不同窗口的稳定性；它不是训练窗口选参。",
        "",
        *_table(
            walk_forward if walk_forward is not None else pd.DataFrame(),
            [
                "train_months",
                "test_months",
                "test_start",
                "test_end",
                "oos_total_return",
                "oos_sharpe",
                "oos_max_drawdown",
                "oos_information_ratio",
            ],
            limit=20,
        ),
        "",
        "## 10. Walk-forward Selection",
        "",
        *_walk_forward_selection_summary(walk_forward_selection),
        "",
        *_table(
            walk_forward_selection if walk_forward_selection is not None else pd.DataFrame(),
            [
                "train_start",
                "train_end",
                "test_start",
                "test_end",
                "selected_strategy",
                "selected_top_k",
                "selected_weighting",
                "train_score",
                "test_total_return",
                "test_excess_return",
                "test_sharpe",
                "test_ir",
                "test_max_drawdown",
            ],
            limit=20,
        ),
        "",
        "## 11. 暴露诊断",
        "",
        *_exposure_summary(exposure_report),
        "",
        "## 12. 结论使用方式",
        "",
        "1. 先看 benchmark 是否是真实数据。",
        "2. 检查股票池模式和 possible_selection_bias。",
        "3. 再看单因子 Rank IC 是否长期显著偏离 0。",
        "4. 检查分组收益是否具备单调性。",
        "5. 对比单因子回测和策略线对比，找出收益来源或拖累项。",
        "6. 最后才看参数网格和 walk-forward selection，且必须同时看样本外和最差窗口。",
        "",
        "详细 CSV 输出见同目录下的 `universe_diagnostics.csv`、`daily_universe_size.csv`、`strategy_comparison.csv`、`walk_forward_selection.csv`、`exposure_report.csv`、`factor_ic.csv`、`factor_group_returns.csv`、`single_factor_backtests.csv`、`parameter_grid.csv`。",
    ]
    (path / "research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _possible_bias(universe_diagnostics: pd.DataFrame | None) -> bool:
    if universe_diagnostics is None or universe_diagnostics.empty or "possible_selection_bias" not in universe_diagnostics:
        return True
    return bool(universe_diagnostics["possible_selection_bias"].astype(bool).any())


def _universe_summary(universe_diagnostics: pd.DataFrame | None) -> list[str]:
    if universe_diagnostics is None or universe_diagnostics.empty:
        return ["暂无股票池诊断数据。"]
    frame = universe_diagnostics.copy()
    lines = [
        f"- 平均 raw_count：`{frame['raw_count'].mean():.2f}`",
        f"- 平均 eligible_count：`{frame['eligible_count'].mean():.2f}`",
        f"- 平均 selected_universe_count：`{frame['selected_universe_count'].mean():.2f}`",
        f"- 平均 raw_to_top_n_ratio：`{frame['raw_to_top_n_ratio'].mean():.2%}`" if "raw_to_top_n_ratio" in frame else "- 平均 raw_to_top_n_ratio：`暂无`",
        f"- candidate_pool_limited：`{frame['candidate_pool_limited'].astype(bool).any()}`" if "candidate_pool_limited" in frame else "- candidate_pool_limited：`暂无`",
        f"- 平均 industry_coverage_rate：`{frame['industry_coverage_rate'].mean():.2%}`",
        f"- 平均 listed_days_fallback_rate：`{frame['listed_days_fallback_rate'].mean():.2%}`",
        f"- possible_selection_bias：`{frame['possible_selection_bias'].astype(bool).any()}`",
        "",
        *_table(
            frame,
            [
                "date",
                "raw_count",
                "eligible_count",
                "selected_universe_count",
                "configured_top_n",
                "raw_to_top_n_ratio",
                "candidate_pool_limited",
                "candidate_source",
                "industry_coverage_rate",
                "listed_days_fallback_rate",
                "universe_mode",
                "possible_selection_bias",
            ],
            limit=10,
        ),
    ]
    return lines


def _walk_forward_selection_summary(walk_forward_selection: pd.DataFrame | None) -> list[str]:
    if walk_forward_selection is None or walk_forward_selection.empty:
        return ["暂无 walk-forward selection 数据。"]
    frame = walk_forward_selection.copy()
    positive = float((frame["test_total_return"] > 0).mean())
    beat = float((frame["test_excess_return"] > 0).mean()) if "test_excess_return" in frame else 0.0
    worst_idx = frame["test_total_return"].astype(float).idxmin()
    worst = frame.loc[worst_idx]
    most_strategy = frame["selected_strategy"].mode().iloc[0] if not frame["selected_strategy"].mode().empty else ""
    return [
        f"- 平均 OOS 收益：`{frame['test_total_return'].mean():.6f}`",
        f"- 平均 OOS Sharpe：`{frame['test_sharpe'].mean():.6f}`",
        f"- 平均 OOS IR：`{frame['test_ir'].mean():.6f}`",
        f"- 正收益窗口占比：`{positive:.2%}`",
        f"- 跑赢 benchmark 窗口占比：`{beat:.2%}`",
        f"- 最差 OOS 窗口：`{_fmt(worst['test_start'])}` 到 `{_fmt(worst['test_end'])}`，收益 `{worst['test_total_return']:.6f}`",
        f"- 被选择最多的策略：`{most_strategy}`",
    ]


def _exposure_summary(exposure_report: pd.DataFrame | None) -> list[str]:
    if exposure_report is None or exposure_report.empty:
        return ["暂无暴露诊断数据。"]
    frame = exposure_report.copy()
    market_cap_available = bool(frame["market_cap_available"].astype(bool).any()) if "market_cap_available" in frame else False
    return [
        f"- 平均 beta to hs300：`{frame['portfolio_beta_to_hs300'].mean():.6f}`",
        f"- 平均 beta to csi500：`{frame['portfolio_beta_to_csi500'].mean():.6f}`",
        f"- 平均 beta to csi1000：`{frame['portfolio_beta_to_csi1000'].mean():.6f}`",
        f"- 平均持仓波动率：`{frame['avg_stock_volatility'].mean():.6f}`",
        f"- 平均行业 top1 权重：`{frame['industry_weight_top1'].mean():.6f}`",
        f"- 平均行业 top3 权重：`{frame['industry_weight_top3'].mean():.6f}`",
        f"- 平均现金权重：`{frame['cash_weight'].mean():.6f}`",
        f"- 市值字段可用：`{market_cap_available}`",
    ]
