"""Export Qlib Alpha158 workflow artifacts into plain reports."""

from __future__ import annotations

import json
import math
import pickle
import re
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def export_alpha158_results(
    run_dir: str | Path | None = None,
    output_dir: str | Path = "reports/alpha158_hs300",
    mlruns_dir: str | Path = "mlruns",
    bars_path: str | Path | None = None,
    benchmarks_path: str | Path | None = None,
    qrun_log: str | Path | None = None,
    requested_symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Export Qlib run artifacts and return the summary dictionary."""

    run = Path(run_dir) if run_dir else find_latest_qlib_run(mlruns_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    artifacts = run / "artifacts"
    pa = artifacts / "portfolio_analysis"
    sig = artifacts / "sig_analysis"

    metrics = _read_metrics(run / "metrics")
    pred = _load_pickle(artifacts / "pred.pkl")
    label = _load_pickle(artifacts / "label.pkl")
    ic = _load_pickle(sig / "ic.pkl")
    ric = _load_pickle(sig / "ric.pkl")
    port = _load_pickle(pa / "port_analysis_1day.pkl")
    report = _load_pickle(pa / "report_normal_1day.pkl")
    indicator = _load_pickle(pa / "indicator_analysis_1day.pkl")
    indicators = _load_optional_pickle(pa / "indicators_normal_1day.pkl")
    positions = _load_optional_pickle(pa / "positions_normal_1day.pkl")

    _write_frame(port, out / "port_analysis_1day.csv")
    _write_frame(report, out / "report_normal_1day.csv")
    _write_frame(indicator, out / "indicator_analysis_1day.csv")
    if indicators is not None:
        _write_frame(indicators, out / "indicators_normal_1day.csv")
    _write_series(ic, "ic", out / "ic_daily.csv")
    _write_series(ric, "rank_ic", out / "rank_ic_daily.csv")

    pred_label = pred.join(label, how="inner").dropna()
    pred_label.to_csv(out / "pred_label_test.csv")
    group_summary, group_daily = _compute_group_returns(pred_label)
    group_daily.to_csv(out / "factor_group_returns_daily.csv")
    group_summary.to_csv(out / "factor_group_summary.csv")

    bars_summary = _summarize_bars(bars_path)
    requested = requested_symbols or _read_requested_symbols(None)
    if requested and bars_summary.get("symbols_list"):
        missing = sorted(set(requested) - set(bars_summary["symbols_list"]))
    else:
        missing = []
    benchmark_summary = _summarize_benchmarks(benchmarks_path)

    benchmark_risk = _parse_benchmark_risk(qrun_log)
    if not benchmark_risk:
        benchmark_risk = _compute_benchmark_risk(report)

    summary = {
        "run": {
            "experiment_id": run.parent.name,
            "run_id": run.name,
            "run_dir": str(run),
            "status": _run_status(run),
            "qrun_log": str(qrun_log) if qrun_log else None,
        },
        "data": {
            **bars_summary,
            "requested_symbols": len(requested) if requested else None,
            "missing_symbols": missing,
            "benchmarks": benchmark_summary,
        },
        "model": {
            "name": "Alpha158 + LightGBM",
            "best_iteration": _parse_best_iteration(qrun_log),
            "l2_train": metrics.get("l2.train"),
            "l2_valid": metrics.get("l2.valid"),
        },
        "signal": {
            "IC": metrics.get("IC"),
            "ICIR": metrics.get("ICIR"),
            "Rank IC": metrics.get("Rank IC"),
            "Rank ICIR": metrics.get("Rank ICIR"),
            "test_days": int(getattr(ic, "count", lambda: 0)()),
        },
        "portfolio": {
            **benchmark_risk,
            "excess_without_cost_mean": metrics.get("1day.excess_return_without_cost.mean"),
            "excess_without_cost_std": metrics.get("1day.excess_return_without_cost.std"),
            "excess_without_cost_annualized_return": metrics.get("1day.excess_return_without_cost.annualized_return"),
            "excess_without_cost_information_ratio": metrics.get("1day.excess_return_without_cost.information_ratio"),
            "excess_without_cost_max_drawdown": metrics.get("1day.excess_return_without_cost.max_drawdown"),
            "excess_with_cost_mean": metrics.get("1day.excess_return_with_cost.mean"),
            "excess_with_cost_std": metrics.get("1day.excess_return_with_cost.std"),
            "excess_with_cost_annualized_return": metrics.get("1day.excess_return_with_cost.annualized_return"),
            "excess_with_cost_information_ratio": metrics.get("1day.excess_return_with_cost.information_ratio"),
            "excess_with_cost_max_drawdown": metrics.get("1day.excess_return_with_cost.max_drawdown"),
            **_summarize_report(report, indicators, indicator, positions),
        },
        "group_returns": group_summary.to_dict(orient="index"),
        "outputs": {
            "summary_json": str(out / "summary.json"),
            "summary_md": str(out / "summary.md"),
            "port_analysis_csv": str(out / "port_analysis_1day.csv"),
            "report_csv": str(out / "report_normal_1day.csv"),
            "indicator_analysis_csv": str(out / "indicator_analysis_1day.csv"),
            "ic_daily_csv": str(out / "ic_daily.csv"),
            "rank_ic_daily_csv": str(out / "rank_ic_daily.csv"),
            "group_daily_csv": str(out / "factor_group_returns_daily.csv"),
            "group_summary_csv": str(out / "factor_group_summary.csv"),
        },
    }
    _write_summary(summary, out)
    return summary


def find_latest_qlib_run(mlruns_dir: str | Path = "mlruns") -> Path:
    """Find the latest successful Qlib run with prediction artifacts."""

    root = Path(mlruns_dir)
    candidates: list[tuple[float, Path]] = []
    for meta in root.glob("*/*/meta.yaml"):
        run = meta.parent
        if not (run / "artifacts" / "pred.pkl").exists():
            continue
        if not (run / "artifacts" / "label.pkl").exists():
            continue
        status = _run_status(run)
        if status not in {"3", "FINISHED", "success", "finished"}:
            continue
        candidates.append((meta.stat().st_mtime, run))
    if not candidates:
        raise FileNotFoundError(f"No successful Qlib run found under {root}")
    return max(candidates)[1]


def _compute_group_returns(pred_label: pd.DataFrame, n_groups: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    if pred_label.empty:
        empty = pd.DataFrame(columns=["mean_daily_return", "annualized_return_simple", "volatility_daily", "count_days"])
        return empty, pd.DataFrame()
    data = pred_label.reset_index()
    label_col = "LABEL0" if "LABEL0" in data.columns else data.columns[-1]
    data["group"] = data.groupby("datetime")["score"].transform(
        lambda s: pd.qcut(s.rank(method="first"), q=min(n_groups, len(s)), labels=False, duplicates="drop") + 1
    )
    daily = data.groupby(["datetime", "group"], observed=True)[label_col].mean().unstack("group").sort_index()
    daily.columns = [f"group_{int(column)}" for column in daily.columns]
    summary = pd.DataFrame(
        {
            "mean_daily_return": daily.mean(),
            "annualized_return_simple": daily.mean() * 252,
            "volatility_daily": daily.std(),
            "count_days": daily.count(),
        }
    )
    low, high = "group_1", f"group_{n_groups}"
    if {low, high}.issubset(daily.columns):
        long_short = daily[high] - daily[low]
        summary.loc[f"{high}_minus_1", "mean_daily_return"] = long_short.mean()
        summary.loc[f"{high}_minus_1", "annualized_return_simple"] = long_short.mean() * 252
        summary.loc[f"{high}_minus_1", "volatility_daily"] = long_short.std()
        summary.loc[f"{high}_minus_1", "count_days"] = long_short.count()
    return summary, daily


def _summarize_bars(path: str | Path | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {"bars_path": str(path) if path else None, "symbols": None, "rows": None, "start": None, "end": None}
    bars = pd.read_parquet(path) if Path(path).suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path)
    dates = pd.to_datetime(bars["date"])
    symbols = sorted(bars["symbol"].dropna().astype(str).unique().tolist())
    return {
        "bars_path": str(path),
        "symbols": int(len(symbols)),
        "symbols_list": symbols,
        "rows": int(len(bars)),
        "start": str(dates.min().date()),
        "end": str(dates.max().date()),
    }


def _summarize_benchmarks(path: str | Path | None) -> list[str]:
    if not path or not Path(path).exists():
        return []
    frame = pd.read_parquet(path) if Path(path).suffix.lower() in {".parquet", ".pq"} else pd.read_csv(path)
    if "benchmark" not in frame.columns:
        return []
    return sorted(frame["benchmark"].dropna().astype(str).unique().tolist())


def _summarize_report(
    report: pd.DataFrame,
    indicators: pd.DataFrame | None,
    indicator: pd.DataFrame,
    positions: Any | None,
) -> dict[str, Any]:
    start_account = float(report["account"].iloc[0]) if "account" in report.columns and len(report) else math.nan
    end_account = float(report["account"].iloc[-1]) if "account" in report.columns and len(report) else math.nan
    result: dict[str, Any] = {
        "account_total_return": end_account / start_account - 1 if start_account else None,
        "benchmark_total_return": float((1 + report["bench"].fillna(0)).prod() - 1) if "bench" in report.columns else None,
        "avg_daily_turnover": _mean_or_none(report.get("turnover")),
        "avg_daily_total_turnover": _mean_or_none(report.get("total_turnover")),
        "total_cost_sum": _sum_or_none(report.get("total_cost")),
        "avg_daily_cost": _mean_or_none(report.get("cost")),
    }
    position_counts = _position_counts(positions)
    if position_counts:
        result["avg_positions"] = float(pd.Series(position_counts).mean())
        result["max_positions"] = int(max(position_counts))
    elif indicators is not None and "count" in indicators.columns:
        result["avg_positions"] = _mean_or_none(indicators["count"])
    for key in ["ffr", "pa", "pos"]:
        if key in indicator.index and "value" in indicator.columns:
            result[key] = _to_json_scalar(indicator.loc[key, "value"])
    return result


def _position_counts(positions: Any | None) -> list[int]:
    if not isinstance(positions, dict):
        return []
    counts: list[int] = []
    for position in positions.values():
        payload = getattr(position, "position", None)
        if payload is None and isinstance(position, dict):
            payload = position.get("position")
        if not isinstance(payload, dict):
            continue
        counts.append(
            sum(
                1
                for key, value in payload.items()
                if key not in {"cash", "now_account_value"} and isinstance(value, dict)
            )
        )
    return counts


def _parse_benchmark_risk(qrun_log: str | Path | None) -> dict[str, float]:
    if not qrun_log or not Path(qrun_log).exists():
        return {}
    text = Path(qrun_log).read_text(encoding="utf-8", errors="ignore")
    marker = "analysis results of benchmark return(1day)"
    pos = text.find(marker)
    if pos < 0:
        return {}
    block = text[pos : pos + 500]
    values = {}
    for key, out_key in [
        ("mean", "benchmark_mean"),
        ("std", "benchmark_std"),
        ("annualized_return", "benchmark_annualized_return"),
        ("information_ratio", "benchmark_information_ratio"),
        ("max_drawdown", "benchmark_max_drawdown"),
    ]:
        match = re.search(rf"{key}\s+(-?\d+(?:\.\d+)?)", block)
        if match:
            values[out_key] = float(match.group(1))
    return values


def _compute_benchmark_risk(report: pd.DataFrame) -> dict[str, float]:
    if "bench" not in report.columns:
        return {}
    bench = report["bench"].dropna()
    if bench.empty:
        return {}
    wealth = (1 + bench).cumprod()
    drawdown = wealth / wealth.cummax() - 1
    std = bench.std()
    return {
        "benchmark_mean": float(bench.mean()),
        "benchmark_std": float(std),
        "benchmark_annualized_return": float(bench.mean() * 252),
        "benchmark_information_ratio": float(bench.mean() / std * math.sqrt(252)) if std else None,
        "benchmark_max_drawdown": float(drawdown.min()),
    }


def _write_summary(summary: dict[str, Any], out: Path) -> None:
    sanitized = _sanitize(summary)
    (out / "summary.json").write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "summary.md").write_text(_render_markdown(sanitized), encoding="utf-8")


def _render_markdown(summary: dict[str, Any]) -> str:
    portfolio = summary["portfolio"]
    signal = summary["signal"]
    data = summary["data"]
    lines = [
        "# Alpha158 LightGBM Baseline",
        "",
        f"Run: `{summary['run']['run_id']}`  ",
        f"Data: {data.get('symbols')} symbols, {data.get('rows')} rows, {data.get('start')} to {data.get('end')}",
        "",
        "## Signal",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| IC | {_num(signal.get('IC'))} |",
        f"| ICIR | {_num(signal.get('ICIR'))} |",
        f"| Rank IC | {_num(signal.get('Rank IC'))} |",
        f"| Rank ICIR | {_num(signal.get('Rank ICIR'))} |",
        f"| Test days | {signal.get('test_days')} |",
        "",
        "## Portfolio",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Benchmark annualized return | {_pct(portfolio.get('benchmark_annualized_return'))} |",
        f"| Benchmark information ratio | {_num(portfolio.get('benchmark_information_ratio'), 3)} |",
        f"| Benchmark max drawdown | {_pct(portfolio.get('benchmark_max_drawdown'))} |",
        f"| Excess annualized return with cost | {_pct(portfolio.get('excess_with_cost_annualized_return'))} |",
        f"| Excess information ratio with cost | {_num(portfolio.get('excess_with_cost_information_ratio'), 3)} |",
        f"| Excess max drawdown with cost | {_pct(portfolio.get('excess_with_cost_max_drawdown'))} |",
        f"| Excess annualized return without cost | {_pct(portfolio.get('excess_without_cost_annualized_return'))} |",
        f"| Excess information ratio without cost | {_num(portfolio.get('excess_without_cost_information_ratio'), 3)} |",
        f"| Excess max drawdown without cost | {_pct(portfolio.get('excess_without_cost_max_drawdown'))} |",
        f"| Account total return | {_pct(portfolio.get('account_total_return'))} |",
        f"| Benchmark total return | {_pct(portfolio.get('benchmark_total_return'))} |",
        f"| Average daily turnover | {_num(portfolio.get('avg_daily_turnover'))} |",
        f"| Total cost sum | {_num(portfolio.get('total_cost_sum'), 2)} |",
        f"| Average positions | {_num(portfolio.get('avg_positions'), 2)} |",
        "",
        "## Group Returns",
        "",
        "| Group | Mean Daily Return | Simple Annualized |",
        "|---|---:|---:|",
    ]
    for key, row in summary.get("group_returns", {}).items():
        lines.append(f"| {key} | {_pct(row.get('mean_daily_return'))} | {_pct(row.get('annualized_return_simple'))} |")
    missing = data.get("missing_symbols") or []
    lines.extend(
        [
            "",
            "## Notes",
            "",
            f"- Requested symbols: {data.get('requested_symbols')}; downloaded symbols: {data.get('symbols')}; missing: {', '.join(missing) if missing else 'none'}.",
            "- This is a baseline research backtest result, not investment advice.",
            "",
        ]
    )
    return "\n".join(lines)


def _read_metrics(path: Path) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if not path.exists():
        return metrics
    for metric_file in path.iterdir():
        if not metric_file.is_file():
            continue
        lines = [line.split() for line in metric_file.read_text(encoding="utf-8").splitlines() if line.strip()]
        if lines:
            metrics[metric_file.name] = float(lines[-1][1])
    return metrics


def _run_status(run: Path) -> str:
    meta = run / "meta.yaml"
    if not meta.exists():
        return "unknown"
    try:
        data = yaml.safe_load(meta.read_text(encoding="utf-8")) or {}
    except Exception:
        return "unknown"
    return str(data.get("status", "unknown"))


def _parse_best_iteration(qrun_log: str | Path | None) -> int | None:
    if not qrun_log or not Path(qrun_log).exists():
        return None
    text = Path(qrun_log).read_text(encoding="utf-8", errors="ignore")
    match = re.search(r"best iteration is:\s*\n\[(\d+)\]", text)
    return int(match.group(1)) if match else None


def _load_pickle(path: Path) -> Any:
    with path.open("rb") as fh:
        return pickle.load(fh)


def _load_optional_pickle(path: Path) -> Any | None:
    return _load_pickle(path) if path.exists() else None


def _write_frame(frame: pd.DataFrame, path: Path) -> None:
    frame.to_csv(path)


def _write_series(series: pd.Series, name: str, path: Path) -> None:
    series.rename(name).to_csv(path)


def _read_requested_symbols(path: str | Path | None) -> list[str]:
    if not path or not Path(path).exists():
        return []
    from ashare_adapter.metadata import normalize_symbol

    return [
        normalize_symbol(line.strip())
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _mean_or_none(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    value = pd.to_numeric(series, errors="coerce").dropna().mean()
    return None if pd.isna(value) else float(value)


def _sum_or_none(series: pd.Series | None) -> float | None:
    if series is None:
        return None
    value = pd.to_numeric(series, errors="coerce").dropna().sum()
    return None if pd.isna(value) else float(value)


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items() if k != "symbols_list"}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    return _to_json_scalar(value)


def _to_json_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _pct(value: Any) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.2%}"


def _num(value: Any, digits: int = 6) -> str:
    if value is None:
        return "n/a"
    return f"{float(value):.{digits}f}"
