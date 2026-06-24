"""Factor group return diagnostics."""

from __future__ import annotations

import pandas as pd

from ashare_quant.research.ic import FACTOR_COLUMNS, LOWER_IS_BETTER, add_forward_returns


def compute_factor_group_returns(
    bars: pd.DataFrame,
    factor_scores: pd.DataFrame,
    n_groups: int = 5,
    horizon: int = 1,
    factor_columns: list[str] | None = None,
    min_group_size: int = 20,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compute equal-weight forward returns for factor quantile groups."""
    factor_columns = factor_columns or FACTOR_COLUMNS
    forward = add_forward_returns(bars, [horizon])
    ret_col = f"future_return_{horizon}d"
    merged = factor_scores[["date", "symbol", *factor_columns]].merge(forward, on=["date", "symbol"], how="left")

    rows: list[dict[str, object]] = []
    for factor in factor_columns:
        for date, group in merged.groupby("date"):
            sample = group[["symbol", factor, ret_col]].dropna().copy()
            if len(sample) < n_groups or sample[factor].nunique() < n_groups:
                continue
            sample["rank_value"] = -sample[factor] if factor in LOWER_IS_BETTER else sample[factor]
            try:
                sample["group"] = pd.qcut(sample["rank_value"], q=n_groups, labels=False, duplicates="drop") + 1
            except ValueError:
                continue
            for group_id, group_frame in sample.groupby("group"):
                rows.append(
                    {
                        "date": date,
                        "factor": factor,
                        "group": int(group_id),
                        "daily_return": float(group_frame[ret_col].mean()),
                        "count": len(group_frame),
                        "confidence": "normal" if len(group_frame) >= min_group_size else "low",
                    }
                )

    group_returns = pd.DataFrame(rows)
    if group_returns.empty:
        return pd.DataFrame(), group_returns

    group_returns = group_returns.sort_values(["factor", "group", "date"]).reset_index(drop=True)
    group_returns["equity"] = group_returns.groupby(["factor", "group"])["daily_return"].transform(
        lambda s: (1.0 + s.fillna(0.0)).cumprod()
    )

    summary_rows = []
    for (factor, group_id), frame in group_returns.groupby(["factor", "group"]):
        periods = max(len(frame), 1)
        total_return = frame["equity"].iloc[-1] - 1.0
        annual_return = (1.0 + total_return) ** (252 / periods) - 1.0
        summary_rows.append(
            {
                "factor": factor,
                "group": group_id,
                "total_return": total_return,
                "annual_return": annual_return,
                "observations": periods,
                "avg_group_size": float(frame["count"].mean()),
                "confidence": "normal" if frame["count"].mean() >= min_group_size else "low",
            }
        )
    summary = pd.DataFrame(summary_rows).sort_values(["factor", "group"]).reset_index(drop=True)
    group_returns = group_returns.merge(summary[["factor", "group", "annual_return"]], on=["factor", "group"], how="left")
    return summary, group_returns
