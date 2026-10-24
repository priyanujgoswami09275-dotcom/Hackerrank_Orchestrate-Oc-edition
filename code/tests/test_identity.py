from __future__ import annotations

import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from pramaantrace.identity import IdentityResolver  # noqa: E402
from pramaantrace.loader import read_csv_rows  # noqa: E402
from pramaantrace.store import NormalizedRecord, RecordStore  # noqa: E402


class IdentityResolverTests(unittest.TestCase):
    def test_null_customer_reference_is_not_a_subject_identifier(self) -> None:
        resolver = IdentityResolver(
            [
                {
                    "user_id": "fixture_user",
                    "name": "Fixture Name",
                    "email": "fixture@example.test",
                    "phone": "",
                    "email_hash": "",
                    "customer_reference": "null",
                    "updated_at": "2026-05-01T00:00:00Z",
                }
            ],
            [],
        )
        identity = resolver.identifiers_for(
            "fixture_user", "2026-05-02T00:00:00Z"
        )
        self.assertIsNotNone(identity)
        self.assertEqual(identity.customer_references, ())

    def test_future_snapshot_and_audit_events_do_not_leak_backward(self) -> None:
        resolver = IdentityResolver(
            [
                {
                    "user_id": "fixture_user",
                    "name": "Fixture Name",
                    "email": "new@example.test",
                    "phone": "+1 202 555 0100",
                    "email_hash": "",
                    "updated_at": "2026-06-01T00:00:00Z",
                }
            ],
            [
                {
                    "audit_id": "fixture_email_change",
                    "user_id": "fixture_user",
                    "event_time": "2026-05-01T00:00:00Z",
                    "field_name": "email",
                    "old_value": "old@example.test",
                    "new_value": "new@example.test",
                },
                {
                    "audit_id": "fixture_phone_change",
                    "user_id": "fixture_user",
                    "event_time": "2026-05-01T00:00:00Z",
                    "field_name": "phone",
                    "old_value": "+1 202 555 0101",
                    "new_value": "+1 202 555 0100",
                },
            ],
        )
        before_change = resolver.identifiers_for(
            "fixture_user", "2026-04-01T00:00:00Z"
        )
        after_change = resolver.identifiers_for(
            "fixture_user", "2026-05-15T00:00:00Z"
        )
        self.assertIsNotNone(before_change)
        self.assertIsNotNone(after_change)
        self.assertEqual(before_change.emails, ())
        self.assertNotIn("new@example.test", before_change.emails)
        self.assertIn("new@example.test", after_change.emails)
        self.assertIn("old@example.test", after_change.emails)
        self.assertEqual(before_change.phones, ())
        self.assertNotIn("12025550100", before_change.phones)

    def test_replays_changes_after_older_snapshot_only_through_cutoff(self) -> None:
        resolver = IdentityResolver(
            [
                {
                    "user_id": "fixture_user",
                    "name": "Fixture Name",
                    "email": "new@example.test",
                    "phone": "",
                    "email_hash": "",
                    "updated_at": "2026-04-01T00:00:00Z",
                }
            ],
            [
                {
                    "audit_id": "fixture_email_change",
                    "user_id": "fixture_user",
                    "event_time": "2026-05-01T00:00:00Z",
                    "field_name": "email",
                    "old_value": "old@example.test",
                    "new_value": "new@example.test",
                }
            ],
        )
        as_of = resolver.identifiers_for("fixture_user", "2026-05-15T00:00:00Z")
        self.assertIn("new@example.test", as_of.emails)
        self.assertIn("old@example.test", as_of.emails)
        self.assertEqual(
            [item.user_id for item in resolver.resolve_email(
                "old@example.test", "2026-05-15T00:00:00Z"
            )],
            ["fixture_user"],
        )

    def test_sha256_snapshot_hash_matches_for_all_users(self) -> None:
        identities = read_csv_rows(ROOT / "dataset" / "user_identities.csv")
        events = read_csv_rows(ROOT / "dataset" / "user_audit_log.csv")
        resolver = IdentityResolver(identities, events)
        self.assertEqual(resolver.current_hash_match_count(), (850, 850))

    def test_customer_reference_join_uses_only_cutoff_visible_evidence(self) -> None:
        resolver = IdentityResolver(
            [
                {
                    "user_id": "fixture_user",
                    "name": "Fixture Name",
                    "email": "fixture@example.test",
                    "phone": "",
                    "email_hash": "",
                    "updated_at": "2026-05-01T00:00:00Z",
                }
            ],
            [],
        )
        identity = resolver.identifiers_for(
            "fixture_user", "2026-05-02T00:00:00Z"
        )
        store = RecordStore()
        for capture_id, captured_at, reference in (
            ("fixture-visible", "2026-05-01T12:00:00Z", "customer_visible"),
            ("fixture-future", "2026-05-03T12:00:00Z", "customer_future"),
        ):
            store.add_record(
                NormalizedRecord(
                    capture_id=capture_id,
                    captured_at=captured_at,
                    topology="fixture",
                    system_id="fixture_service",
                    resource_id=f"record_{capture_id}",
                    category="FIXTURE",
                    identifiers={
                        "emails": ("fixture@example.test",),
                        "customer_references": (reference,),
                    },
                )
            )
        enriched = resolver.enrich_customer_references(
            identity,
            audit_at="2026-05-02T00:00:00Z",
            store=store,
        )
        self.assertEqual(enriched.customer_references, ("customer_visible",))

    def test_all_evaluation_request_emails_resolve_at_their_audit_cutoff(self) -> None:
        requests = read_csv_rows(ROOT / "dataset" / "deletion_requests.csv")
        identities = read_csv_rows(ROOT / "dataset" / "user_identities.csv")
        events = read_csv_rows(ROOT / "dataset" / "user_audit_log.csv")
        resolver = IdentityResolver(identities, events)
        unresolved = [
            row["case_id"]
            for row in requests
            if not resolver.resolve_email(row["email"], row["audit_at"])
        ]
        self.assertEqual(unresolved, [])


if __name__ == "__main__":
    unittest.main()
