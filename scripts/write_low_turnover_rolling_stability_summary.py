"""Summarize real-data low-turnover rolling OOS stability by scenario."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.report_policy import assert_formal_report_uses_real_data, real_data_markers


EXCESS_COL = "excess_annualized_return_with_cost"
IR_COL = "excess_information_ratio_with_cost"
MDD_COL = "excess_max_drawdown_with_cost"


def main() -> None:
    args = parse_args()
    rows = pd.read_csv(args.input)
    summary = summarize_low_turnover_stability(rows)
    csv_path = Path(args.output_csv)
    md_path = Path(args.output_md)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    assert_formal_report_uses_real_data(csv_path, {"data": real_data_markers()})
    assert_formal_report_uses_real_data(md_path, {"data": real_data_markers()})
    summary.to_csv(csv_path, index=False)
    md_path.write_text(render_markdown(summary), encoding="utf-8")
    print(f"Wrote low-turnover rolling stability summary: {csv_path}")


def summarize_low_turnover_stability(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame(columns=_columns())
    _assert_real_rows(rows)
    data = rows.copy()
    if "scenario" not in data.columns:
        data["scenario"] = ""
    data["scenario"] = data["scenario"].fillna("").astype(str)
    missing = data["scenario"].str.strip().eq("")
    if missing.any():
        data.loc[missing, "scenario"] = data.loc[missing].apply(_scenario_from_row, axis=1)
    for column in [EXCESS_COL, IR_COL, MDD_COL, "turnover"]:
        data[column] = pd.to_numeric(data.get(column), errors="coerce")
    data["is_ytd"] = _to_bool_series(data.get("is_ytd", pd.Series(False, index=data.index)))

    records: list[dict[str, Any]] = []
    group_cols = ["scenario", "universe_name", "model", "model_key", "topk", "n_drop", "rebalance_step"]
    for keys, frame in data.groupby(group_cols, dropna=False):
        key_map = dict(zip(group_cols, keys if isinstance(keys, tuple) else (keys,)))
        excess = frame[EXCESS_COL].dropna()
        ir = frame[IR_COL].dropna()
        drawdown = frame[MDD_COL].dropna()
        ytd = frame[frame["is_ytd"]].sort_values("test_end") if "test_end" in frame.columns else frame[frame["is_ytd"]]
        ytd_excess = _last_numeric(ytd.get(EXCESS_COL))
        ytd_ir = _last_numeric(ytd.get(IR_COL))
        positive = int(excess.gt(0).sum())
        count = int(excess.count())
        records.append(
            {
                **real_data_markers(),
                **key_map,
                "window_count": count,
                "positive_excess_windows": positive,
                "positive_excess_ratio": positive / count if count else None,
                "mean_excess_annualized": _mean(excess),
                "median_excess_annualized": _median(excess),
                "min_excess_annualized": _min(excess),
                "max_excess_annualized": _max(excess),
                "mean_IR": _mean(ir),
                "min_IR": _min(ir),
                "worst_drawdown": _min(drawdown),
                "y2026_excess": ytd_excess,
                "y2026_IR": ytd_ir,
                "mean_turnover": _mean(frame["turnover"].dropna()),
                "data_quality_status": _mode_value(frame.get("data_quality_status")),
                "industry_quality_status": _mode_value(frame.get("industry_quality_status")),
                "conclusion_tag": _conclusion_tag(count, positive, ytd_excess),
            }
        )
    return pd.DataFrame(records, columns=_columns()).sort_values(["scenario", "universe_name"], kind="stable")


def render_markdown(summary: pd.DataFrame) -> str:
    note = "Real AKShare low-turnover rolling OOS stability from full Qlib workflows, not portfolio-layer reruns."
    return "# Low-Turnover Rolling Stability Summary Real AKShare\n\n" + note + "\n\n" + summary.to_markdown(index=False) + "\n"


def _scenario_from_row(row: pd.Series) -> str:
    topk = int(float(row.get("topk", 0)))
    n_drop = int(float(row.get("n_drop", 0)))
    step = int(float(row.get("rebalance_step", 1)))
    if step == 5:
        return f"weekly_topk{topk}_drop{n_drop}"
    if step == 20:
        return f"monthly_topk{topk}_drop{n_drop}"
    return f"topk{topk}_drop{n_drop}"


def _assert_real_rows(rows: pd.DataFrame) -> None:
    if not rows.get("data_type", pd.Series(dtype=str)).astype(str).eq("real_akshare").all():
        raise ValueError("Low-turnover stability requires data_type=real_akshare for every row.")
    if _to_bool_series(rows.get("synthetic_data", pd.Series(dtype=bool))).any():
        raise ValueError("Low-turnover stability refuses synthetic_data=True rows.")
    if _to_bool_series(rows.get("mock_data", pd.Series(dtype=bool))).any():
        raise ValueError("Low-turnover stability refuses mock_data=True rows.")


def _conclusion_tag(window_count: int, positive_windows: int, ytd_excess: float | None) -> str:
    if window_count <= 0:
        return "insufficient_data"
    if ytd_excess is not None and ytd_excess < 0:
        return "mostly_positive_but_recent_weakness" if positive_windows / window_count >= 0.6 else "unstable_recent_weakness"
    if positive_windows == window_count:
        return "stable_positive"
    if positive_windows / window_count >= 0.6:
        return "mostly_positive"
    return "unstable"


def _last_numeric(values: pd.Series | None) -> float | None:
    if values is None:
        return None
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.iloc[-1]) if not numeric.empty else None


def _mean(values: pd.Series) -> float | None:
    return None if values.empty else float(values.mean())


def _median(values: pd.Series) -> float | None:
    return None if values.empty else float(values.median())


def _min(values: pd.Series) -> float | None:
    return None if values.empty else float(values.min())


def _max(values: pd.Series) -> float | None:
    return None if values.empty else float(values.max())


def _mode_value(values: pd.Series | None) -> Any:
    if values is None:
        return None
    cleaned = values.dropna()
    if cleaned.empty:
        return None
    return cleaned.astype(str).value_counts().index[0]


def _to_bool_series(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=bool)
    if values.dtype == bool:
        return values.fillna(False)
    return values.astype(str).str.lower().isin({"true", "1", "yes"})


def _columns() -> list[str]:
    return [
        "data_type",
        "synthetic_data",
        "mock_data",
        "download_source",
        "scenario",
        "universe_name",
        "model",
        "model_key",
        "topk",
        "n_drop",
        "rebalance_step",
        "window_count",
        "positive_excess_windows",
        "positive_excess_ratio",
        "mean_excess_annualized",
        "median_excess_annualized",
        "min_excess_annualized",
        "max_excess_annualized",
        "mean_IR",
        "min_IR",
        "worst_drawdown",
        "y2026_excess",
        "y2026_IR",
        "mean_turnover",
        "data_quality_status",
        "industry_quality_status",
        "conclusion_tag",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="reports/low_turnover_rolling_comparison_real.csv")
    parser.add_argument("--output-csv", default="reports/low_turnover_rolling_stability_summary_real.csv")
    parser.add_argument("--output-md", default="reports/low_turnover_rolling_stability_summary_real.md")
    return parser.parse_args()


if __name__ == "__main__":
    main()
