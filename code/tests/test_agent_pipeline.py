from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

import pytest

CODE = Path(__file__).resolve().parents[1]
ROOT = CODE.parent
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.baseline import run_baseline  # noqa: E402
from pramaantrace.agent.loop import CandidateLink, InvestigationResult  # noqa: E402
from pramaantrace.loader import DatasetBundle  # noqa: E402
from pramaantrace.store import NormalizedRecord, RecordStore  # noqa: E402
from pramaantrace.validator import validate_rows  # noqa: E402

AUDIT_AT = "2026-09-15T12:00:00Z"
EMAIL = "subject@example.test"


class _BrokenInvestigator:
    class _Usage:
        @staticmethod
        def summary() -> dict[str, Any]:
            return {"network_calls": 0, "cache_hits": 0}

    client = type("Client", (), {"usage_ledger": _Usage()})()

    def investigate(self, request: dict[str, str], toolbox: Any) -> Any:
        raise RuntimeError("simulated agent loop failure")


class _StructuredLinkInvestigator:
    client = _BrokenInvestigator.client

    def investigate(self, request: dict[str, str], toolbox: Any) -> InvestigationResult:
        source = toolbox.observe("search_records", {"identifier": EMAIL})
        target = toolbox.observe(
            "compare_replicas", {"resource_id": "analytics_profile_89"}
        )
        candidate = CandidateLink(
            "analytics_profile_89", "evidence_analytics", target.observation_id
        )
        return InvestigationResult(
            candidates=(candidate,), observations=(source, target), turns=2
        )


def _bundle(*, with_structured_target: bool = False) -> DatasetBundle:
    store = RecordStore()
    store.add_record(
        NormalizedRecord(
            capture_id="evidence_profile",
            captured_at="2026-09-15T11:59:00Z",
            topology="primary",
            system_id="account_service",
            resource_id="account_profile_88",
            category="USER_PROFILE",
            identifiers={"emails": (EMAIL,), "user_ids": ("user_subject",)},
            attributes={
                "email": EMAIL,
                "user_id": "user_subject",
                **(
                    {"analytics_resource": "analytics_profile_89"}
                    if with_structured_target
                    else {}
                ),
            },
        )
    )
    if with_structured_target:
        store.add_record(
            NormalizedRecord(
                capture_id="evidence_analytics",
                captured_at="2026-09-15T11:59:30Z",
                topology="primary",
                system_id="analytics_platform",
                resource_id="analytics_profile_89",
                category="ANALYTICS_PROFILE",
                attributes={"email": EMAIL},
            )
        )
    request = {
        "case_id": "fixture_case",
        "email": EMAIL,
        "requested_at": "2026-09-15T11:00:00Z",
        "reported_status": "COMPLETE",
        "reported_at": "2026-09-15T11:30:00Z",
        "audit_at": AUDIT_AT,
        "request_text": "Please delete my account and data.",
    }
    return DatasetBundle(
        root=ROOT,
        store=store,
        tables={
            "deletion_requests.csv": [request],
            "deletion_rules.csv": [
                {
                    "rule_id": "rule-profile",
                    "data_category": "USER_PROFILE",
                    "condition": "Always",
                    "required_action": "DELETE",
                },
                {
                    "rule_id": "rule-analytics",
                    "data_category": "ANALYTICS_PROFILE",
                    "condition": "Always",
                    "required_action": "ANONYMIZE",
                },
            ],
            "evidence_files.csv": [
                {
                    "file_id": "evidence_profile",
                    "file_path": "evidence/records/profile.json",
                    "origin": "account_service",
                    "captured_at": "2026-09-15T11:59:00Z",
                }
                ,*([
                    {
                        "file_id": "evidence_analytics",
                        "file_path": "evidence/records/analytics.json",
                        "origin": "analytics_platform",
                        "captured_at": "2026-09-15T11:59:30Z",
                    }
                ] if with_structured_target else [])
            ],
            "system_activity.csv": [],
            "user_identities.csv": [
                {
                    "user_id": "user_subject",
                    "name": "Subject",
                    "email": EMAIL,
                    "email_hash": "",
                    "phone": "",
                    "customer_reference": "",
                    "updated_at": "2026-09-15T10:00:00Z",
                }
            ],
            "user_audit_log.csv": [],
        },
    )


def test_agent_error_falls_back_to_exact_baseline_case_and_validates() -> None:
    module = __import__("pramaantrace.agent.pipeline", fromlist=["run_agent_pipeline"])
    bundle = _bundle()
    expected = run_baseline(bundle)

    result = module.run_agent_pipeline(bundle, _BrokenInvestigator())

    assert result.rows == expected
    assert result.attempted_cases == 1
    assert result.completed_cases == 0
    assert result.fallback_cases == 1
    assert result.accepted_candidates == 0
    assert result.rejected_candidates == 0
    validate_rows(
        bundle.tables["deletion_requests.csv"],
        result.rows,
        manifest=bundle.tables["evidence_files.csv"],
        activities=bundle.tables["system_activity.csv"],
        audit_rows=bundle.tables["user_audit_log.csv"],
    )


def test_verified_structured_link_reassesses_through_deterministic_policy() -> None:
    module = __import__("pramaantrace.agent.pipeline", fromlist=["run_agent_pipeline"])
    bundle = _bundle(with_structured_target=True)
    baseline = run_baseline(bundle)

    result = module.run_agent_pipeline(bundle, _StructuredLinkInvestigator())

    assert baseline[0]["deletion_status"] == "INCOMPLETE"
    assert not any(
        step["resource_id"] == "analytics_profile_89" for step in baseline[0]["steps"]
    )
    assert result.accepted_candidates == 1
    assert result.rejected_candidates == 0
    assert any(
        step["resource_id"] == "analytics_profile_89"
        and step["operation"] == "REPORT_EXPOSED_PII"
        for step in result.rows[0]["steps"]
    )
    validate_rows(
        bundle.tables["deletion_requests.csv"],
        result.rows,
        manifest=bundle.tables["evidence_files.csv"],
        activities=bundle.tables["system_activity.csv"],
        audit_rows=bundle.tables["user_audit_log.csv"],
    )


def test_non_deletion_request_skips_investigator() -> None:
    module = __import__("pramaantrace.agent.pipeline", fromlist=["run_agent_pipeline"])
    bundle = _bundle()
    bundle.tables["deletion_requests.csv"][0]["request_text"] = "Please export my data."

    result = module.run_agent_pipeline(bundle, _BrokenInvestigator())

    assert result.rows[0]["deletion_status"] == "NOT_APPLICABLE"
    assert result.rows[0]["steps"] == []
    assert result.attempted_cases == 0
    assert result.fallback_cases == 0
