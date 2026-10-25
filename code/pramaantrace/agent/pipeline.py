"""Per-case investigator orchestration with deterministic fallback authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..baseline import assess_case, run_baseline
from ..identity import IdentityResolver
from ..intent import authorizes_deletion
from ..loader import DatasetBundle
from ..rules import RuleEngine
from .tools import CaseToolbox
from .verifier import verify_candidate_links


@dataclass(frozen=True)
class AgentRunResult:
    rows: list[dict[str, Any]]
    attempted_cases: int
    completed_cases: int
    fallback_cases: int
    accepted_candidates: int
    rejected_candidates: int
    usage_summary: dict[str, Any]


def _usage_summary(investigator: Any) -> dict[str, Any]:
    ledger = getattr(getattr(investigator, "client", None), "usage_ledger", None)
    summary = getattr(ledger, "summary", None)
    if not callable(summary):
        return {}
    try:
        value = summary()
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def run_agent_pipeline(
    bundle: DatasetBundle,
    investigator: Any,
) -> AgentRunResult:
    """Run baseline first, then apply only replay-verified resource candidates."""
    requests = sorted(
        bundle.tables["deletion_requests.csv"],
        key=lambda row: row["case_id"],
    )
    baseline_rows = run_baseline(bundle)
    rows_by_case = {row["case_id"]: row for row in baseline_rows}
    identity_resolver = IdentityResolver(
        bundle.tables["user_identities.csv"],
        bundle.tables["user_audit_log.csv"],
    )
    rule_engine = RuleEngine(bundle.tables["deletion_rules.csv"])
    activities = bundle.tables["system_activity.csv"]

    attempted = 0
    completed = 0
    fallbacks = 0
    accepted_count = 0
    rejected_count = 0

    for request in requests:
        if not authorizes_deletion(request["request_text"]):
            continue
        attempted += 1
        identities = identity_resolver.resolve_email(
            request["email"],
            request["audit_at"],
        )
        if len(identities) != 1:
            fallbacks += 1
            continue

        identity = identity_resolver.enrich_customer_references(
            identities[0],
            audit_at=request["audit_at"],
            store=bundle.store,
        )
        toolbox = CaseToolbox(
            request=request,
            identity=identity,
            store=bundle.store,
            activities=activities,
            rule_engine=rule_engine,
            manifest=bundle.tables["evidence_files.csv"],
        )
        try:
            investigation = investigator.investigate(request, toolbox)
            candidate_keys: set[tuple[str, str, str]] = set()
            for candidate in investigation.candidates:
                verified_keys = verify_candidate_links(
                    request,
                    identity,
                    (candidate,),
                    investigation.observations,
                    toolbox,
                    bundle.store,
                )
                if verified_keys:
                    accepted_count += 1
                    candidate_keys.update(verified_keys)
                else:
                    rejected_count += 1

            if candidate_keys:
                rows_by_case[request["case_id"]] = assess_case(
                    request,
                    store=bundle.store,
                    identity_resolver=identity_resolver,
                    rule_engine=rule_engine,
                    activities=activities,
                    additional_resource_keys=tuple(sorted(candidate_keys)),
                )
            completed += 1
        except Exception:
            # The investigator is advisory. Preserve the whole baseline row if
            # its loop, observation replay, or deterministic reassessment fails.
            fallbacks += 1

    return AgentRunResult(
        rows=[rows_by_case[row["case_id"]] for row in requests],
        attempted_cases=attempted,
        completed_cases=completed,
        fallback_cases=fallbacks,
        accepted_candidates=accepted_count,
        rejected_candidates=rejected_count,
        usage_summary=_usage_summary(investigator),
    )
