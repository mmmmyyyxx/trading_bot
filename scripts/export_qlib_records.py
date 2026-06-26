"""Export Qlib recorder artifacts and run local diagnostics."""

from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.benchmarks import read_benchmarks
from ashare_adapter.diagnostics import write_diagnostics
from ashare_adapter.metadata import from_qlib_symbol
from ashare_adapter.qlib_converter import read_bars
from ashare_adapter.result_export import find_latest_qlib_run
from ashare_adapter.signal_mask import apply_selected_mask


def main() -> None:
    args = parse_args()
    run_dir = Path(args.run_dir) if args.run_dir else find_latest_qlib_run(args.mlruns_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    exported = export_records(run_dir, output_dir)
    scores_path = exported["predictions"]
    if args.apply_mask:
        bars = read_bars(args.bars)
        scores = pd.read_csv(scores_path)
        masked = apply_selected_mask(scores, bars, score_col=args.score_col, mask_col=args.mask_col)
        scores_path = output_dir / "masked_predictions.csv"
        masked.to_csv(scores_path, index=False)
        exported["masked_predictions"] = scores_path

    if args.run_diagnostics:
        bars = read_bars(args.bars)
        scores = pd.read_csv(scores_path)
        benchmarks = read_benchmarks(args.benchmarks) if args.benchmarks else None
        equity = pd.read_csv(exported["equity"]) if "equity" in exported else None
        positions = pd.read_csv(exported["positions"]) if "positions" in exported else None
        diagnostics_dir = output_dir / "diagnostics"
        diagnostic_paths = write_diagnostics(
            output_dir=diagnostics_dir,
            bars=bars,
            scores=scores,
            benchmarks=benchmarks,
            equity=equity,
            positions=positions,
            trades=None,
            score_col=args.score_col,
            horizons=args.horizons,
            n_groups=args.n_groups,
            oos_start_date=args.oos_start_date,
        )
        exported.update({f"diagnostics_{name}": path for name, path in diagnostic_paths.items()})

    for name, path in exported.items():
        print(f"Wrote {name}: {path}")


def export_records(run_dir: str | Path, output_dir: str | Path) -> dict[str, Path]:
    """Export common Qlib artifacts from a recorder run directory."""

    run = Path(run_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    artifacts = run / "artifacts"
    pa = artifacts / "portfolio_analysis"
    outputs: dict[str, Path] = {}

    pred = _load_pickle(artifacts / "pred.pkl")
    predictions = _prediction_to_csv_frame(pred)
    outputs["predictions"] = out / "predictions.csv"
    predictions.to_csv(outputs["predictions"], index=False)

    label_path = artifacts / "label.pkl"
    if label_path.exists():
        labels = _prediction_to_csv_frame(_load_pickle(label_path), score_col="label")
        outputs["labels"] = out / "labels.csv"
        labels.to_csv(outputs["labels"], index=False)

    report_path = pa / "report_normal_1day.pkl"
    if report_path.exists():
        report = _load_pickle(report_path)
        outputs["equity"] = out / "equity.csv"
        _report_to_equity(report).to_csv(outputs["equity"], index=False)
        outputs["portfolio_report"] = out / "portfolio_report.csv"
        report.to_csv(outputs["portfolio_report"])

    positions_path = pa / "positions_normal_1day.pkl"
    if positions_path.exists():
        outputs["positions"] = out / "positions.csv"
        _positions_to_frame(_load_pickle(positions_path)).to_csv(outputs["positions"], index=False)

    indicators_path = pa / "indicators_normal_1day.pkl"
    if indicators_path.exists():
        outputs["indicators"] = out / "indicators.csv"
        _load_pickle(indicators_path).to_csv(outputs["indicators"])

    return outputs


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", default=None)
    parser.add_argument("--mlruns-dir", default="mlruns")
    parser.add_argument("--output-dir", default="reports/qlib_records")
    parser.add_argument("--bars", required=True)
    parser.add_argument("--benchmarks", default=None)
    parser.add_argument("--score-col", default="score")
    parser.add_argument("--apply-mask", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--mask-col", default="selected")
    parser.add_argument("--run-diagnostics", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--horizons", nargs="+", type=int, default=[1, 5, 20])
    parser.add_argument("--n-groups", type=int, default=5)
    parser.add_argument("--oos-start-date", default=None)
    return parser.parse_args()


def _prediction_to_csv_frame(frame: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    data = frame.copy()
    if isinstance(data.index, pd.MultiIndex):
        data = data.reset_index()
    data = data.rename(columns={"datetime": "date", "instrument": "symbol"})
    value_cols = [column for column in data.columns if column not in {"date", "symbol"}]
    if score_col not in data.columns and value_cols:
        data = data.rename(columns={value_cols[0]: score_col})
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(_normalize_export_symbol)
    return data[["date", "symbol", score_col]].sort_values(["date", "symbol"])


def _report_to_equity(report: pd.DataFrame) -> pd.DataFrame:
    data = report.copy().reset_index().rename(columns={"datetime": "date", "index": "date"})
    if "date" not in data.columns:
        data = data.rename(columns={data.columns[0]: "date"})
    data["date"] = pd.to_datetime(data["date"])
    if "account" in data.columns:
        data["account_value"] = pd.to_numeric(data["account"], errors="coerce")
        data["equity"] = data["account_value"] / data["account_value"].iloc[0]
    elif "return" in data.columns:
        data["equity"] = (1.0 + pd.to_numeric(data["return"], errors="coerce").fillna(0.0)).cumprod()
        data["account_value"] = data["equity"]
    if "daily_return" not in data.columns:
        if "return" in data.columns:
            data["daily_return"] = pd.to_numeric(data["return"], errors="coerce").fillna(0.0)
        else:
            data["daily_return"] = data["equity"].pct_change().fillna(0.0)
    keep = [column for column in ["date", "equity", "account_value", "daily_return", "bench", "turnover", "cost", "total_cost"] if column in data.columns]
    return data[keep]


def _positions_to_frame(positions: dict[Any, Any]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for date, position in positions.items():
        payload = getattr(position, "position", None)
        if payload is None and isinstance(position, dict):
            payload = position.get("position")
        if not isinstance(payload, dict):
            continue
        for symbol, values in payload.items():
            if symbol in {"cash", "now_account_value"} or not isinstance(values, dict):
                continue
            rows.append(
                {
                    "date": pd.Timestamp(date),
                    "symbol": _normalize_export_symbol(symbol),
                    "weight": float(values.get("weight", 0.0)),
                    "amount": float(values.get("amount", 0.0)),
                    "price": float(values.get("price", 0.0)),
                }
            )
    return pd.DataFrame(rows).sort_values(["date", "symbol"]) if rows else pd.DataFrame(columns=["date", "symbol", "weight", "amount", "price"])


def _normalize_export_symbol(symbol: object) -> str:
    text = str(symbol).strip()
    if len(text) >= 8 and text[:2].upper() in {"SH", "SZ", "BJ"}:
        return from_qlib_symbol(text)
    return text


def _load_pickle(path: Path) -> Any:
    with path.open("rb") as fh:
        return pickle.load(fh)


if __name__ == "__main__":
    main()
