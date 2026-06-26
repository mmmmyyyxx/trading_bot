"""Run manifest helpers for lightweight, reproducible report summaries."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml


def build_run_manifest(
    summary_path: str | Path,
    runtime_config_path: str | Path,
    universe_diagnostics_path: str | Path | None = None,
    symbols_file: str | Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, Any]:
    """Build a lightweight manifest for a completed Qlib run."""

    summary = json.loads(Path(summary_path).read_text(encoding="utf-8"))
    config = yaml.safe_load(Path(runtime_config_path).read_text(encoding="utf-8"))
    universe = _summarize_universe(universe_diagnostics_path)
    task = config.get("task", {})
    dataset_kwargs = task.get("dataset", {}).get("kwargs", {})
    segments = dataset_kwargs.get("segments", {})
    port_config = _find_port_analysis_config(task.get("record", []))
    strategy_kwargs = port_config.get("strategy", {}).get("kwargs", {})
    exchange_kwargs = port_config.get("backtest", {}).get("exchange_kwargs", {})

    manifest = {
        "git_commit": _git_commit(),
        "run_time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "run": summary.get("run", {}),
        "data": {
            "bars_path": summary.get("data", {}).get("bars_path"),
            "data_start": summary.get("data", {}).get("start"),
            "data_end": summary.get("data", {}).get("end"),
            "rows": summary.get("data", {}).get("rows"),
        },
        "segments": {
            "train": segments.get("train"),
            "valid": segments.get("valid"),
            "test": segments.get("test"),
        },
        "universe": {
            "symbols_file": str(symbols_file) if symbols_file else None,
            "requested_symbols": summary.get("data", {}).get("requested_symbols"),
            "actual_symbols": summary.get("data", {}).get("symbols"),
            "missing_symbols": summary.get("data", {}).get("missing_symbols", []),
            "dynamic_liquidity_top_n": universe["dynamic_liquidity_top_n"],
            "selected_mode": universe["selected_mode"],
            "selected_filter": _selected_filter(config),
            "avg_selected_universe_count": universe["avg_selected_universe_count"],
            "min_selected_universe_count": universe["min_selected_universe_count"],
            "max_selected_universe_count": universe["max_selected_universe_count"],
        },
        "benchmarks": summary.get("data", {}).get("benchmarks", []),
        "portfolio": {
            "benchmark": config.get("benchmark"),
            "topk": strategy_kwargs.get("topk"),
            "n_drop": strategy_kwargs.get("n_drop"),
            "account": port_config.get("backtest", {}).get("account"),
            "cost": {
                "open_cost": exchange_kwargs.get("open_cost"),
                "close_cost": exchange_kwargs.get("close_cost"),
                "min_cost": exchange_kwargs.get("min_cost"),
            },
            "limit_model": f"qlib_uniform_limit_threshold_{exchange_kwargs.get('limit_threshold')}",
            "deal_price": exchange_kwargs.get("deal_price"),
        },
        "caveats": [
            "Current constituent universe is used historically, so constituent survivorship bias remains.",
            "Qlib backtest uses a uniform limit_threshold, not full per-stock A-share board/ST limit rules.",
            "IC and portfolio excess performance should be reconciled through exposure and rolling diagnostics before claiming strategy validity.",
        ],
    }
    if output_path:
        target = Path(output_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _summarize_universe(path: str | Path | None) -> dict[str, Any]:
    if not path or not Path(path).exists():
        return {
            "dynamic_liquidity_top_n": None,
            "selected_mode": "unknown",
            "avg_selected_universe_count": None,
            "min_selected_universe_count": None,
            "max_selected_universe_count": None,
        }
    data = pd.read_csv(path)
    configured = pd.to_numeric(data.get("configured_top_n", pd.Series(dtype=float)), errors="coerce").fillna(0)
    top_n = int(configured.max()) if not configured.empty and configured.max() > 0 else None
    selected = pd.to_numeric(data.get("selected_universe_count", pd.Series(dtype=float)), errors="coerce").dropna()
    return {
        "dynamic_liquidity_top_n": top_n,
        "selected_mode": f"dynamic_liquidity_top_{top_n}" if top_n else "eligible_only",
        "avg_selected_universe_count": float(selected.mean()) if not selected.empty else None,
        "min_selected_universe_count": int(selected.min()) if not selected.empty else None,
        "max_selected_universe_count": int(selected.max()) if not selected.empty else None,
    }


def _find_port_analysis_config(records: list[dict[str, Any]]) -> dict[str, Any]:
    for record in records:
        if record.get("class") == "PortAnaRecord":
            return record.get("kwargs", {}).get("config", {})
    return {}


def _selected_filter(config: dict[str, Any]) -> str | None:
    handler = config.get("task", {}).get("dataset", {}).get("kwargs", {}).get("handler", {})
    pipes = handler.get("kwargs", {}).get("filter_pipe", [])
    for pipe in pipes:
        if pipe.get("filter_type") == "ExpressionDFilter":
            return pipe.get("rule_expression")
    return None


def _git_commit() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        return None
