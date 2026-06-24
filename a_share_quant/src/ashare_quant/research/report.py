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
        f"- 默认 top_k：`{config.strategy.top_k}`",
        f"- 默认调仓频率：`{config.strategy.rebalance_frequency}`",
        f"- 默认权重方式：`{config.strategy.weighting}`",
        "",
        "## 2. Benchmark 对比",
        "",
        "Benchmark 仅使用 AKShare 真实指数数据；如果真实指数不可用，研究诊断会失败而不是生成模拟数据。",
        "",
        *_table(benchmark_summary, ["benchmark", "benchmark_name", "source", "benchmark_return"]),
        "",
        "## 3. 因子 Rank IC",
        "",
        "Rank IC 衡量因子排序与未来收益排序的 Spearman 相关性。长期接近 0 说明排序能力弱；方向不稳定说明因子不稳。波动率因子按“低波动更好”做了方向调整。",
        "",
        *_table(ic_summary, ["factor", "horizon", "ic_mean", "ic_std", "icir", "positive_ic_ratio", "observations", "avg_count"]),
        "",
        "## 4. 因子分组收益",
        "",
        "将股票按因子分成 5 组。有效因子通常应表现为高分组收益稳定高于低分组收益。波动率因子的高分组表示低波动股票。",
        "",
        *_table(group_summary, ["factor", "group", "total_return", "annual_return", "avg_group_size", "confidence"]),
        "",
        "## 5. 单因子 top-K 回测",
        "",
        "每次只启用一个因子，检查到底是哪个因子贡献或拖累组合。",
        "",
        *_table(
            single_factor_results,
            ["factor", "total_return", "annual_return", "sharpe", "max_drawdown", "turnover", "total_cost"],
        ),
        "",
        "## 6. 参数网格样本内/样本外",
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
        "## 7. 结论使用方式",
        "",
        "1. 先看 benchmark 是否是真实数据。",
        "2. 再看单因子 Rank IC 是否长期显著偏离 0。",
        "3. 检查分组收益是否具备单调性。",
        "4. 对比单因子回测，找出拖累项。",
        "5. 最后才看参数网格，且必须同时看样本外表现。",
        "",
        "详细 CSV 输出见同目录下的 `factor_ic.csv`、`factor_group_returns.csv`、`single_factor_backtests.csv`、`parameter_grid.csv`。",
    ]
    (path / "research_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
