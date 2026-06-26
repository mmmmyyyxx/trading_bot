"""Data sufficiency checks for dynamic liquidity universe experiments."""

from __future__ import annotations

from typing import Any


def assess_data_sufficiency(
    data: dict[str, Any],
    universe: dict[str, Any],
    *,
    candidate_coverage_threshold: float = 0.8,
) -> dict[str, Any]:
    """Assess whether a run has enough data for its declared universe mode."""

    requested = _to_int(data.get("requested_symbols") or universe.get("requested_symbols"))
    actual = _to_int(data.get("symbols") or data.get("actual_symbols") or universe.get("actual_symbols"))
    top_n = _to_int(universe.get("dynamic_liquidity_top_n"))
    avg_selected = _to_float(universe.get("avg_selected_universe_count"))
    min_selected = _to_int(universe.get("min_selected_universe_count"))
    max_selected = _to_int(universe.get("max_selected_universe_count"))

    coverage = actual / requested if actual is not None and requested else None
    candidate_ok = coverage >= candidate_coverage_threshold if coverage is not None else None
    selected_top_n_reached = max_selected >= top_n if top_n is not None and max_selected is not None else None

    if top_n is None:
        sufficient = None
        note = "eligible_only universe; dynamic liquidity top-N was not requested."
    else:
        sufficient = bool(selected_top_n_reached) and candidate_ok is not False
        if selected_top_n_reached is False:
            note = f"data insufficient for intended dynamic top{top_n}; max selected universe count is {max_selected}."
        elif candidate_ok is False:
            note = (
                f"candidate coverage is low for dynamic top{top_n}; "
                f"downloaded {actual} of {requested} requested symbols."
            )
        elif selected_top_n_reached is None:
            note = f"dynamic top{top_n} sufficiency is unknown; selected universe diagnostics are missing."
        else:
            note = f"dynamic top{top_n} selected count reached the configured target."

    return {
        "requested_symbols": requested,
        "actual_symbols": actual,
        "candidate_symbol_coverage": coverage,
        "candidate_coverage_threshold": float(candidate_coverage_threshold),
        "candidate_coverage_ok": candidate_ok,
        "dynamic_liquidity_top_n": top_n,
        "avg_selected_universe_count": avg_selected,
        "min_selected_universe_count": min_selected,
        "max_selected_universe_count": max_selected,
        "selected_top_n_reached": selected_top_n_reached,
        "data_sufficient_for_dynamic_top_n": sufficient,
        "note": note,
    }


def data_sufficiency_caveats(assessment: dict[str, Any]) -> list[str]:
    """Return human-readable caveats from a sufficiency assessment."""

    top_n = assessment.get("dynamic_liquidity_top_n")
    caveats: list[str] = []
    if top_n is None:
        return caveats
    if assessment.get("selected_top_n_reached") is False:
        caveats.append(
            "Data insufficient for intended dynamic liquidity "
            f"top{top_n}: max selected universe count is "
            f"{assessment.get('max_selected_universe_count')}, below {top_n}."
        )
    if assessment.get("candidate_coverage_ok") is False:
        coverage = assessment.get("candidate_symbol_coverage")
        coverage_text = f"{coverage:.1%}" if isinstance(coverage, float) else "unknown"
        caveats.append(
            "Candidate data coverage is low: downloaded "
            f"{assessment.get('actual_symbols')} of {assessment.get('requested_symbols')} "
            f"requested symbols ({coverage_text})."
        )
    return caveats


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        if value != value:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
