"""Small parallel execution helpers for independent research jobs."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TypeVar

import pandas as pd
from pandas.api.types import is_object_dtype, is_string_dtype

T = TypeVar("T")
R = TypeVar("R")

_FRAME_CACHE: dict[str, pd.DataFrame] = {}


def parallel_map(items: Sequence[T], worker: Callable[[T], R], max_workers: int = 1) -> list[R]:
    """Run independent jobs with a bounded thread pool while preserving item order."""
    if not items:
        return []
    workers = min(max(1, int(max_workers or 1)), len(items))
    if workers <= 1:
        return [worker(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(worker, items))


def process_map(items: Sequence[T], worker: Callable[[T], R], max_workers: int = 1) -> list[R]:
    """Run independent jobs in worker processes while preserving item order."""
    if not items:
        return []
    workers = min(max(1, int(max_workers or 1)), len(items))
    if workers <= 1:
        return [worker(item) for item in items]
    with ProcessPoolExecutor(max_workers=workers) as executor:
        return list(executor.map(worker, items, chunksize=1))


class SharedFrameStore:
    """Temporary Parquet store for sharing large frames with worker processes."""

    def __init__(self, base_dir: str | Path) -> None:
        Path(base_dir).mkdir(parents=True, exist_ok=True)
        self._tempdir = TemporaryDirectory(prefix="ashare_quant_parallel_", dir=base_dir)
        self.path = Path(self._tempdir.name)

    def __enter__(self) -> "SharedFrameStore":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self._tempdir.cleanup()

    def write(self, name: str, frame: pd.DataFrame) -> str:
        output_path = self.path / f"{name}.parquet"
        optimized = optimize_shared_frame(frame)
        optimized.to_parquet(output_path, index=False, engine="pyarrow")
        return str(output_path)


def read_shared_frame(path: str | Path, *, cache: bool = True) -> pd.DataFrame:
    """Read a Parquet frame written by SharedFrameStore."""
    key = str(Path(path))
    if cache:
        cached = _FRAME_CACHE.get(key)
        if cached is not None:
            return cached
    frame = pd.read_parquet(path, engine="pyarrow")
    if cache:
        _FRAME_CACHE[key] = frame
    return frame


def optimize_shared_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a shallow copy with repeated string columns stored categorically."""
    optimized = frame.copy(deep=False)
    for column in optimized.columns:
        series = optimized[column]
        if not (is_object_dtype(series.dtype) or is_string_dtype(series.dtype)):
            continue
        if column in {"symbol", "industry", "benchmark", "benchmark_name", "source"}:
            optimized[column] = series.astype("category")
            continue
        non_null = series.dropna()
        if non_null.empty:
            continue
        unique_ratio = non_null.nunique(dropna=True) / len(non_null)
        if unique_ratio <= 0.20:
            optimized[column] = series.astype("category")
    return optimized
