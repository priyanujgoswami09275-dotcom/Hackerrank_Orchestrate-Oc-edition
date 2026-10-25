from __future__ import annotations

import sys
import unittest
from pathlib import Path

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
sys.path.insert(0, str(CODE))

from pramaantrace.baseline import _activity_linked_resources, run_baseline  # noqa: E402
from pramaantrace.identity import ResolvedIdentity  # noqa: E402
from pramaantrace.intent import authorizes_deletion  # noqa: E402
from pramaantrace.loader import load_dataset, read_csv_rows  # noqa: E402
from pramaantrace.validator import validate_rows  # noqa: E402


class IntentTests(unittest.TestCase):
    def test_affirmative_deletion_requests_authorize(self) -> None:
        self.assertTrue(authorizes_deletion("Please delete my account and data."))
        self.assertTrue(authorizes_deletion("Por favor, elimina mis datos personales."))
        self.assertTrue(
            authorizes_deletion(
                "Solicito a exclusão permanente da conta associada a este e-mail."
            )
        )

    def test_non_deletion_and_withdrawn_requests_do_not_authorize(self) -> None:
        self.assertFalse(authorizes_deletion("Please export a copy of my data."))
        self.assertFalse(authorizes_deletion("Do not delete my account; keep it active."))
        self.assertFalse(
            authorizes_deletion(
                "I need help resetting the login. Do not close the account."
            )
        )
        self.assertFalse(authorizes_deletion("Não quero a exclusão da minha conta."))

    def test_negated_information_request_does_not_authorize(self) -> None:
        self.assertFalse(
            authorizes_deletion(
                "Can you tell me what personal information you hold about me? "
                "This is an information request, not a request to erase it."
            )
        )

    def test_positive_erasure_wording_still_authorizes(self) -> None:
        self.assertTrue(authorizes_deletion("Please erase my account and data."))
        self.assertTrue(
            authorizes_deletion("Delete my account and every record linked to it.")
        )
        self.assertTrue(
            authorizes_deletion(
                "I don't want you keeping my data, please erase it."
            )
        )

    def test_public_sample_intent_matches_expected_authorization(self) -> None:
        requests = read_csv_rows(ROOT / "dataset" / "sample_deletion_requests.csv")
        expected = {
            row["case_id"]: row["deletion_status"]
            for row in read_csv_rows(ROOT / "dataset" / "sample_output.csv")
        }
        for request in requests:
            with self.subTest(case_id=request["case_id"]):
                self.assertEqual(
                    authorizes_deletion(request["request_text"]),
                    expected[request["case_id"]] != "NOT_APPLICABLE",
                )

    def test_activity_identity_match_respects_token_boundaries(self) -> None:
        identity = ResolvedIdentity(
            user_id="user_01",
            names=(),
            emails=(),
            email_hashes=(),
            phones=(),
            customer_references=(),
        )
        events = [
            {
                "event_time": "2026-06-01T00:00:00Z",
                "details": "connector contains subject user_010",
                "resource_id": "flow_unrelated",
            }
        ]
        self.assertEqual(
            _activity_linked_resources(
                identity, events, "2026-06-02T00:00:00Z"
            ),
            set(),
        )


class BaselineDatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundle = load_dataset(ROOT)
        cls.rows = run_baseline(cls.bundle)

    def test_baseline_covers_and_validates_every_request(self) -> None:
        requests = self.bundle.tables["deletion_requests.csv"]
        self.assertEqual(len(self.rows), len(requests))
        self.assertEqual(
            [row["case_id"] for row in self.rows],
            sorted(row["case_id"] for row in requests),
        )
        validate_rows(
            requests,
            self.rows,
            manifest=self.bundle.tables["evidence_files.csv"],
            activities=self.bundle.tables["system_activity.csv"],
            audit_rows=self.bundle.tables["user_audit_log.csv"],
        )

    def test_non_applicable_cases_have_no_steps(self) -> None:
        for row in self.rows:
            if row["deletion_status"] == "NOT_APPLICABLE":
                self.assertEqual(row["steps"], [])


if __name__ == "__main__":
    unittest.main()
