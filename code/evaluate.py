#!/usr/bin/env python3
"""Run the public-sample baseline and score it with the M1 evaluator."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path


CODE = Path(__file__).resolve().parent
ROOT = CODE.parent


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--disable-media",
        action="store_true",
        help="score the structured-only baseline for a media delta comparison",
    )
    parser.add_argument(
        "--no-diffs",
        action="store_true",
        help="suppress the evaluator's per-case difference details",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="pramaantrace-eval-") as directory:
        candidate = Path(directory) / "sample-output.csv"
        run_command = [
            sys.executable,
            str(CODE / "run.py"),
            "--requests",
            "dataset/sample_deletion_requests.csv",
            "--output",
            str(candidate),
        ]
        if args.disable_media:
            run_command.append("--disable-media")
        run_result = subprocess.run(run_command, cwd=ROOT, check=False)
        if run_result.returncode:
            return run_result.returncode

        evaluation_command = [
            sys.executable,
            str(CODE / "evaluation" / "harness.py"),
            str(candidate),
        ]
        if args.no_diffs:
            evaluation_command.append("--no-diffs")
        return subprocess.run(evaluation_command, cwd=ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
