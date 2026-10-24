from __future__ import annotations

import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(CODE))

from pramaantrace.baseline import assess_case  # noqa: E402
from pramaantrace.identity import IdentityResolver  # noqa: E402
from pramaantrace.rules import RuleEngine  # noqa: E402
from pramaantrace.store import NormalizedRecord, RecordScope, RecordStore  # noqa: E402


AUDIT_AT = "2026-10-01T00:00:00Z"
OLD_EMAIL = "previous@example.invalid"
CURRENT_EMAIL = "current@example.invalid"
USER_ID = "subject-token"

RULES = RuleEngine(
    [
        {
            "rule_id": "fixture-delete-profile",
            "data_category": "USER_PROFILE",
            "condition": "Always",
            "required_action": "DELETE",
        },
        {
            "rule_id": "fixture-retain-hold",
            "data_category": "LEGAL_HOLD_RECORD",
            "condition": "Active hold",
            "required_action": "RETAIN",
        },
    ]
)


def assess(
    store: RecordStore,
    *,
    email: str = CURRENT_EMAIL,
    audit_log: list[dict[str, str]] | None = None,
) -> dict:
    identities = [
        {
            "user_id": USER_ID,
            "name": "Synthetic Person",
            "email": CURRENT_EMAIL,
            "email_hash": "",
            "phone": "",
            "customer_reference": "",
            "updated_at": "2026-09-01T00:00:00Z",
        }
    ]
    request = {
        "case_id": "custom-fixture",
        "email": email,
        "requested_at": "2026-08-01T00:00:00Z",
        "reported_status": "NOT_STARTED",
        "reported_at": "2026-08-02T00:00:00Z",
        "audit_at": AUDIT_AT,
        "request_text": "Please erase my account and personal information.",
    }
    return assess_case(
        request,
        store=store,
        identity_resolver=IdentityResolver(identities, audit_log or []),
        rule_engine=RULES,
        activities=(),
    )


class ParticipantCreatedCaseTests(unittest.TestCase):
    def test_incomplete_plan_verifies_already_compliant_retained_records(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="profile-capture",
                captured_at="2026-09-15T00:00:00Z",
                topology="primary",
                system_id="account_service",
                resource_id="profile-fixture",
                category="USER_PROFILE",
                identifiers={"emails": (CURRENT_EMAIL,), "user_ids": (USER_ID,)},
                attributes={"email": CURRENT_EMAIL, "user_id": USER_ID},
            )
        )
        store.add_record(
            NormalizedRecord(
                capture_id="hold-capture",
                captured_at="2026-09-15T00:00:00Z",
                topology="primary",
                system_id="legal_service",
                resource_id="hold-fixture",
                category="LEGAL_HOLD_RECORD",
                identifiers={"emails": (CURRENT_EMAIL,), "user_ids": (USER_ID,)},
                attributes={
                    "email": CURRENT_EMAIL,
                    "user_id": USER_ID,
                    "legal_hold": True,
                },
            )
        )

        result = assess(store)
        verification_steps = [
            step for step in result["steps"] if step["phase"] == "VERIFICATION"
        ]

        self.assertEqual(result["deletion_status"], "INCOMPLETE")
        self.assertIn(
            ("VERIFY_RECORD_PRESENT", "PRESENT"),
            {(step["operation"], step["state"]) for step in verification_steps},
        )
        self.assertTrue(verification_steps)
        self.assertTrue(all(step["evidence_id"] == "" for step in verification_steps))

    def test_historical_request_email_finds_current_subject_record(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="fixture-capture",
                captured_at="2026-09-15T00:00:00Z",
                topology="fixture-primary",
                system_id="account_service",
                resource_id="profile-fixture",
                category="USER_PROFILE",
                identifiers={"emails": (OLD_EMAIL,), "user_ids": (USER_ID,)},
                attributes={"email": OLD_EMAIL, "user_id": USER_ID},
            )
        )
        history = [
            {
                "audit_id": "fixture-audit",
                "user_id": USER_ID,
                "event_time": "2026-08-20T00:00:00Z",
                "field_name": "email",
                "old_value": OLD_EMAIL,
                "new_value": CURRENT_EMAIL,
            }
        ]

        result = assess(store, email=OLD_EMAIL, audit_log=history)

        self.assertEqual(result["deletion_status"], "INCOMPLETE")
        self.assertEqual(result["steps"][0]["operation"], "REPORT_REMAINING_RECORD")
        self.assertEqual(result["steps"][0]["resource_id"], "profile-fixture")

    def test_active_legal_hold_record_is_verified_as_retained(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="fixture-capture",
                captured_at="2026-09-15T00:00:00Z",
                topology="fixture-primary",
                system_id="legal_service",
                resource_id="hold-fixture",
                category="LEGAL_HOLD_RECORD",
                identifiers={"emails": (CURRENT_EMAIL,), "user_ids": (USER_ID,)},
                attributes={
                    "email": CURRENT_EMAIL,
                    "user_id": USER_ID,
                    "legal_hold": True,
                },
            )
        )

        result = assess(store)

        self.assertEqual(result["deletion_status"], "COMPLETE")
        self.assertEqual(
            [step["operation"] for step in result["steps"]],
            ["VERIFY_RECORD_PRESENT"],
        )

    def test_absent_primary_with_present_replica_is_incomplete(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="replica-capture",
                captured_at="2026-09-20T00:00:00Z",
                topology="read_replica",
                system_id="account_service",
                resource_id="profile-fixture",
                category="USER_PROFILE",
                identifiers={"emails": (CURRENT_EMAIL,), "user_ids": (USER_ID,)},
                attributes={"email": CURRENT_EMAIL, "user_id": USER_ID},
            )
        )
        store.add_scope(
            RecordScope(
                capture_id="primary-listing",
                captured_at="2026-09-21T00:00:00Z",
                topology="primary",
                system_id="account_service",
                category="USER_PROFILE",
                complete_listing=True,
            )
        )

        result = assess(store)

        self.assertEqual(result["deletion_status"], "INCOMPLETE")
        self.assertEqual(result["steps"][0]["operation"], "REPORT_REMAINING_RECORD")
        self.assertEqual(result["steps"][0]["evidence_id"], "replica-capture")


if __name__ == "__main__":
    unittest.main()
