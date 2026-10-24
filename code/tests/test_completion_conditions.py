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
SUBJECT_EMAIL = "subject@example.invalid"
IDENTITY_ROWS = [
    {
        "user_id": "subject-token",
        "name": "Synthetic Subject",
        "email": SUBJECT_EMAIL,
        "email_hash": "",
        "phone": "",
        "customer_reference": "",
        "updated_at": "2026-01-01T00:00:00Z",
    }
]
EMPTY_AUDIT_LOG: list[dict[str, str]] = []
RETENTION_RULES = [
    {
        "rule_id": "fixture-retained",
        "data_category": "LEGAL_HOLD_RECORD",
        "condition": "Keep while a hold is active",
        "required_action": "RETAIN",
    },
    {
        "rule_id": "fixture-tombstone",
        "data_category": "ACCOUNT_TOMBSTONE",
        "condition": "Keep only the stable internal subject reference",
        "required_action": "REDACT",
    },
]


def request_row() -> dict[str, str]:
    return {
        "case_id": "synthetic-case",
        "email": SUBJECT_EMAIL,
        "requested_at": "2026-01-01T00:00:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-01-02T00:00:00Z",
        "audit_at": AUDIT_AT,
        "request_text": "Please delete my account and personal data.",
    }


def assess(store: RecordStore) -> dict:
    return assess_case(
        request_row(),
        store=store,
        identity_resolver=IdentityResolver(IDENTITY_ROWS, EMPTY_AUDIT_LOG),
        rule_engine=RuleEngine(RETENTION_RULES),
        activities=(),
    )


class CompletionConditionTests(unittest.TestCase):
    def test_retained_tombstone_with_prohibited_identifiers_is_incomplete(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="fixture-capture",
                captured_at="2026-09-01T00:00:00Z",
                topology="fixture-topology",
                system_id="identity_service",
                resource_id="tombstone-fixture",
                category="ACCOUNT_TOMBSTONE",
                identifiers={"user_ids": ("subject-token",)},
                attributes={
                    "resource_id": "tombstone-fixture",
                    "user_id": "subject-token",
                    "email": SUBJECT_EMAIL,
                    "name": "Synthetic Subject",
                },
            )
        )

        result = assess(store)

        self.assertEqual(result["deletion_status"], "INCOMPLETE")
        self.assertEqual(
            [step["operation"] for step in result["steps"]],
            ["REPORT_EXPOSED_PII", "REDACT_RECORD", "VERIFY_RECORD_REDACTED"],
        )

    def test_missing_required_retained_record_is_incomplete_without_new_operation(self) -> None:
        store = RecordStore()
        store.add_record(
            NormalizedRecord(
                capture_id="prior-capture",
                captured_at="2026-08-01T00:00:00Z",
                topology="fixture-topology",
                system_id="legal_service",
                resource_id="retained-fixture",
                category="LEGAL_HOLD_RECORD",
                identifiers={"user_ids": ("subject-token",)},
                attributes={
                    "resource_id": "retained-fixture",
                    "user_id": "subject-token",
                    "legal_hold": True,
                },
            )
        )
        store.add_scope(
            RecordScope(
                capture_id="later-listing",
                captured_at="2026-09-01T00:00:00Z",
                topology="fixture-topology",
                system_id="legal_service",
                category="LEGAL_HOLD_RECORD",
                complete_listing=True,
            )
        )

        result = assess(store)

        self.assertEqual(result["deletion_status"], "INCOMPLETE")
        # No allowed finding/remediation operation describes restoring a
        # required retained record. Do not fabricate one.
        self.assertEqual(result["steps"], [])


if __name__ == "__main__":
    unittest.main()
