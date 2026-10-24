"""Strict output-contract validator."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .constants import OPERATION_ORDER, PHASE_ORDER
from .planner import STEP_FIELDS, step_sort_key
from .store import parse_timestamp


STATUS_VALUES = {"COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"}
STATE_BY_OPERATION = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}


def _known_evidence_times(
    manifest: Iterable[Mapping[str, str]],
    activities: Iterable[Mapping[str, str]],
    audit_rows: Iterable[Mapping[str, str]],
) -> dict[str, str]:
    times = {row["file_id"]: row["captured_at"] for row in manifest}
    times.update({row["activity_id"]: row["event_time"] for row in activities})
    times.update({row["audit_id"]: row["event_time"] for row in audit_rows})
    return times


def validate_rows(
    requests: Iterable[Mapping[str, str]],
    output_rows: Iterable[Mapping[str, Any]],
    *,
    manifest: Iterable[Mapping[str, str]],
    activities: Iterable[Mapping[str, str]],
    audit_rows: Iterable[Mapping[str, str]],
) -> None:
    request_map = {row["case_id"]: row for row in requests}
    rows = list(output_rows)
    if len(rows) != len(request_map):
        raise ValueError(
            f"expected {len(request_map)} output rows, got {len(rows)}"
        )
    case_ids = [str(row.get("case_id", "")) for row in rows]
    if case_ids != sorted(request_map):
        raise ValueError("output rows must contain every case_id in sorted order")
    if len(set(case_ids)) != len(case_ids):
        raise ValueError("duplicate case_id in output")

    evidence_times = _known_evidence_times(manifest, activities, audit_rows)
    for row in rows:
        case_id = row["case_id"]
        status = row["deletion_status"]
        if status not in STATUS_VALUES:
            raise ValueError(f"{case_id}: invalid deletion_status {status!r}")
        steps = row["steps"]
        if not isinstance(steps, list):
            raise ValueError(f"{case_id}: steps must be a JSON array")
        if status == "NOT_APPLICABLE":
            if steps:
                raise ValueError(f"{case_id}: NOT_APPLICABLE must have no steps")
            continue

        if [step.get("step_no") for step in steps] != list(
            range(1, len(steps) + 1)
        ):
            raise ValueError(f"{case_id}: step_no must be consecutive from 1")
        if [step_sort_key(step) for step in steps] != sorted(
            step_sort_key(step) for step in steps
        ):
            raise ValueError(f"{case_id}: steps violate phase/operation/resource order")

        phases = []
        for step in steps:
            if set(step) != set(STEP_FIELDS):
                raise ValueError(f"{case_id}: step keys do not match the contract")
            operation = step["operation"]
            if operation not in STATE_BY_OPERATION:
                raise ValueError(f"{case_id}: unsupported operation {operation!r}")
            expected_phase, expected_state = STATE_BY_OPERATION[operation]
            if step["phase"] != expected_phase or step["state"] != expected_state:
                raise ValueError(
                    f"{case_id}: invalid phase/state for {operation}: "
                    f"{step['phase']}/{step['state']}"
                )
            if not step["system_id"] or not step["resource_id"]:
                raise ValueError(f"{case_id}: system_id/resource_id must be nonempty")
            phases.append(step["phase"])
            evidence_id = step["evidence_id"]
            if status == "COMPLETE":
                if step["phase"] != "VERIFICATION" or not evidence_id:
                    raise ValueError(
                        f"{case_id}: COMPLETE permits only evidence-backed VERIFICATION steps"
                    )
            elif step["phase"] in {"REMEDIATION", "VERIFICATION"}:
                if evidence_id:
                    raise ValueError(
                        f"{case_id}: proposed remediation/future verification must have empty evidence_id"
                    )
            elif step["phase"] == "FINDING" and not evidence_id:
                raise ValueError(f"{case_id}: findings require evidence_id")
            if evidence_id:
                captured_at = evidence_times.get(evidence_id)
                if captured_at is None:
                    raise ValueError(f"{case_id}: unknown evidence_id {evidence_id!r}")
                if parse_timestamp(captured_at) > parse_timestamp(
                    request_map[case_id]["audit_at"]
                ):
                    raise ValueError(
                        f"{case_id}: evidence {evidence_id!r} is after audit_at"
                    )
        if status == "COMPLETE" and any(phase != "VERIFICATION" for phase in phases):
            raise ValueError(f"{case_id}: COMPLETE must contain only verification")
        if status == "INCOMPLETE" and phases:
            expected_phase_order = sorted(phases, key=PHASE_ORDER.index)
            if phases != expected_phase_order:
                raise ValueError(f"{case_id}: phase order is invalid")
