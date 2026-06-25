"""Write JSON, CSV, and chart outputs for a backtest."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from ashare_quant.backtest.result import BacktestResult

METRIC_EXPLANATIONS: dict[str, tuple[str, str]] = {
    "total_return": ("净总收益率", "扣除交易成本后，最终净值相对初始资金的累计收益率。"),
    "gross_total_return": ("毛总收益率", "将累计交易成本加回后的近似累计收益率，用于观察成本拖累。"),
    "annual_return": ("年化收益率", "把回测期净收益按 252 个交易日折算到一年的收益率。"),
    "annual_volatility": ("年化波动率", "每日净收益率标准差按 252 个交易日年化后的波动水平。"),
    "sharpe": ("夏普比率", "年化超额收益相对年化波动的比值；当前版本默认无风险利率为 0。"),
    "max_drawdown": ("最大回撤", "回测期间净值从历史高点到后续低点的最大跌幅。"),
    "calmar": ("Calmar 比率", "年化收益率除以最大回撤绝对值，用于衡量收益和回撤的关系。"),
    "win_rate": ("胜率", "日收益率大于 0 的交易日占比。"),
    "turnover": ("累计换手率", "每日成交金额相对组合权益的换手率累计值。"),
    "average_turnover": ("平均日换手率", "回测期间每日换手率的平均值。"),
    "total_cost": ("累计交易成本", "佣金、印花税、过户费和滑点影响的合计金额。"),
    "benchmark_return": ("基准收益率", "如果提供基准数据，则表示基准在同一时期的累计收益率。"),
    "excess_return": ("超额收益", "策略净收益率减去 benchmark 收益率。"),
    "tracking_error": ("跟踪误差", "策略日收益相对 benchmark 日收益差值的年化波动率。"),
    "information_ratio": ("信息比率", "年化相对收益除以跟踪误差，用于衡量相对收益稳定性。"),
    "beta": ("Beta", "策略收益相对 benchmark 收益的敏感度。"),
    "alpha": ("Alpha", "扣除 beta 暴露后的粗略年化超额收益估计。"),
    "up_capture": ("上涨捕获率", "benchmark 上涨日中，策略平均收益相对 benchmark 平均收益的比例。"),
    "down_capture": ("下跌捕获率", "benchmark 下跌日中，策略平均收益相对 benchmark 平均收益的比例。"),
    "relative_drawdown": ("相对最大回撤", "策略相对 benchmark 净值曲线的最大回撤。"),
    "monthly_win_rate_vs_benchmark": ("月度跑赢率", "策略月收益高于 benchmark 月收益的月份占比。"),
}


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def write_report(
    result: BacktestResult,
    output_dir: str | Path,
    make_plots: bool = True,
    clean_output: bool = True,
) -> None:
    """Persist summary metrics, equity curve, trades, positions, and plots."""
    path = Path(output_dir)
    prepare_output_dir(path, clean=clean_output)

    with (path / "backtest_summary.json").open("w", encoding="utf-8") as fh:
        json.dump(result.metrics, fh, indent=2, ensure_ascii=False, default=_json_default)
    write_metric_explanation(result.metrics, path / "backtest_summary_cn.md")
    result.equity_curve.to_csv(path / "equity_curve.csv", index=False)
    result.trades.to_csv(path / "trades.csv", index=False)
    result.positions.to_csv(path / "positions.csv", index=False)
    write_yearly_performance(result.equity_curve, path / "yearly_performance.csv")
    write_industry_exposure(result.positions, path / "industry_exposure.csv")

    if make_plots and not result.equity_curve.empty:
        write_plots(result.equity_curve, path)


def prepare_output_dir(output_dir: str | Path, clean: bool = True) -> Path:
    """Create the output directory and optionally clear existing contents."""
    path = Path(output_dir)
    path.mkdir(parents=True, exist_ok=True)
    if clean:
        for child in path.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink(missing_ok=True)
    return path


def write_plots(equity_curve: pd.DataFrame, output_dir: str | Path) -> None:
    """Write equity and drawdown PNG charts."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    path = Path(output_dir)
    curve = equity_curve.copy()
    curve["date"] = pd.to_datetime(curve["date"])

    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(curve["date"], curve["net_equity"], label="net")
    ax.plot(curve["date"], curve["gross_equity"], label="gross", alpha=0.8)
    ax.set_title("Equity Curve")
    ax.set_xlabel("Date")
    ax.set_ylabel("Equity")
    ax.legend()
    fig.tight_layout()
    fig.savefig(path / "equity_curve.png", dpi=150)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(10, 3))
    ax.fill_between(curve["date"], curve["drawdown"], 0, alpha=0.35)
    ax.set_title("Drawdown")
    ax.set_xlabel("Date")
    ax.set_ylabel("Drawdown")
    fig.tight_layout()
    fig.savefig(path / "drawdown.png", dpi=150)
    plt.close(fig)


def write_metric_explanation(metrics: dict[str, float], output_path: str | Path) -> None:
    """Write a Chinese Markdown explanation for performance metrics."""
    lines = [
        "# 回测绩效指标说明",
        "",
        "| 指标字段 | 中文名称 | 当前数值 | 含义 |",
        "| --- | --- | ---: | --- |",
    ]
    for key, value in metrics.items():
        name, description = METRIC_EXPLANATIONS.get(key, (key, "暂无说明。"))
        lines.append(f"| `{key}` | {name} | {value:.6f} | {description} |")
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_yearly_performance(equity_curve: pd.DataFrame, output_path: str | Path) -> None:
    """Write yearly compounded returns and max drawdown."""
    if equity_curve.empty:
        pd.DataFrame().to_csv(output_path, index=False)
        return
    data = equity_curve.copy()
    data["date"] = pd.to_datetime(data["date"])
    rows = []
    for year, frame in data.groupby(data["date"].dt.year):
        total_return = frame["net_equity"].iloc[-1] / frame["net_equity"].iloc[0] - 1.0
        drawdown = (frame["net_equity"] / frame["net_equity"].cummax() - 1.0).min()
        rows.append({"year": year, "total_return": total_return, "max_drawdown": drawdown})
    pd.DataFrame(rows).to_csv(output_path, index=False)


def write_industry_exposure(positions: pd.DataFrame, output_path: str | Path) -> None:
    """Write daily industry exposure when industry data is available."""
    if positions.empty or "industry" not in positions.columns or positions["industry"].replace("", pd.NA).dropna().empty:
        pd.DataFrame(columns=["date", "industry", "weight"]).to_csv(output_path, index=False)
        return
    exposure = positions.groupby(["date", "industry"], as_index=False)["weight"].sum()
    exposure.to_csv(output_path, index=False)
