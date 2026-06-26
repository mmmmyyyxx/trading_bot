"""Build symbol files for expanded A-share universe experiments."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ashare_adapter.akshare_downloader import AKShareDownloader
from ashare_adapter.indexes import load_index_constituents, symbols_from_constituents, write_constituents
from ashare_adapter.metadata import normalize_symbol

INDEX_KEYS = {
    "hs300": "000300",
    "csi500": "000905",
    "csi1000": "000852",
}

UNIVERSE_INDEXES = {
    "hs300_current": ["hs300"],
    "csi800_current": ["hs300", "csi500"],
    "csi1800_current": ["hs300", "csi500", "csi1000"],
}


def main() -> None:
    args = parse_args()
    metadata = build_universe(
        universe_name=args.universe_name,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        metadata_cache=args.metadata_cache,
        refresh_constituents=args.refresh_constituents,
        candidate_pool_size=args.candidate_pool_size,
        max_symbols=args.max_symbols,
    )
    print(f"Wrote symbols: {metadata['symbols_file']}")
    print(f"Wrote metadata: {metadata['metadata_file']}")


def build_universe(
    universe_name: str,
    output_dir: str | Path = "data/cache/expanded_universes",
    cache_dir: str | Path = "data/cache",
    metadata_cache: str | Path = "data/cache/akshare_metadata.parquet",
    refresh_constituents: bool = False,
    candidate_pool_size: int | None = None,
    max_symbols: int | None = None,
) -> dict[str, Any]:
    """Build a universe symbol file and metadata sidecar."""

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    if universe_name in UNIVERSE_INDEXES:
        symbols, constituents = _build_index_universe(
            universe_name=universe_name,
            cache_dir=cache,
            refresh_constituents=refresh_constituents,
            max_symbols=max_symbols,
        )
        universe_mode = "current_constituent"
        selected_mode = "eligible_only"
        dynamic_top_n = None
        candidate_size = None
        caveats = [
            "Current index constituents are used historically, so current-constituent/survivorship bias remains.",
            "This symbol file does not represent historical index membership.",
        ]
    elif universe_name.startswith("dynamic_candidate"):
        size = candidate_pool_size or _candidate_size_from_name(universe_name)
        dynamic_top_n = _dynamic_top_n_from_name(universe_name)
        symbols = _build_current_listed_candidates(metadata_cache, size)
        constituents = pd.DataFrame({"symbol": symbols})
        universe_mode = "current_listed_candidate"
        selected_mode = f"dynamic_liquidity_top{dynamic_top_n}" if dynamic_top_n else "dynamic_liquidity_topN"
        candidate_size = size
        caveats = [
            "Candidate symbols come from the current listed universe and may miss historical delisted stocks.",
            "Candidate symbols are deterministic board/industry-stratified samples, not historical liquidity constituents.",
            "Dynamic selected universe must be formed later with backward-looking rolling amount.",
        ]
    else:
        raise ValueError(f"Unsupported universe_name: {universe_name}")

    symbols_file = out / f"{universe_name}_symbols.txt"
    metadata_file = out / f"{universe_name}_metadata.json"
    constituents_file = out / f"{universe_name}_constituents.csv"
    _write_symbols(symbols, symbols_file)
    if not constituents.empty:
        constituents.to_csv(constituents_file, index=False)

    metadata = {
        "universe_name": universe_name,
        "universe_mode": universe_mode,
        "selected_mode": selected_mode,
        "candidate_pool_size": candidate_size,
        "dynamic_liquidity_top_n": dynamic_top_n,
        "requested_symbols": len(symbols),
        "symbols_file": str(symbols_file),
        "constituents_file": str(constituents_file) if constituents_file.exists() else None,
        "metadata_file": str(metadata_file),
        "caveats": caveats,
    }
    metadata_file.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def _build_index_universe(
    universe_name: str,
    cache_dir: Path,
    refresh_constituents: bool,
    max_symbols: int | None,
) -> tuple[list[str], pd.DataFrame]:
    frames = []
    for key in UNIVERSE_INDEXES[universe_name]:
        frame = load_index_constituents(
            index_symbol=INDEX_KEYS[key],
            cache_path=cache_dir / f"{key}_constituents.parquet",
            refresh=refresh_constituents,
        )
        frame = frame.copy()
        frame["index_key"] = key
        frames.append(frame)
    merged = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    merged = merged.drop_duplicates("symbol").reset_index(drop=True)
    if max_symbols:
        merged = merged.head(max_symbols).reset_index(drop=True)
    symbols = symbols_from_constituents(merged)
    return symbols, merged


def _build_current_listed_candidates(metadata_cache: str | Path, candidate_pool_size: int) -> list[str]:
    cache = Path(metadata_cache)
    if not cache.exists():
        AKShareDownloader(metadata_cache_path=cache, refresh_metadata=False)
    if cache.suffix.lower() in {".parquet", ".pq"}:
        metadata = pd.read_parquet(cache)
    else:
        metadata = pd.read_csv(cache)
    if "symbol" not in metadata.columns:
        raise ValueError(f"Metadata cache must contain symbol column: {cache}")
    data = metadata.copy()
    data["symbol"] = data["symbol"].map(normalize_symbol)
    if "is_st" in data.columns:
        data = data[~data["is_st"].fillna(False).astype(bool)]
    data = data.drop_duplicates("symbol")
    if len(data) <= candidate_pool_size:
        return sorted(data["symbol"].tolist())
    if "industry" in data.columns:
        data["industry_key"] = data["industry"].fillna("").astype(str).str.strip()
    else:
        data["industry_key"] = "unknown"
    data.loc[data["industry_key"] == "", "industry_key"] = "unknown"
    data["board"] = data["symbol"].map(_board_bucket)
    data["sample_key"] = data["symbol"].map(_stable_sample_key)
    selected = _stratified_symbol_sample(data, candidate_pool_size)
    return sorted(selected["symbol"].tolist())


def _stratified_symbol_sample(data: pd.DataFrame, target_size: int) -> pd.DataFrame:
    group_cols = ["board", "industry_key"]
    groups = data.groupby(group_cols, dropna=False).size().rename("group_size").reset_index()
    total = float(groups["group_size"].sum())
    groups["exact"] = groups["group_size"] / total * int(target_size)
    groups["take"] = groups["exact"].astype(int).clip(upper=groups["group_size"])
    remaining = int(target_size) - int(groups["take"].sum())
    if remaining > 0:
        groups["fraction"] = groups["exact"] - groups["take"]
        groups = groups.sort_values(["fraction", "group_size", "board", "industry_key"], ascending=[False, False, True, True])
        idx = 0
        while remaining > 0 and idx < len(groups):
            row_index = groups.index[idx]
            if groups.at[row_index, "take"] < groups.at[row_index, "group_size"]:
                groups.at[row_index, "take"] += 1
                remaining -= 1
            idx = (idx + 1) % len(groups)
    allocations = {
        (row["board"], row["industry_key"]): int(row["take"])
        for _, row in groups.iterrows()
        if int(row["take"]) > 0
    }
    pieces = []
    for key, frame in data.groupby(group_cols, dropna=False):
        take = allocations.get(key, 0)
        if take:
            pieces.append(frame.sort_values(["sample_key", "symbol"]).head(take))
    selected = pd.concat(pieces, ignore_index=True) if pieces else data.iloc[0:0].copy()
    if len(selected) < target_size:
        missing = int(target_size) - len(selected)
        selected_symbols = set(selected["symbol"])
        filler = data[~data["symbol"].isin(selected_symbols)].sort_values(["sample_key", "symbol"]).head(missing)
        selected = pd.concat([selected, filler], ignore_index=True)
    return selected.head(target_size)


def _board_bucket(symbol: str) -> str:
    code, market = normalize_symbol(symbol).split(".", 1)
    if market == "BJ":
        return "bj"
    if code.startswith(("688", "689")):
        return "star"
    if code.startswith(("300", "301", "302")):
        return "chinext"
    if market == "SH":
        return "sh_main"
    if market == "SZ":
        return "sz_main"
    return "other"


def _stable_sample_key(symbol: str) -> str:
    return hashlib.sha1(f"dynamic_candidate_v1:{normalize_symbol(symbol)}".encode("utf-8")).hexdigest()


def _candidate_size_from_name(name: str) -> int:
    for token in name.split("_"):
        if token.startswith("candidate"):
            value = token.replace("candidate", "")
            if value.isdigit():
                return int(value)
    raise ValueError(f"Unable to infer candidate pool size from {name!r}")


def _dynamic_top_n_from_name(name: str) -> int | None:
    for token in name.split("_"):
        if token.startswith("top"):
            value = token.replace("top", "")
            if value.isdigit():
                return int(value)
    return None


def _write_symbols(symbols: list[str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(symbols) + ("\n" if symbols else ""), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--universe-name", required=True)
    parser.add_argument("--output-dir", default="data/cache/expanded_universes")
    parser.add_argument("--cache-dir", default="data/cache")
    parser.add_argument("--metadata-cache", default="data/cache/akshare_metadata.parquet")
    parser.add_argument("--refresh-constituents", action="store_true")
    parser.add_argument("--candidate-pool-size", type=int, default=None)
    parser.add_argument("--max-symbols", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    main()
