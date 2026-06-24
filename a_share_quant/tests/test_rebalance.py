from __future__ import annotations

import pandas as pd

from ashare_quant.portfolio.weighting import build_target_weights


def test_rebalance_top_k_and_max_weight_leave_cash_when_capped() -> None:
    date = pd.Timestamp("2023-06-30")
    scores = pd.DataFrame(
        {
            "date": [date] * 5,
            "symbol": ["A", "B", "C", "D", "E"],
            "composite_score": [5, 4, 3, 2, 1],
            "volatility": [0.2, 0.1, 0.3, 0.4, 0.5],
        }
    )

    weights = build_target_weights(scores, date, ["A", "B", "C", "D", "E"], 3, "equal_weight", 0.2)

    assert weights["symbol"].tolist() == ["A", "B", "C"]
    assert weights["target_weight"].max() <= 0.2
    assert round(weights["target_weight"].sum(), 6) == 0.6


def test_inverse_vol_weighting_normalizes_when_uncapped() -> None:
    date = pd.Timestamp("2023-06-30")
    scores = pd.DataFrame(
        {
            "date": [date] * 2,
            "symbol": ["A", "B"],
            "composite_score": [2, 1],
            "volatility": [0.2, 0.1],
        }
    )

    weights = build_target_weights(scores, date, ["A", "B"], 2, "inverse_vol_weight", 1.0)

    assert round(weights["target_weight"].sum(), 6) == 1.0
    assert weights.loc[weights["symbol"] == "B", "target_weight"].iloc[0] > 0.5

