"""Guards that keep formal research reports tied to real data."""

from __future__ import annotations

from pathlib import Path
from typing import Any


REAL_DATA_TYPE = "real_akshare"
SYNTHETIC_TEST_REPORT_ROOT = Path("reports/synthetic_test_only")


def is_formal_report_path(path: str | Path) -> bool:
    """Return whether a path is a formal report location."""

    normalized = Path(path).as_posix().lower()
    name = Path(path).name.lower()
    parent = Path(path).parent.as_posix().lower()
    if "reports/synthetic_test_only" in normalized:
        return False
    if normalized in {
        "reports/baseline_comparison.csv",
        "reports/baseline_comparison.md",
        "reports/universe_expansion_comparison.csv",
        "reports/universe_expansion_comparison.md",
    }:
        return True
    if normalized.startswith("reports/rolling_baseline_comparison"):
        return True
    if name == "run_manifest.json" and (normalized == "run_manifest.json" or normalized.startswith("reports/")):
        return True
    if name in {"summary.json", "summary.md"} and "/reports/alpha158_" in f"/{parent}/":
        return True
    if name in {"summary.json", "summary.md"} and parent.endswith("reports/real_data_smoke_test"):
        return True
    return False


def assert_formal_report_uses_real_data(
    path: str | Path,
    payload: dict[str, Any] | None = None,
    *,
    data_type: str | None = None,
    synthetic_data: bool | None = None,
    mock_data: bool | None = None,
    allow_synthetic_test: bool = False,
) -> None:
    """Raise if a formal report would be written without a real-data marker."""

    target = Path(path)
    if allow_synthetic_test and SYNTHETIC_TEST_REPORT_ROOT.as_posix() in target.as_posix():
        return
    if not is_formal_report_path(target):
        return

    data_section = (payload or {}).get("data", {}) if isinstance(payload, dict) else {}
    effective_data_type = data_type if data_type is not None else data_section.get("data_type")
    effective_synthetic = synthetic_data if synthetic_data is not None else data_section.get("synthetic_data")
    effective_mock = mock_data if mock_data is not None else data_section.get("mock_data")

    if effective_data_type != REAL_DATA_TYPE or bool(effective_synthetic) or bool(effective_mock):
        raise ValueError(
            f"Refusing to write formal report {target} without real AKShare data markers "
            f"(data_type={effective_data_type!r}, synthetic_data={effective_synthetic!r}, mock_data={effective_mock!r})."
        )


def real_data_markers(download_source: str = "akshare") -> dict[str, Any]:
    """Return the manifest fields required for formal real-data reports."""

    return {
        "data_type": REAL_DATA_TYPE,
        "synthetic_data": False,
        "mock_data": False,
        "download_source": download_source,
    }
