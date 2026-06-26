"""Signal masking helpers for A-share dynamic universe fields."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ashare_adapter.metadata import from_qlib_symbol, normalize_symbol, to_qlib_symbol
from ashare_adapter.qlib_converter import read_bars


def apply_selected_mask(
    predictions: pd.DataFrame,
    bars: pd.DataFrame,
    score_col: str = "score",
    mask_col: str = "selected",
    fallback_mask_col: str | None = "eligible",
    masked_value: float = np.nan,
) -> pd.DataFrame:
    """Mask prediction scores with a dynamic universe column from bars.

    Predictions outside the selected/eligible universe keep their rows but have
    `score_col` replaced by `masked_value`.
    """

    pred = normalize_prediction_frame(predictions, score_col=score_col)
    mask = normalize_mask_frame(bars, mask_col=mask_col, fallback_mask_col=fallback_mask_col)
    merged = pred.merge(mask, on=["date", "symbol"], how="left")
    active = merged["mask_active"].fillna(False).astype(bool)
    merged.loc[~active, score_col] = masked_value
    return merged.sort_values(["date", "symbol"]).reset_index(drop=True)


def normalize_prediction_frame(predictions: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    """Normalize Qlib/local predictions to date/symbol/score columns."""

    data = predictions.copy()
    if isinstance(data.index, pd.MultiIndex):
        data = data.reset_index()
    rename = {}
    if "datetime" in data.columns:
        rename["datetime"] = "date"
    if "instrument" in data.columns:
        rename["instrument"] = "symbol"
    data = data.rename(columns=rename)
    if "date" not in data.columns or "symbol" not in data.columns:
        raise ValueError("Predictions must contain date/symbol columns or a datetime/instrument MultiIndex.")
    if score_col not in data.columns:
        raise ValueError(f"Prediction score column not found: {score_col}")
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(_normalize_prediction_symbol)
    data[score_col] = pd.to_numeric(data[score_col], errors="coerce")
    return data


def normalize_mask_frame(
    bars: pd.DataFrame,
    mask_col: str = "selected",
    fallback_mask_col: str | None = "eligible",
) -> pd.DataFrame:
    """Normalize a bar frame's universe mask to date/symbol/mask columns."""

    if mask_col not in bars.columns:
        if fallback_mask_col and fallback_mask_col in bars.columns:
            mask_col = fallback_mask_col
        else:
            raise ValueError(f"Mask column not found: {mask_col}")
    data = bars[["date", "symbol", mask_col]].copy()
    data["date"] = pd.to_datetime(data["date"])
    data["symbol"] = data["symbol"].map(normalize_symbol)
    data[mask_col] = data[mask_col].fillna(False).astype(bool)
    return data.rename(columns={mask_col: "mask_active"}).drop_duplicates(["date", "symbol"])


def to_qlib_signal_frame(masked_predictions: pd.DataFrame, score_col: str = "score") -> pd.DataFrame:
    """Convert masked date/symbol predictions to Qlib's MultiIndex signal frame."""

    data = normalize_prediction_frame(masked_predictions, score_col=score_col)
    data["instrument"] = data["symbol"].map(to_qlib_symbol)
    signal = data[["date", "instrument", score_col]].rename(columns={"date": "datetime"})
    return signal.set_index(["datetime", "instrument"]).sort_index()


def read_prediction_file(path: str | Path) -> pd.DataFrame:
    """Read predictions from CSV, parquet, or pickle."""

    source = Path(path)
    if source.suffix.lower() in {".pkl", ".pickle"}:
        return pd.read_pickle(source)
    if source.suffix.lower() in {".parquet", ".pq"}:
        return pd.read_parquet(source)
    return pd.read_csv(source)


def write_masked_predictions(
    masked_predictions: pd.DataFrame,
    output_csv: str | Path,
    output_pkl: str | Path | None = None,
    score_col: str = "score",
) -> dict[str, Path]:
    """Write masked predictions as CSV and optionally Qlib signal pickle."""

    paths: dict[str, Path] = {}
    csv_path = Path(output_csv)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    masked_predictions.to_csv(csv_path, index=False)
    paths["csv"] = csv_path
    if output_pkl:
        pkl_path = Path(output_pkl)
        pkl_path.parent.mkdir(parents=True, exist_ok=True)
        to_qlib_signal_frame(masked_predictions, score_col=score_col).to_pickle(pkl_path)
        paths["pkl"] = pkl_path
    return paths


def mask_prediction_file(
    predictions_path: str | Path,
    bars_path: str | Path,
    output_csv: str | Path,
    output_pkl: str | Path | None = None,
    score_col: str = "score",
    mask_col: str = "selected",
) -> dict[str, Path]:
    """Read, mask, and write prediction files."""

    predictions = read_prediction_file(predictions_path)
    bars = read_bars(bars_path)
    masked = apply_selected_mask(predictions, bars, score_col=score_col, mask_col=mask_col)
    return write_masked_predictions(masked, output_csv, output_pkl, score_col=score_col)


def _normalize_prediction_symbol(symbol: object) -> str:
    text = str(symbol).strip()
    if len(text) >= 8 and text[:2].upper() in {"SH", "SZ", "BJ"}:
        return from_qlib_symbol(text)
    return normalize_symbol(text)
