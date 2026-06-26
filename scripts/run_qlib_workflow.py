"""Run a Qlib workflow config."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys


def main() -> None:
    args = parse_args()
    try:
        import qlib  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Qlib is not installed in this environment. Install with `pip install pyqlib lightgbm` "
            "or use a Python 3.10/3.11 environment if wheels are unavailable."
        ) from exc

    qrun = shutil.which("qrun")
    if not qrun:
        raise SystemExit("Qlib is installed but `qrun` was not found on PATH. Run this script inside the Qlib environment.")
    command = [qrun, args.config]
    env = os.environ.copy()
    if args.experiment_name:
        env["QLIB_EXP_NAME"] = args.experiment_name
    subprocess.run(command, check=True, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/qlib_alpha158_lgb.yaml")
    parser.add_argument("--experiment-name", default="qlib_a_share")
    return parser.parse_args()


if __name__ == "__main__":
    main()
