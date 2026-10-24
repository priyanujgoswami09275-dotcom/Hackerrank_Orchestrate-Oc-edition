#!/usr/bin/env python3
"""Report per-case sample step differences as multiset deltas."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any

from harness import OUTPUT_FIELDS, parse_steps, read_csv


CONTENT_FIELDS = (
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
)


def content_key(step: dict[str, Any]) -> tuple[Any, ...]:
    """Use the complete step content but ignore sequence numbering."""
    return tuple(step[field] for field in CONTENT_FIELDS)


def delta(
    expected: list[dict[str, Any]], predicted: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    expected_counts = Counter(content_key(step) for step in expected)
    predicted_counts = Counter(content_key(step) for step in predicted)
    missing = expected_counts - predicted_counts
    extra = predicted_counts - expected_counts

    def expand(counts: Counter[tuple[Any, ...]]) -> list[dict[str, Any]]:
        rows = [
            dict(zip(CONTENT_FIELDS, key))
            for key, count in sorted(counts.items(), key=lambda item: item[0])
            for _ in range(count)
        ]
        return rows

    return expand(missing), expand(extra)


def analyze(
    expected_rows: dict[str, dict[str, str]],
    predicted_rows: dict[str, dict[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for case_id in sorted(expected_rows):
        expected_row = expected_rows[case_id]
        predicted_row = predicted_rows.get(case_id)
        expected_steps = parse_steps(expected_row, case_id, "expected")
        if predicted_row is None:
            predicted_steps: list[dict[str, Any]] = []
            predicted_status = "<missing row>"
        else:
            predicted_steps = parse_steps(predicted_row, case_id, "predicted")
            predicted_status = predicted_row["deletion_status"]
        missing, extra = delta(expected_steps, predicted_steps)
        if (
            expected_row["deletion_status"] != predicted_status
            or missing
            or extra
        ):
            result[case_id] = {
                "expected_status": expected_row["deletion_status"],
                "predicted_status": predicted_status,
                "missing_expected_steps": missing,
                "extra_predicted_steps": extra,
            }
    return result


def classify_unmatched(
    missing_steps: list[dict[str, Any]],
    extra_steps: list[dict[str, Any]],
) -> tuple[Counter[str], list[dict[str, Any]], list[dict[str, Any]]]:
    """Pair only unmatched steps that differ in exactly one content field."""
    missing_keys = [content_key(step) for step in missing_steps]
    extra_keys = [content_key(step) for step in extra_steps]
    candidates = []
    for missing_index, missing_key in enumerate(missing_keys):
        for extra_index, extra_key in enumerate(extra_keys):
            changed = [
                field
                for field, left, right in zip(
                    CONTENT_FIELDS, missing_key, extra_key
                )
                if left != right
            ]
            if len(changed) == 1:
                candidates.append(
                    (
                        changed[0],
                        missing_key,
                        extra_key,
                        missing_index,
                        extra_index,
                    )
                )

    paired_fields: Counter[str] = Counter()
    paired_missing: set[int] = set()
    paired_extra: set[int] = set()
    for field, _, _, missing_index, extra_index in sorted(candidates):
        if missing_index in paired_missing or extra_index in paired_extra:
            continue
        paired_fields[field] += 1
        paired_missing.add(missing_index)
        paired_extra.add(extra_index)

    unpaired_missing = [
        step
        for index, step in enumerate(missing_steps)
        if index not in paired_missing
    ]
    unpaired_extra = [
        step for index, step in enumerate(extra_steps) if index not in paired_extra
    ]
    return paired_fields, unpaired_missing, unpaired_extra


def summarize(
    diffs: dict[str, dict[str, Any]]
) -> tuple[Counter, Counter, Counter]:
    missing: Counter[tuple[str, str, str]] = Counter()
    extra: Counter[tuple[str, str, str]] = Counter()
    one_field: Counter[str] = Counter()
    for diff in diffs.values():
        paired, unpaired_missing, unpaired_extra = classify_unmatched(
            diff["missing_expected_steps"],
            diff["extra_predicted_steps"],
        )
        one_field.update(paired)
        for step in unpaired_missing:
            missing[(step["phase"], step["operation"], step["state"])] += 1
        for step in unpaired_extra:
            extra[(step["phase"], step["operation"], step["state"])] += 1
    return missing, extra, one_field


def main() -> int:
    repo_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "predictions",
        nargs="?",
        type=Path,
        help="candidate CSV; defaults to a temporary sample baseline run",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=repo_root / "dataset" / "sample_output.csv",
        help="public sample labels used only for evaluation",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="print per-case missing/extra counts without step tuples",
    )
    args = parser.parse_args()

    expected_rows = read_csv(args.expected, OUTPUT_FIELDS)
    if args.predictions is None:
        with tempfile.TemporaryDirectory(
            prefix="pramaantrace-failure-analysis-"
        ) as directory:
            prediction_path = Path(directory) / "sample-output.csv"
            command = [
                sys.executable,
                str(repo_root / "code" / "run.py"),
                "--requests",
                "dataset/sample_deletion_requests.csv",
                "--output",
                str(prediction_path),
            ]
            subprocess.run(command, cwd=repo_root, check=True)
            predicted_rows = read_csv(prediction_path, OUTPUT_FIELDS)
            diffs = analyze(expected_rows, predicted_rows)
    else:
        predicted_rows = read_csv(args.predictions, OUTPUT_FIELDS)
        diffs = analyze(expected_rows, predicted_rows)
    missing, extra, one_field = summarize(diffs)
    print(f"Cases with any status or content-step difference: {len(diffs)}")
    print(f"One-field content mismatches: {sum(one_field.values())}")
    print("One-field mismatches by field:")
    for field, count in sorted(one_field.items()):
        print(f"  {field}: {count}")
    print(f"Unpaired missing expected content steps: {sum(missing.values())}")
    print(f"Unpaired extra predicted content steps: {sum(extra.values())}")
    print("Unpaired missing by phase/operation/state:")
    for key, count in sorted(missing.items()):
        print(f"  {key}: {count}")
    print("Unpaired extra by phase/operation/state:")
    for key, count in sorted(extra.items()):
        print(f"  {key}: {count}")
    print("Per-case multiset differences:")
    for case_id, diff in diffs.items():
        if args.compact:
            value = {
                "expected_status": diff["expected_status"],
                "predicted_status": diff["predicted_status"],
                "missing_count": len(diff["missing_expected_steps"]),
                "extra_count": len(diff["extra_predicted_steps"]),
            }
        else:
            value = diff
        print(f"  {case_id}: {json.dumps(value, ensure_ascii=False, sort_keys=True)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
