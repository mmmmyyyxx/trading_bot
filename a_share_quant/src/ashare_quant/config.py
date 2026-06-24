"""Configuration loading and command-line override helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DataConfig:
    provider: str = "akshare"
    universe_type: str = "static_symbols"
    max_symbols: int = 300
    start_date: str = "2022-01-01"
    end_date: str = "2023-12-31"
    adjust: str = "qfq"
    cache_path: str = "data/cache/bars.sqlite"
    symbols: list[str] = field(default_factory=list)
    benchmark_symbol: str = "hs300"
    min_listed_days: int = 120
    min_amount: float = 10_000_000.0
    liquidity_window: int = 20
    liquidity_top_pct: float | None = None
    exclude_st: bool = True
    exclude_paused: bool = True
    exclude_limit_buy: bool = False


@dataclass
class FactorConfig:
    momentum_window: int = 120
    momentum_skip: int = 20
    trend_window: int = 120
    volatility_window: int = 60
    liquidity_window: int = 20
    weights: dict[str, float] = field(
        default_factory=lambda: {
            "momentum": 0.35,
            "trend": 0.25,
            "volatility": 0.25,
            "liquidity": 0.15,
        }
    )


@dataclass
class StrategyConfig:
    rebalance_frequency: str = "M"
    top_k: int = 5
    weighting: str = "equal_weight"
    max_weight: float = 0.2
    min_holdings: int = 1


@dataclass
class RiskConfig:
    max_industry_weight: float = 0.2
    market_filter: bool = False
    market_filter_benchmark: str = "csi500"
    market_filter_window: int = 120
    defensive_exposure: float = 0.5
    target_volatility: float | None = None


@dataclass
class BacktestConfig:
    initial_cash: float = 1_000_000.0
    allow_short: bool = False
    t_plus_one: bool = True
    trade_price: str = "open"
    lot_size: int = 100
    start_date: str | None = None
    end_date: str | None = None


@dataclass
class CostConfig:
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage_bps: float = 2.0


@dataclass
class ReportConfig:
    output_dir: str = "reports"
    make_plots: bool = True


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class AppConfig:
    data: DataConfig = field(default_factory=DataConfig)
    factors: FactorConfig = field(default_factory=FactorConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    cost: CostConfig = field(default_factory=CostConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _coerce_value(value: str) -> Any:
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"none", "null"}:
        return None
    try:
        if "." not in value:
            return int(value)
        return float(value)
    except ValueError:
        return value


def parse_overrides(items: list[str] | None) -> dict[str, Any]:
    """Parse CLI overrides of the form `section.key=value` into a nested dict."""
    parsed: dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"Invalid override {item!r}; expected key=value.")
        key, raw_value = item.split("=", 1)
        cursor = parsed
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = _coerce_value(raw_value)
    return parsed


def load_config(path: str | Path = "configs/default.yaml", overrides: list[str] | None = None) -> AppConfig:
    """Load YAML config and apply optional dotted-key CLI overrides."""
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    raw.pop("project", None)
    override_dict = parse_overrides(overrides)
    _deep_update(raw, override_dict)
    return AppConfig(
        data=DataConfig(**raw.get("data", {})),
        factors=FactorConfig(**raw.get("factors", {})),
        strategy=StrategyConfig(**raw.get("strategy", {})),
        risk=RiskConfig(**raw.get("risk", {})),
        backtest=BacktestConfig(**raw.get("backtest", {})),
        cost=CostConfig(**raw.get("cost", {})),
        report=ReportConfig(**raw.get("report", {})),
        logging=LoggingConfig(**raw.get("logging", {})),
    )
