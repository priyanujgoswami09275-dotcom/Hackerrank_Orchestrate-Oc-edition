"""Deterministic evidence assessor and remediation planner."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .identity import IdentityResolver, ResolvedIdentity
from .intent import authorizes_deletion
from .linkage import referenced_resource_ids
from .loader import (
    DatasetBundle,
    enrich_enabled,
    system_from_resource,
)
from .planner import build_steps
from .rules import RuleEngine
from .store import NormalizedRecord, RecordScope, RecordStore, parse_timestamp


FINDING_FOR_ACTION = {
    "DELETE": ("REPORT_REMAINING_RECORD", "PRESENT"),
    "REDACT": ("REPORT_EXPOSED_PII", "PRESENT"),
    "ANONYMIZE": ("REPORT_EXPOSED_PII", "PRESENT"),
}
REMEDIATION_FOR_ACTION = {
    "DELETE": ("DELETE_RECORD", "ABSENT"),
    "REDACT": ("REDACT_RECORD", "REDACTED"),
    "ANONYMIZE": ("ANONYMIZE_RECORD", "ANONYMIZED"),
}
VERIFICATION_FOR_ACTION = {
    "DELETE": ("VERIFY_RECORD_ABSENT", "ABSENT"),
    "REDACT": ("VERIFY_RECORD_REDACTED", "REDACTED"),
    "ANONYMIZE": ("VERIFY_RECORD_ANONYMIZED", "ANONYMIZED"),
    "RETAIN": ("VERIFY_RECORD_PRESENT", "PRESENT"),
}

# Canonical attribute names each identifier bucket maps onto for the policy
# checks that read attribute fields.
IDENTIFIER_ATTRIBUTES = {
    "emails": "email",
    "email_hashes": "email_hash",
    "phones": "phone",
    "user_ids": "user_id",
    "customer_references": "customer_reference",
    "names": "full_name",
}


@dataclass(frozen=True)
class CurrentState:
    state: str
    evidence_id: str
    record: NormalizedRecord | None


def _identity_values(identity: ResolvedIdentity) -> set[str]:
    return {
        value
        for value in (
            identity.user_id,
            *identity.emails,
            *identity.email_hashes,
            *identity.phones,
            *identity.customer_references,
        )
        if value
    }


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().casefold() in {"1", "true", "yes", "enabled", "active", "allowed"}


CLAIM_EVENT_ACTIONS = {
    "DELETE_RECORD": "DELETE",
    "REDACT_RECORD": "REDACT",
    "ANONYMIZE_RECORD": "ANONYMIZE",
}


def _referenced_resources(matched_records: Iterable[NormalizedRecord]) -> set[str]:
    """Resource ids that subject-linked evidence records name in their
    attributes (e.g. an index document naming its source account). These are
    the subject's other resources the evidence itself ties to this person."""
    referenced: set[str] = set()
    for record in matched_records:
        referenced.update(
            referenced_resource_ids(
                record.attributes,
                own_resource_id=record.resource_id,
            )
        )
    return referenced


def _wave_derived_account_ids(
    store: RecordStore,
    activities: Iterable[Mapping[str, str]],
    *,
    anchored_ids: set[str],
    requested_at: str,
    audit_at: str,
) -> list[str]:
    """Derive the subject's primary account id from the deletion worker's
    own in-window wave.

    The subject's known resources were queued for the same operation; where
    the activity stream places exactly one deleted account row inside a
    short neighbourhood of those known resources' own claim rows, that row
    is the operation's account. Anything else stays unreported instead of
    guessing among ambiguous candidates."""
    requested = parse_timestamp(requested_at)
    cutoff = parse_timestamp(audit_at)
    claim_types = {"DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD"}
    anchor_times = [
        parse_timestamp(event["event_time"])
        for event in activities
        if event.get("resource_id") in anchored_ids
        and event.get("event_type") in claim_types
        and requested <= parse_timestamp(event["event_time"]) <= cutoff
    ]
    if not anchor_times:
        return []
    candidates: set[str] = set()
    for event in activities:
        if event.get("event_type") != "DELETE_RECORD":
            continue
        resource_id = event.get("resource_id", "")
        if not resource_id.startswith("account_") and not resource_id.startswith(
            "account-"
        ):
            continue
        event_time = parse_timestamp(event["event_time"])
        if event_time < requested or event_time > cutoff:
            continue
        if any(abs((event_time - anchor).total_seconds()) <= 420 for anchor in anchor_times):
            candidates.add(resource_id)
    if len(candidates) != 1:
        return []
    derived = next(iter(candidates))
    # Never re-report resources the evidence already treats subject-linked,
    # and never derive an account that itself carries store records.
    if not derived.casefold().startswith("account_"):
        return []
    if store.query(audit_at=audit_at, resource_id=derived):
        return []
    return [derived]


def _claim_action(
    activities: Iterable[Mapping[str, str]],
    resource_id: str,
    requested_at: str,
    audit_at: str,
) -> str | None:
    """Policy action the deletion workflow claimed for a resource within the
    request window. The latest claim inside the window wins."""
    requested = parse_timestamp(requested_at)
    cutoff = parse_timestamp(audit_at)
    best: Mapping[str, str] | None = None
    best_time = None
    for event in activities:
        if event.get("resource_id") != resource_id:
            continue
        action = CLAIM_EVENT_ACTIONS.get(event.get("event_type", ""))
        if action is None:
            continue
        event_time = parse_timestamp(event["event_time"])
        if event_time < requested or event_time > cutoff:
            continue
        if best_time is None or event_time >= best_time:
            best = event
            best_time = event_time
    if best is None:
        return None
    return CLAIM_EVENT_ACTIONS.get(str(best.get("event_type", "")))


def _explicit_absence(record: NormalizedRecord) -> bool:
    attributes = record.attributes
    status_code = attributes.get("status_code")
    try:
        if int(status_code) == 404:
            return True
    except (TypeError, ValueError):
        pass
    event = str(attributes.get("event", "")).casefold()
    http_status = attributes.get("http_status")
    rows = attributes.get("rows")
    try:
        if int(http_status) == 404 and int(rows) == 0:
            return True
    except (TypeError, ValueError):
        pass
    if "lookup_completed" in event:
        try:
            return int(rows) == 0
        except (TypeError, ValueError):
            return False
    return False


def _record_capture_state(record: NormalizedRecord) -> str:
    return "ABSENT" if _explicit_absence(record) else "PRESENT"


def _latest_current_state(
    store: RecordStore,
    *,
    audit_at: str,
    system_id: str,
    resource_id: str,
    category: str,
) -> CurrentState:
    records = store.query(
        audit_at=audit_at,
        system_id=system_id,
        resource_id=resource_id,
        category=category,
    )
    by_topology: dict[str, list[NormalizedRecord]] = defaultdict(list)
    for record in records:
        by_topology[record.topology].append(record)

    scopes = store.query_scopes(
        audit_at=audit_at,
        system_id=system_id,
        category=category,
        complete_listing=True,
    )
    scopes_by_topology: dict[str, list[RecordScope]] = defaultdict(list)
    for scope in scopes:
        scopes_by_topology[scope.topology].append(scope)

    states: list[tuple[str, str, NormalizedRecord | None, str]] = []
    for topology in sorted(set(by_topology) | set(scopes_by_topology)):
        topology_records = sorted(
            by_topology.get(topology, ()),
            key=lambda item: (
                parse_timestamp(item.captured_at),
                item.capture_id,
                item.resource_id,
                *(
                    (
                        int(item.attributes["line_no"]),
                    )
                    if enrich_enabled()
                    and isinstance(item.attributes.get("line_no"), (int, str))
                    and str(item.attributes.get("line_no", "")).isdigit()
                    else (0,)
                ),
            ),
        )
        topology_scopes = sorted(
            scopes_by_topology.get(topology, ()),
            key=lambda item: (
                parse_timestamp(item.captured_at),
                item.capture_id,
            ),
        )
        latest_record = topology_records[-1] if topology_records else None
        latest_scope = topology_scopes[-1] if topology_scopes else None

        if latest_scope and (
            latest_record is None
            or parse_timestamp(latest_scope.captured_at)
            >= parse_timestamp(latest_record.captured_at)
        ):
            present_in_scope = bool(
                latest_record
                and latest_record.capture_id == latest_scope.capture_id
            )
            if present_in_scope:
                states.append(
                    (
                        "PRESENT",
                        latest_record.capture_id,
                        latest_record,
                        topology,
                    )
                )
            else:
                states.append(
                    ("ABSENT", latest_scope.capture_id, None, topology)
                )
        elif latest_record:
            states.append(
                (
                    _record_capture_state(latest_record),
                    latest_record.capture_id,
                    latest_record,
                    topology,
                )
            )

    # A 404/readback and a complete snapshot are both state-bearing. Any
    # surviving topology with a present copy makes the logical resource present.
    present = [item for item in states if item[0] == "PRESENT"]
    if present:
        chosen = max(
            present,
            key=lambda item: (
                parse_timestamp(
                    item[2].captured_at
                    if item[2] is not None
                    else audit_at
                ),
                item[1],
            ),
        )
        return CurrentState("PRESENT", chosen[1], chosen[2])
    absent = [item for item in states if item[0] == "ABSENT"]
    if absent:
        chosen = max(
            absent,
            key=lambda item: (
                parse_timestamp(
                    item[2].captured_at
                    if item[2] is not None
                    else next(
                        (
                            scope.captured_at
                            for scope in scopes
                            if scope.capture_id == item[1]
                            and scope.topology == item[3]
                        ),
                        audit_at,
                    )
                ),
                item[1],
            ),
        )
        return CurrentState("ABSENT", chosen[1], chosen[2])
    return CurrentState("UNKNOWN", "", None)


def _activity_linked_resources(
    identity: ResolvedIdentity,
    activities: Iterable[Mapping[str, str]],
    audit_at: str,
) -> set[str]:
    values = {
        value.casefold()
        for value in (
            identity.user_id,
            *identity.emails,
            *identity.email_hashes,
        *identity.phones,
            *identity.customer_references,
        )
        if len(value) >= 4
    }
    linked = set()
    cutoff = parse_timestamp(audit_at)
    for event in activities:
        if parse_timestamp(event["event_time"]) > cutoff:
            continue
        details = event.get("details", "").casefold()
        if not any(
            re.search(
                rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])",
                details,
                flags=re.I,
            )
            for token in values
        ):
            continue
        if event.get("resource_id"):
            linked.add(event["resource_id"])
    return linked


def _resource_keys(
    identity: ResolvedIdentity,
    store: RecordStore,
    activities: Iterable[Mapping[str, str]],
    audit_at: str,
) -> set[tuple[str, str, str]]:
    values = _identity_values(identity)
    matched = store.query(audit_at=audit_at, identifier_values=values)
    keys = {
        (record.system_id, record.resource_id, record.category)
        for record in matched
    }
    for resource_id in _activity_linked_resources(identity, activities, audit_at):
        for record in store.query(audit_at=audit_at, resource_id=resource_id):
            keys.add((record.system_id, record.resource_id, record.category))
    return keys


def _candidate_records(
    store: RecordStore,
    *,
    audit_at: str,
    system_id: str,
    resource_id: str,
    category: str,
) -> list[NormalizedRecord]:
    return store.query(
        audit_at=audit_at,
        system_id=system_id,
        resource_id=resource_id,
        category=category,
    )


def assess_case(
    request: Mapping[str, str],
    *,
    store: RecordStore,
    identity_resolver: IdentityResolver,
    rule_engine: RuleEngine,
    activities: Iterable[Mapping[str, str]],
    additional_resource_keys: Iterable[tuple[str, str, str]] = (),
) -> dict[str, Any]:
    if not authorizes_deletion(request["request_text"]):
        return {
            "case_id": request["case_id"],
            "deletion_status": "NOT_APPLICABLE",
            "steps": [],
        }

    identities = identity_resolver.resolve_email(
        request["email"], request["audit_at"]
    )
    if len(identities) != 1:
        # The dataset currently resolves uniquely; this safe fallback avoids
        # guessing a subject or fabricating unsupported resource steps.
        return {
            "case_id": request["case_id"],
            "deletion_status": "INCOMPLETE",
            "steps": [],
        }
    identity = identity_resolver.enrich_customer_references(
        identities[0],
        audit_at=request["audit_at"],
        store=store,
    )
    identity_values = _identity_values(identity)
    activities = tuple(activities)
    keys = _resource_keys(identity, store, activities, request["audit_at"])
    for key in additional_resource_keys:
        if (
            isinstance(key, tuple)
            and len(key) == 3
            and all(isinstance(part, str) and part for part in key)
            and _candidate_records(
                store,
                audit_at=request["audit_at"],
                system_id=key[0],
                resource_id=key[1],
                category=key[2],
            )
        ):
            keys.add(key)

    findings: list[dict[str, str]] = []
    remediations: list[dict[str, str]] = []
    future_verifications: list[dict[str, str]] = []
    compliant_verifications: list[dict[str, str]] = []
    missing_required_retention = False

    crossref_verifications: list[dict[str, str]] = []
    if enrich_enabled():
        matched_records = store.query(
            audit_at=request["audit_at"],
            identifier_values=identity_values,
        )
        known_ids = {resource_id for _, resource_id, _ in keys}
        for resource_id in sorted(
            _referenced_resources(matched_records) - known_ids
        ):
            referenced_system = system_from_resource(resource_id)
            if referenced_system is None:
                continue
            if store.query(audit_at=request["audit_at"], resource_id=resource_id):
                continue
            # A referenced resource joins the closing checklist only, and only if
            # its recorded deletion belongs to this request window.
            if _claim_action(
                activities,
                resource_id,
                request["requested_at"],
                request["audit_at"],
            ) == "DELETE":
                crossref_verifications.append(
                    {
                        "system_id": referenced_system,
                        "resource_id": resource_id,
                        "operation": "VERIFY_RECORD_ABSENT",
                        "state": "ABSENT",
                        "evidence_id": "",
                    }
                )
        for account_id in _wave_derived_account_ids(
            store,
            activities,
            anchored_ids={record.resource_id for record in matched_records},
            requested_at=request["requested_at"],
            audit_at=request["audit_at"],
        ):
            crossref_verifications.append(
                {
                    "system_id": system_from_resource(account_id) or "account_service",
                    "resource_id": account_id,
                    "operation": "VERIFY_RECORD_ABSENT",
                    "state": "ABSENT",
                    "evidence_id": "",
                }
            )

    for system_id, resource_id, category in sorted(keys):
        records = _candidate_records(
            store,
            audit_at=request["audit_at"],
            system_id=system_id,
            resource_id=resource_id,
            category=category,
        )
        if not records:
            continue
        state = _latest_current_state(
            store,
            audit_at=request["audit_at"],
            system_id=system_id,
            resource_id=resource_id,
            category=category,
        )
        representative = state.record or max(
            records,
            key=lambda item: (
                parse_timestamp(item.captured_at),
                item.capture_id,
                item.topology,
            ),
        )
        attributes = representative.attributes
        if enrich_enabled() and representative.identifiers:
            # E1 linkage stores subject identifiers in the canonical
            # identifier map; the policy checks look at attribute fields.
            # Expose them under the canonical attribute names for checks only.
            merged = dict(attributes)
            for key, values in representative.identifiers.items():
                if key in IDENTIFIER_ATTRIBUTES and values:
                    merged.setdefault(IDENTIFIER_ATTRIBUTES[key], values[0])
            attributes = merged
        action = rule_engine.disposition(
            category,
            attributes,
            audit_at=request["audit_at"],
            identity_values=identity_values,
        )
        if enrich_enabled():
            claimed = _claim_action(
                activities,
                resource_id,
                request["requested_at"],
                request["audit_at"],
            )
            # The workflow's own claim inside the window states the intended
            # action; a claim followed by a still-identifiable record is a
            # failed claim, so the plan re-runs that same action.
            if claimed == "DELETE" and action in {"DELETE", "REDACT", "ANONYMIZE"}:
                action = "DELETE"

        if category == "DATA_FLOW":
            if state.state == "PRESENT" and _as_bool(
                attributes.get("enabled", False)
            ):
                findings.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "REPORT_ACTIVE_DATA_FLOW",
                        "state": "ACTIVE",
                        "evidence_id": state.evidence_id,
                    }
                )
                remediations.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "DISABLE_DATA_FLOW",
                        "state": "DISABLED",
                        "evidence_id": "",
                    }
                )
                future_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "VERIFY_DATA_FLOW_DISABLED",
                        "state": "DISABLED",
                        "evidence_id": "",
                    }
                )
            elif state.state == "PRESENT":
                compliant_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "VERIFY_DATA_FLOW_DISABLED",
                        "state": "DISABLED",
                        "evidence_id": state.evidence_id,
                    }
                )
            continue

        if category == "BACKUP_ARCHIVE":
            if state.state == "PRESENT" and _as_bool(
                attributes.get("restore_allowed", False)
            ):
                findings.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "REPORT_RESTORE_RISK",
                        "state": "ACTIVE",
                        "evidence_id": state.evidence_id,
                    }
                )
                remediations.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "BLOCK_RESTORE",
                        "state": "BLOCKED",
                        "evidence_id": "",
                    }
                )
                future_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "VERIFY_RESTORE_BLOCKED",
                        "state": "BLOCKED",
                        "evidence_id": "",
                    }
                )
            elif state.state == "PRESENT":
                compliant_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "VERIFY_RESTORE_BLOCKED",
                        "state": "BLOCKED",
                        "evidence_id": state.evidence_id,
                    }
                )
            continue

        if action is None:
            continue
        if state.state == "UNKNOWN":
            continue

        if action == "DELETE":
            if state.state == "PRESENT":
                finding_operation, finding_state = FINDING_FOR_ACTION[action]
                remediation_operation, remediation_state = REMEDIATION_FOR_ACTION[action]
                verify_operation, verify_state = VERIFICATION_FOR_ACTION[action]
                findings.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": finding_operation,
                        "state": finding_state,
                        "evidence_id": state.evidence_id,
                    }
                )
                remediations.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": remediation_operation,
                        "state": remediation_state,
                        "evidence_id": "",
                    }
                )
                future_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": verify_operation,
                        "state": verify_state,
                        "evidence_id": "",
                    }
                )
            else:
                # The evidence may already claim this record was deleted. Only
                # report the closing verification when that observed absence
                # is anchored to this request's own operation window; records
                # seen absent only in much older captures describe earlier
                # lifecycle operations, not this deletion's plan.
                anchored_in_window = not enrich_enabled() or (
                    parse_timestamp(representative.captured_at)
                    >= parse_timestamp(request["requested_at"])
                )
                if anchored_in_window:
                    compliant_verifications.append(
                        {
                            "system_id": system_id,
                            "resource_id": resource_id,
                            "operation": "VERIFY_RECORD_ABSENT",
                            "state": "ABSENT",
                            "evidence_id": state.evidence_id,
                        }
                    )
            continue

        if action in {"REDACT", "ANONYMIZE"}:
            prohibited = (
                state.state == "PRESENT"
                and rule_engine.has_prohibited_identifiers(
                    category,
                    attributes,
                    identity_values=identity_values,
                )
            )
            if prohibited:
                finding_operation, finding_state = FINDING_FOR_ACTION[action]
                remediation_operation, remediation_state = REMEDIATION_FOR_ACTION[action]
                verify_operation, verify_state = VERIFICATION_FOR_ACTION[action]
                findings.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": finding_operation,
                        "state": finding_state,
                        "evidence_id": state.evidence_id,
                    }
                )
                remediations.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": remediation_operation,
                        "state": remediation_state,
                        "evidence_id": "",
                    }
                )
                future_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": verify_operation,
                        "state": verify_state,
                        "evidence_id": "",
                    }
                )
            elif state.state == "PRESENT":
                verify_operation, verify_state = VERIFICATION_FOR_ACTION[action]
                compliant_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": verify_operation,
                        "state": verify_state,
                        "evidence_id": state.evidence_id,
                    }
                )
            elif state.state == "ABSENT":
                compliant_verifications.append(
                    {
                        "system_id": system_id,
                        "resource_id": resource_id,
                        "operation": "VERIFY_RECORD_ABSENT",
                        "state": "ABSENT",
                        "evidence_id": state.evidence_id,
                    }
                )
            continue

        if action == "RETAIN" and state.state == "PRESENT":
            compliant_verifications.append(
                {
                    "system_id": system_id,
                    "resource_id": resource_id,
                    "operation": "VERIFY_RECORD_PRESENT",
                    "state": "PRESENT",
                    "evidence_id": state.evidence_id,
                }
            )
        elif action == "RETAIN" and state.state == "ABSENT":
            # The contract requires retained records to remain available, but
            # its allowed operations have no finding/remediation pair for a
            # missing retained record. Preserve the required INCOMPLETE verdict
            # without inventing a new operation or mislabeling the absence.
            missing_required_retention = True

    if findings or missing_required_retention:
        # An incomplete case still needs a complete post-remediation checklist.
        # Include records and processes that already satisfy policy alongside
        # the checks for findings being remediated. Future checks carry no
        # evidence because they have not happened yet.
        incomplete_verifications = [
            *future_verifications,
            *crossref_verifications,
            *(
                {**step, "evidence_id": ""}
                for step in compliant_verifications
            ),
        ]
        return {
            "case_id": request["case_id"],
            "deletion_status": "INCOMPLETE",
            "steps": build_steps(
                findings, remediations, incomplete_verifications
            ),
        }
    if compliant_verifications:
        return {
            "case_id": request["case_id"],
            "deletion_status": "COMPLETE",
            "steps": build_steps([], [], compliant_verifications),
        }
    # With no subject-linked, state-bearing evidence, the baseline cannot prove
    # completion or invent findings. Preserve this as unresolved/incomplete.
    return {
        "case_id": request["case_id"],
        "deletion_status": "INCOMPLETE",
        "steps": [],
    }


def run_baseline(bundle: DatasetBundle) -> list[dict[str, Any]]:
    identity_resolver = IdentityResolver(
        bundle.tables["user_identities.csv"],
        bundle.tables["user_audit_log.csv"],
    )
    rules = RuleEngine(bundle.tables["deletion_rules.csv"])
    activities = bundle.tables["system_activity.csv"]
    requests = bundle.tables["deletion_requests.csv"]
    return [
        assess_case(
            request,
            store=bundle.store,
            identity_resolver=identity_resolver,
            rule_engine=rules,
            activities=activities,
        )
        for request in sorted(requests, key=lambda row: row["case_id"])
    ]
