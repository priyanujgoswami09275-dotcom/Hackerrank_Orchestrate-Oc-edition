#!/usr/bin/env python3
"""Compare a candidate output CSV with the public sample answers."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))
from pramaantrace.constants import OPERATION_ORDER, PHASE_ORDER  # noqa: E402


OUTPUT_FIELDS = ("case_id", "deletion_status", "steps_json")
STEP_FIELDS = (
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
)
@dataclass(frozen=True)
class Metrics:
    cases: int
    status_correct: int
    expected_steps: int
    matched_steps: int
    aligned_fields: int
    matching_fields: int
    sequences_correct: int


def read_csv(path: Path, required_header: Iterable[str]) -> dict[str, dict[str, str]]:
    """Read a CSV indexed by case_id, rejecting malformed or duplicate rows."""
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != tuple(required_header):
            raise ValueError(
                f"{path}: expected header {','.join(required_header)!r}, "
                f"got {','.join(reader.fieldnames or ())!r}"
            )
        rows: dict[str, dict[str, str]] = {}
        for line_no, row in enumerate(reader, start=2):
            case_id = (row.get("case_id") or "").strip()
            if not case_id:
                raise ValueError(f"{path}:{line_no}: empty case_id")
            if case_id in rows:
                raise ValueError(f"{path}:{line_no}: duplicate case_id {case_id!r}")
            rows[case_id] = row
    return rows


def parse_steps(row: dict[str, str], case_id: str, source: str) -> list[dict[str, Any]]:
    try:
        steps = json.loads(row["steps_json"])
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError(f"{source}: invalid steps_json for {case_id}: {exc}") from exc
    if not isinstance(steps, list):
        raise ValueError(f"{source}: steps_json for {case_id} is not an array")
    for index, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            raise ValueError(f"{source}: step {index} for {case_id} is not an object")
        if set(step) != set(STEP_FIELDS):
            raise ValueError(
                f"{source}: step {index} for {case_id} has keys "
                f"{sorted(step)}, expected {sorted(STEP_FIELDS)}"
            )
    return steps


def step_key(step: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(step[field] for field in STEP_FIELDS)


def normalized_steps(steps: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    """Normalize object-key order while retaining array order."""
    return [step_key(step) for step in steps]


def evaluate(
    expected_rows: dict[str, dict[str, str]],
    actual_rows: dict[str, dict[str, str]],
) -> tuple[Metrics, dict[str, dict[str, Any]]]:
    """Score only expected sample cases; candidate files may contain all 518 cases."""
    total_status_correct = 0
    expected_step_count = 0
    matched_step_count = 0
    aligned_field_count = 0
    matching_field_count = 0
    sequences_correct = 0
    diffs: dict[str, dict[str, Any]] = {}

    for case_id in sorted(expected_rows):
        expected = expected_rows[case_id]
        actual = actual_rows.get(case_id)
        if actual is None:
            diffs[case_id] = {
                "error": "candidate row missing",
                "expected_status": expected["deletion_status"],
            }
            e_steps = parse_steps(expected, case_id, "expected")
            expected_step_count += len(e_steps)
            aligned_field_count += max(1, len(e_steps)) * len(STEP_FIELDS)
            continue

        expected_steps = parse_steps(expected, case_id, "expected")
        actual_steps = parse_steps(actual, case_id, "candidate")
        expected_keys = normalized_steps(expected_steps)
        actual_keys = normalized_steps(actual_steps)

        status_matches = actual["deletion_status"] == expected["deletion_status"]
        total_status_correct += int(status_matches)
        expected_step_count += len(expected_steps)

        expected_counter = Counter(expected_keys)
        actual_counter = Counter(actual_keys)
        matched_step_count += sum((expected_counter & actual_counter).values())

        aligned_count = max(len(expected_steps), len(actual_steps))
        aligned_field_count += aligned_count * len(STEP_FIELDS)
        for index in range(aligned_count):
            if index >= len(expected_steps) or index >= len(actual_steps):
                continue
            for field in STEP_FIELDS:
                matching_field_count += int(
                    expected_steps[index][field] == actual_steps[index][field]
                )

        sequence_matches = expected_keys == actual_keys
        sequences_correct += int(sequence_matches)

        if not status_matches or not sequence_matches:
            case_diff: dict[str, Any] = {}
            if not status_matches:
                case_diff["status"] = {
                    "expected": expected["deletion_status"],
                    "actual": actual["deletion_status"],
                }
            if not sequence_matches:
                missing = list((expected_counter - actual_counter).elements())
                extra = list((actual_counter - expected_counter).elements())
                if missing:
                    case_diff["missing_steps"] = [
                        dict(zip(STEP_FIELDS, item)) for item in missing
                    ]
                if extra:
                    case_diff["extra_steps"] = [
                        dict(zip(STEP_FIELDS, item)) for item in extra
                    ]
                positional = []
                for index in range(aligned_count):
                    if index >= len(expected_steps):
                        positional.append(
                            {"index": index + 1, "expected": None, "actual": actual_steps[index]}
                        )
                    elif index >= len(actual_steps):
                        positional.append(
                            {"index": index + 1, "expected": expected_steps[index], "actual": None}
                        )
                    else:
                        field_diff = {
                            field: {
                                "expected": expected_steps[index][field],
                                "actual": actual_steps[index][field],
                            }
                            for field in STEP_FIELDS
                            if expected_steps[index][field] != actual_steps[index][field]
                        }
                        if field_diff:
                            positional.append({"index": index + 1, "fields": field_diff})
                if positional:
                    case_diff["positional_differences"] = positional
            diffs[case_id] = case_diff

    metrics = Metrics(
        cases=len(expected_rows),
        status_correct=total_status_correct,
        expected_steps=expected_step_count,
        matched_steps=matched_step_count,
        aligned_fields=aligned_field_count,
        matching_fields=matching_field_count,
        sequences_correct=sequences_correct,
    )
    return metrics, diffs


def percentage(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "n/a (0/0)"
    return f"{100.0 * numerator / denominator:.2f}% ({numerator}/{denominator})"


def sort_key(step: dict[str, Any]) -> tuple[Any, ...]:
    phase = step["phase"]
    operation = step["operation"]
    return (
        PHASE_ORDER.index(phase) if phase in PHASE_ORDER else len(PHASE_ORDER),
        OPERATION_ORDER.get(phase, ()).index(operation)
        if operation in OPERATION_ORDER.get(phase, ())
        else len(OPERATION_ORDER.get(phase, ())),
        step["system_id"],
        step["resource_id"],
    )


def check_sample_order(rows: dict[str, dict[str, str]]) -> list[str]:
    """Return case IDs whose sample steps do not follow the declared sort contract."""
    failures = []
    for case_id, row in sorted(rows.items()):
        steps = parse_steps(row, case_id, "expected")
        if [step.get("step_no") for step in steps] != list(range(1, len(steps) + 1)):
            failures.append(f"{case_id}: nonconsecutive step_no")
        if [sort_key(step) for step in steps] != sorted(sort_key(step) for step in steps):
            failures.append(f"{case_id}: operation/system/resource ordering")
    return failures


def main(argv: list[str] | None = None) -> int:
    root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "predictions",
        nargs="?",
        type=Path,
        default=root / "output.csv",
        help="candidate CSV (default: repo-root output.csv)",
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=root / "dataset" / "sample_output.csv",
        help="expected sample CSV",
    )
    parser.add_argument("--no-diffs", action="store_true", help="suppress per-case failure details")
    args = parser.parse_args(argv)

    try:
        expected = read_csv(args.expected, OUTPUT_FIELDS)
        actual = read_csv(args.predictions, OUTPUT_FIELDS)
        metrics, diffs = evaluate(expected, actual)
        order_failures = check_sample_order(expected)
    except (OSError, ValueError) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2

    print(f"Expected sample cases: {metrics.cases}")
    print(f"Candidate rows: {len(actual)}")
    print(f"Case status accuracy: {percentage(metrics.status_correct, metrics.cases)}")
    print(
        "Step-level accuracy: "
        f"{percentage(metrics.matched_steps, metrics.expected_steps)}"
    )
    print(
        "Field-level accuracy: "
        f"{percentage(metrics.matching_fields, metrics.aligned_fields)}"
    )
    print(
        "Sequence accuracy: "
        f"{percentage(metrics.sequences_correct, metrics.cases)}"
    )
    print(
        "Sample sort contract: "
        + ("PASS (all sample cases)" if not order_failures else "FAIL")
    )
    if order_failures:
        for failure in order_failures:
            print(f"  {failure}")
    if diffs and not args.no_diffs:
        print("Per-case differences:")
        for case_id, diff in sorted(diffs.items()):
            print(f"  {case_id}: {json.dumps(diff, ensure_ascii=False, sort_keys=True)}")
    elif not diffs:
        print("Per-case differences: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
