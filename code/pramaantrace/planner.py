"""Deterministic step ordering and serialization."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .constants import OPERATION_ORDER, PHASE_ORDER


STEP_FIELDS = (
    "step_no",
    "phase",
    "system_id",
    "resource_id",
    "operation",
    "state",
    "evidence_id",
)
PHASE_BY_OPERATION = {
    phase: {operation: index for index, operation in enumerate(operations)}
    for phase, operations in OPERATION_ORDER.items()
}


def step_sort_key(step: Mapping[str, Any]) -> tuple[Any, ...]:
    phase = str(step["phase"])
    operation = str(step["operation"])
    return (
        PHASE_ORDER.index(phase),
        PHASE_BY_OPERATION[phase][operation],
        str(step["system_id"]),
        str(step["resource_id"]),
        str(step["evidence_id"]),
    )


def build_steps(
    findings: Iterable[Mapping[str, Any]],
    remediations: Iterable[Mapping[str, Any]],
    verifications: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    steps = []
    for phase, rows in (
        ("FINDING", findings),
        ("REMEDIATION", remediations),
        ("VERIFICATION", verifications),
    ):
        for item in rows:
            step = {
                "phase": phase,
                "system_id": str(item["system_id"]),
                "resource_id": str(item["resource_id"]),
                "operation": str(item["operation"]),
                "state": str(item["state"]),
                "evidence_id": str(item.get("evidence_id", "")),
            }
            steps.append(step)

    steps.sort(key=step_sort_key)
    deduplicated = []
    seen = set()
    for step in steps:
        identity = (
            step["phase"],
            step["operation"],
            step["system_id"],
            step["resource_id"],
        )
        if identity in seen:
            continue
        seen.add(identity)
        step["step_no"] = len(deduplicated) + 1
        deduplicated.append(step)
    return deduplicated
