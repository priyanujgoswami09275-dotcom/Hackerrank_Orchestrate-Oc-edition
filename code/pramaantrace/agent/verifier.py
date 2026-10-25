"""Deterministic replay and subject-link verification for model candidates."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping

from ..identity import ResolvedIdentity, normalize_phone
from ..linkage import referenced_resource_ids
from ..store import NormalizedRecord, RecordStore, normalize_identifier
from .loop import CandidateLink
from .tools import CaseToolbox, ToolObservation


def _identity_values(identity: ResolvedIdentity) -> dict[str, set[str]]:
    return {
        "emails": {normalize_identifier(value) for value in identity.emails},
        "email_hashes": {
            normalize_identifier(value) for value in identity.email_hashes
        },
        "phones": {normalize_phone(value) for value in identity.phones},
        "user_ids": {normalize_identifier(identity.user_id)},
        "customer_references": {
            normalize_identifier(value) for value in identity.customer_references
        },
    }


def _record_identifier_values(record: NormalizedRecord) -> dict[str, set[str]]:
    return {
        "emails": {
            normalize_identifier(value)
            for value in record.identifiers.get("emails", ())
        },
        "email_hashes": {
            normalize_identifier(value)
            for value in record.identifiers.get("email_hashes", ())
        },
        "phones": {
            normalize_phone(value) for value in record.identifiers.get("phones", ())
        },
        "user_ids": {
            normalize_identifier(value)
            for value in record.identifiers.get("user_ids", ())
        },
        "customer_references": {
            normalize_identifier(value)
            for value in record.identifiers.get("customer_references", ())
        },
    }


def _directly_matches(record: NormalizedRecord, identity: ResolvedIdentity) -> bool:
    expected = _identity_values(identity)
    actual = _record_identifier_values(record)
    return any(expected[key].intersection(actual[key]) for key in expected)


def _has_identity_values(record: NormalizedRecord) -> bool:
    return any(_record_identifier_values(record).values())


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _record_for_observed_link(
    store: RecordStore,
    *,
    audit_at: str,
    capture_id: str,
    resource_id: str,
) -> list[NormalizedRecord]:
    return store.query(
        audit_at=audit_at,
        capture_id=capture_id,
        resource_id=resource_id,
    )


def _replay_observations(
    observations: Iterable[ToolObservation], toolbox: CaseToolbox
) -> tuple[dict[str, Mapping[str, Any]], set[str]]:
    replayed: dict[str, Mapping[str, Any]] = {}
    invalid: set[str] = set()
    for observation in observations:
        observation_id = getattr(observation, "observation_id", None)
        if not isinstance(observation_id, str) or not observation_id:
            continue
        if observation_id in replayed or observation_id in invalid:
            invalid.add(observation_id)
            replayed.pop(observation_id, None)
            continue
        try:
            result = toolbox.dispatch(observation.tool_name, observation.arguments)
            if _canonical(result) != _canonical(observation.result):
                invalid.add(observation_id)
                continue
            replayed[observation_id] = result
        except Exception:
            invalid.add(observation_id)
    return replayed, invalid


def _subject_linked_sources(
    observations: Iterable[ToolObservation],
    replayed: Mapping[str, Mapping[str, Any]],
    invalid: set[str],
    *,
    identity: ResolvedIdentity,
    store: RecordStore,
    audit_at: str,
) -> list[NormalizedRecord]:
    sources: dict[tuple[str, str, str, str], NormalizedRecord] = {}
    for observation in observations:
        if (
            observation.observation_id in invalid
            or observation.observation_id not in replayed
            or observation.tool_name != "search_records"
        ):
            continue
        for row in replayed[observation.observation_id].get("records", ()):
            if not isinstance(row, Mapping):
                continue
            capture_id = row.get("capture_id")
            resource_id = row.get("resource_id")
            if not isinstance(capture_id, str) or not isinstance(resource_id, str):
                continue
            for record in _record_for_observed_link(
                store,
                audit_at=audit_at,
                capture_id=capture_id,
                resource_id=resource_id,
            ):
                key = (record.capture_id, record.system_id, record.resource_id, record.category)
                if _directly_matches(record, identity):
                    sources[key] = record
    return list(sources.values())


def _candidate_is_in_observation(
    candidate: CandidateLink,
    observation: ToolObservation,
    replayed_result: Mapping[str, Any],
) -> bool:
    if observation.tool_name in {"search_records", "compare_replicas"}:
        return any(
            isinstance(row, Mapping)
            and row.get("capture_id") == candidate.capture_id
            and row.get("resource_id") == candidate.resource_id
            for row in replayed_result.get("records", ())
        )
    if observation.tool_name == "read_text_evidence":
        text = replayed_result.get("text")
        return (
            replayed_result.get("evidence_id") == candidate.capture_id
            and isinstance(text, str)
            and candidate.resource_id in text
        )
    return False


def _has_ambiguous_other_subject_reference(
    resource_id: str,
    *,
    identity: ResolvedIdentity,
    store: RecordStore,
    audit_at: str,
) -> bool:
    for record in store.query(audit_at=audit_at):
        if resource_id not in referenced_resource_ids(
            record.attributes,
            own_resource_id=record.resource_id,
        ):
            continue
        if _has_identity_values(record) and not _directly_matches(record, identity):
            return True
    return False


def _candidate_keys(
    candidate: CandidateLink,
    observation: ToolObservation,
    observations: tuple[ToolObservation, ...],
    replayed: Mapping[str, Mapping[str, Any]],
    invalid: set[str],
    *,
    request: Mapping[str, str],
    identity: ResolvedIdentity,
    store: RecordStore,
) -> tuple[tuple[str, str, str], ...]:
    obs_id = observation.observation_id
    result = replayed.get(obs_id)
    if result is None or obs_id in invalid:
        return ()
    if not _candidate_is_in_observation(candidate, observation, result):
        return ()

    target_records = _record_for_observed_link(
        store,
        audit_at=request["audit_at"],
        capture_id=candidate.capture_id,
        resource_id=candidate.resource_id,
    )
    if not target_records:
        return ()

    observed_keys = {
        (row.get("system_id"), row.get("resource_id"), row.get("category"))
        for row in result.get("records", ())
        if isinstance(row, Mapping)
        and row.get("capture_id") == candidate.capture_id
        and row.get("resource_id") == candidate.resource_id
    }
    target_keys = {
        (record.system_id, record.resource_id, record.category)
        for record in target_records
        if observation.tool_name == "read_text_evidence"
        or (record.system_id, record.resource_id, record.category) in observed_keys
    }
    if not target_keys or len({(system, category) for system, _resource, category in target_keys}) != 1:
        return ()
    if _has_ambiguous_other_subject_reference(
        candidate.resource_id,
        identity=identity,
        store=store,
        audit_at=request["audit_at"],
    ):
        return ()

    if any(_directly_matches(record, identity) for record in target_records):
        return tuple(sorted(target_keys))

    linked_sources = _subject_linked_sources(
        observations,
        replayed,
        invalid,
        identity=identity,
        store=store,
        audit_at=request["audit_at"],
    )
    if any(
        candidate.resource_id
        in referenced_resource_ids(source.attributes, own_resource_id=source.resource_id)
        for source in linked_sources
    ):
        return tuple(sorted(target_keys))
    return ()


def verify_candidate_links(
    request: Mapping[str, str],
    identity: ResolvedIdentity,
    candidates: Iterable[CandidateLink],
    observations: Iterable[ToolObservation],
    toolbox: CaseToolbox,
    store: RecordStore,
) -> tuple[tuple[str, str, str], ...]:
    """Replay observations and accept only independently proven resource links."""
    if request.get("audit_at") != toolbox.audit_at:
        return ()
    trace = tuple(observations)
    replay_toolbox = toolbox.fresh_for_replay()
    replayed, invalid = _replay_observations(trace, replay_toolbox)
    observation_by_id = {
        observation.observation_id: observation
        for observation in trace
        if isinstance(getattr(observation, "observation_id", None), str)
        and observation.observation_id not in invalid
    }
    accepted: set[tuple[str, str, str]] = set()
    for candidate in candidates:
        if not isinstance(candidate, CandidateLink):
            continue
        observation = observation_by_id.get(candidate.observation_id)
        if observation is None:
            continue
        accepted.update(
            _candidate_keys(
                candidate,
                observation,
                trace,
                replayed,
                invalid,
                request=request,
                identity=identity,
                store=store,
            )
        )
    return tuple(sorted(accepted))
