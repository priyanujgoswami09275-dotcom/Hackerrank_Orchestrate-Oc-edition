from __future__ import annotations

import csv
import json
import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE / "evaluation"))

from harness import (  # noqa: E402
    OUTPUT_FIELDS,
    STEP_FIELDS,
    check_sample_order,
    evaluate,
    fixed_sample_splits,
    read_csv,
)
from failure_analysis import classify_unmatched, delta  # noqa: E402


class EvaluationHarnessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.expected = read_csv(ROOT / "dataset" / "sample_output.csv", OUTPUT_FIELDS)

    def test_public_sample_has_32_cases_and_declared_order(self) -> None:
        self.assertEqual(len(self.expected), 32)
        self.assertEqual(check_sample_order(self.expected), [])

    def test_identical_candidate_scores_perfect(self) -> None:
        metrics, diffs = evaluate(self.expected, self.expected)
        self.assertEqual(metrics.status_correct, 32)
        self.assertEqual(metrics.sequences_correct, 32)
        self.assertEqual(metrics.matched_steps, metrics.expected_steps)
        self.assertEqual(metrics.matched_steps, metrics.predicted_steps)
        self.assertEqual(metrics.matching_fields, metrics.aligned_fields)
        self.assertEqual(diffs, {})

    def test_tuple_metrics_ignore_step_number_and_report_precision_recall(self) -> None:
        actual = {key: dict(value) for key, value in self.expected.items()}
        case_id = sorted(actual)[0]
        row = actual[case_id]
        steps = json.loads(row["steps_json"])
        steps[0]["step_no"] += 10
        steps[-1]["resource_id"] = "synthetic-unmatched-resource"
        row["steps_json"] = json.dumps(steps)

        metrics, _ = evaluate(self.expected, actual)

        self.assertEqual(metrics.expected_steps, 193)
        self.assertEqual(metrics.predicted_steps, 193)
        self.assertEqual(metrics.matched_steps, 192)

    def test_fixed_sample_split_is_sorted_odd_even_and_balanced(self) -> None:
        split_a, split_b = fixed_sample_splits(self.expected)

        self.assertEqual(len(split_a), 16)
        self.assertEqual(len(split_b), 16)
        self.assertEqual(set(split_a).intersection(split_b), set())
        self.assertEqual(set(split_a).union(split_b), set(self.expected))

    def test_object_key_order_does_not_change_sequence_score(self) -> None:
        actual = {key: dict(value) for key, value in self.expected.items()}
        row = actual[sorted(actual)[0]]
        parsed = json.loads(row["steps_json"])
        row["steps_json"] = json.dumps(
            [{key: step[key] for key in reversed(STEP_FIELDS)} for step in parsed]
        )
        metrics, diffs = evaluate(self.expected, actual)
        self.assertEqual(metrics.sequences_correct, 32)
        self.assertEqual(diffs, {})

    def test_reports_missing_and_extra_steps(self) -> None:
        actual = {key: dict(value) for key, value in self.expected.items()}
        case_id = sorted(actual)[0]
        row = actual[case_id]
        row["steps_json"] = "[]"
        metrics, diffs = evaluate(self.expected, actual)
        self.assertEqual(metrics.sequences_correct, 31)
        self.assertIn("missing_steps", diffs[case_id])

    def test_failure_multiset_ignores_step_number(self) -> None:
        step = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "fixture-system",
            "resource_id": "fixture-resource",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "fixture-evidence",
        }
        predicted = {**step, "step_no": 4}

        missing, extra = delta([step], [predicted])

        self.assertEqual(missing, [])
        self.assertEqual(extra, [])

    def test_failure_multiset_preserves_duplicate_counts(self) -> None:
        step = {
            "step_no": 1,
            "phase": "VERIFICATION",
            "system_id": "fixture-system",
            "resource_id": "fixture-resource",
            "operation": "VERIFY_RECORD_PRESENT",
            "state": "PRESENT",
            "evidence_id": "fixture-evidence",
        }

        missing, extra = delta([step, {**step, "step_no": 2}], [step])

        self.assertEqual(len(missing), 1)
        self.assertEqual(extra, [])

    def test_failure_buckets_only_single_field_pairs(self) -> None:
        expected = {
            "phase": "VERIFICATION",
            "system_id": "fixture-system",
            "resource_id": "fixture-resource",
            "operation": "VERIFY_RECORD_ABSENT",
            "state": "ABSENT",
            "evidence_id": "fixture-evidence",
        }
        predicted = {**expected, "evidence_id": ""}

        paired, missing, extra = classify_unmatched([expected], [predicted])

        self.assertEqual(paired["evidence_id"], 1)
        self.assertEqual(missing, [])
        self.assertEqual(extra, [])

    def test_absence_citations_are_temporal_and_artifact_backed(self) -> None:
        requests = read_csv(
            ROOT / "dataset" / "sample_deletion_requests.csv",
            ("case_id", "email", "requested_at", "reported_status", "reported_at", "audit_at", "request_text"),
        )
        with (ROOT / "dataset" / "evidence_files.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            manifest = {row["file_id"]: row for row in csv.DictReader(handle)}
        audited = 0
        omitted_from_complete_listing = 0
        explicit_not_found = 0
        for case_id, row in sorted(self.expected.items()):
            steps = json.loads(row["steps_json"])
            for step in steps:
                if (
                    row["deletion_status"] != "COMPLETE"
                    or step["operation"] != "VERIFY_RECORD_ABSENT"
                ):
                    continue
                evidence_id = step["evidence_id"]
                if not evidence_id:
                    continue
                evidence = manifest[evidence_id]
                self.assertLessEqual(evidence["captured_at"], requests[case_id]["audit_at"])
                path = ROOT / "dataset" / evidence["file_path"]
                raw = path.read_text(encoding="utf-8", errors="replace")
                resource_id = step["resource_id"]
                audited += 1

                if resource_id in raw:
                    explicit_not_found += 1
                    if path.suffix == ".json":
                        document = json.loads(raw)
                        matches = list(_walk_resource_objects(document, resource_id))
                        self.assertTrue(matches)
                        self.assertTrue(
                            any(
                                item.get("status_code") == 404
                                or item.get("rows") == 0
                                or item.get("hits") == []
                                for item in matches
                            ),
                            f"{case_id}: resource mention is not an explicit not-found result",
                        )
                    else:
                        self.assertTrue(
                            "rows=0" in raw or "http_status=404" in raw,
                            f"{case_id}: log does not show a zero-row/404 result",
                        )
                else:
                    omitted_from_complete_listing += 1
                    self.assertIn(path.suffix, {".sql", ".json"})
                    if path.suffix == ".json":
                        document = json.loads(raw)
                        snapshots = list(_walk_snapshot_lists(document, step["system_id"]))
                        self.assertTrue(
                            snapshots,
                            f"{case_id}: JSON omission is not within a named snapshot listing",
                        )
                        for records in snapshots:
                            self.assertFalse(
                                any(
                                    isinstance(record, dict)
                                    and record.get("resource_id") == resource_id
                                    for record in records
                                )
                            )
                    else:
                        import sqlite3

                        connection = sqlite3.connect(":memory:")
                        try:
                            connection.executescript(raw)
                            tables = [
                                item[0]
                                for item in connection.execute(
                                    "SELECT name FROM sqlite_master WHERE type='table'"
                                )
                            ]
                            listing_tables = []
                            for table in tables:
                                columns = {
                                    info[1]
                                    for info in connection.execute(
                                        f'PRAGMA table_info("{table}")'
                                    )
                                }
                                if "resource_id" not in columns:
                                    continue
                                listing_tables.append(table)
                                count = connection.execute(
                                    f'SELECT COUNT(*) FROM "{table}" WHERE resource_id = ?',
                                    (resource_id,),
                                ).fetchone()[0]
                                self.assertEqual(count, 0)
                            self.assertTrue(listing_tables, f"{case_id}: no structured listing")
                        finally:
                            connection.close()

        self.assertEqual(audited, 10)
        self.assertEqual(omitted_from_complete_listing, 4)
        self.assertEqual(explicit_not_found, 6)


def _walk_resource_objects(value, resource_id):
    if isinstance(value, dict):
        if value.get("resource_id") == resource_id:
            yield value
        for child in value.values():
            yield from _walk_resource_objects(child, resource_id)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_resource_objects(child, resource_id)


def _walk_snapshot_lists(value, system_id):
    if isinstance(value, dict):
        if (
            value.get("data_store") == system_id
            and isinstance(value.get("records"), list)
        ):
            yield value["records"]
        for child in value.values():
            yield from _walk_snapshot_lists(child, system_id)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_snapshot_lists(child, system_id)


if __name__ == "__main__":
    unittest.main()
