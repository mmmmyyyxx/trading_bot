"""Configuration objects for the Qlib A-share adapter."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class UniverseConfig:
    """Backward-looking A-share universe filter settings."""

    exclude_st: bool = True
    exclude_paused: bool = True
    exclude_limit_buy: bool = False
    min_listed_days: int = 120
    min_amount: float = 10_000_000.0
    liquidity_window: int = 20
    dynamic_liquidity_top_n: int | None = None


@dataclass(frozen=True)
class CostConfig:
    """A-share transaction cost assumptions."""

    open_cost: float = 0.00031
    close_cost: float = 0.00081
    min_cost: float = 5.0
    commission_rate: float = 0.0003
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 2.0


@dataclass(frozen=True)
class DataConfig:
    """Data preparation settings."""

    start_date: str = "2020-01-01"
    end_date: str = "2023-12-31"
    adjust: str = "qfq"
    symbols: list[str] = field(default_factory=list)
    bars_path: str = "data/ashare_bars.parquet"
    qlib_dir: str = "data/qlib_cn_ashare"


@dataclass(frozen=True)
class DiagnosticsConfig:
    """Local diagnostics settings."""

    horizons: list[int] = field(default_factory=lambda: [1, 5, 20])
    n_groups: int = 5
    min_cross_section: int = 30
    oos_start_date: str | None = None


@dataclass(frozen=True)
class ProjectConfig:
    """Top-level project config used by scripts."""

    data: DataConfig = field(default_factory=DataConfig)
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    diagnostics: DiagnosticsConfig = field(default_factory=DiagnosticsConfig)


def load_config(path: str | Path) -> ProjectConfig:
    """Load a YAML config into dataclasses, ignoring unknown top-level keys."""

    raw = _read_yaml(path)
    return ProjectConfig(
        data=DataConfig(**raw.get("data", {})),
        universe=UniverseConfig(**raw.get("universe", {})),
        cost=CostConfig(**raw.get("cost", {})),
        diagnostics=DiagnosticsConfig(**raw.get("diagnostics", {})),
    )


def _read_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config must be a mapping: {path}")
    return data
