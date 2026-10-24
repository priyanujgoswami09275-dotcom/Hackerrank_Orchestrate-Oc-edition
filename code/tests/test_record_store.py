from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from pramaantrace.loader import load_dataset, normalize_sql_file  # noqa: E402
from pramaantrace.store import (  # noqa: E402
    CapturedText,
    NormalizedRecord,
    RecordStore,
    parse_timestamp,
)


class RecordStoreTests(unittest.TestCase):
    def test_every_record_query_applies_audit_cutoff(self) -> None:
        store = RecordStore()
        for capture_id, captured_at in (
            ("fixture-before", "2026-05-01T00:00:00Z"),
            ("fixture-after", "2026-05-03T00:00:00Z"),
        ):
            store.add_record(
                NormalizedRecord(
                    capture_id=capture_id,
                    captured_at=captured_at,
                    topology="fixture",
                    system_id="fixture_service",
                    resource_id="fixture_record",
                    category="FIXTURE",
                )
            )

        visible = store.query(
            audit_at="2026-05-02T00:00:00Z",
            system_id="fixture_service",
        )
        self.assertEqual([record.capture_id for record in visible], ["fixture-before"])
        self.assertEqual(store.record_count(audit_at="2026-05-02T00:00:00Z"), 1)

    def test_text_reads_are_gated_too(self) -> None:
        store = RecordStore()
        store.add_text(
            CapturedText(
                capture_id="fixture-document",
                captured_at="2026-05-03T00:00:00Z",
                file_path="fixture.txt",
                text="fixture",
            )
        )
        self.assertIsNone(
            store.read_text(
                audit_at="2026-05-02T00:00:00Z",
                capture_id="fixture-document",
            )
        )
        self.assertIsNotNone(
            store.read_text(
                audit_at="2026-05-03T00:00:00Z",
                capture_id="fixture-document",
            )
        )

    def test_sql_loader_fails_loudly_for_unmapped_table(self) -> None:
        store = RecordStore()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "unmapped.sql"
            path.write_text(
                "CREATE TABLE unexpected_table (resource_id TEXT);",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "unmapped SQL table"):
                normalize_sql_file(
                    store,
                    evidence_id="fixture-capture",
                    captured_at="2026-05-01T00:00:00Z",
                    path=path,
                )


class DatasetLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_dataset(ROOT)

    def test_loads_every_structured_artifact_and_defers_multimodal(self) -> None:
        self.assertEqual(self.bundle.evidence_file_count, 94)
        self.assertEqual(self.bundle.loaded_evidence_count, 79)
        self.assertEqual(len(self.bundle.skipped_multimodal), 15)
        self.assertEqual(
            len(self.bundle.tables["deletion_requests.csv"]),
            518,
        )
        self.assertEqual(
            len(self.bundle.tables["user_identities.csv"]),
            850,
        )
        self.assertGreater(
            self.bundle.store.record_count(audit_at="2026-10-24T00:00:00Z"),
            0,
        )

    def test_latest_cutoff_never_returns_a_capture_from_the_future(self) -> None:
        cutoff = "2026-09-01T00:00:00Z"
        visible = self.bundle.store.query(audit_at=cutoff)
        self.assertTrue(
            all(parse_timestamp(record.captured_at) <= parse_timestamp(cutoff) for record in visible)
        )

    def test_empty_inventory_collection_is_preserved_as_a_gated_scope(self) -> None:
        scopes = self.bundle.store.query_scopes(
            audit_at="2026-09-07T00:00:00Z",
            system_id="account_service",
            category="USER_PROFILE",
        )
        self.assertTrue(scopes)
        latest_scope = scopes[-1]
        records = self.bundle.store.query(
            audit_at="2026-09-07T00:00:00Z",
            capture_id=latest_scope.capture_id,
            system_id="account_service",
            category="USER_PROFILE",
        )
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
