"""Read-only, cutoff-bound tools available to one case investigator."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Iterable, Mapping

from ..identity import ResolvedIdentity, normalize_email, normalize_phone
from ..linkage import referenced_resource_ids
from ..loader import system_from_resource
from ..rules import RuleEngine
from ..store import (
    CapturedText,
    NormalizedRecord,
    RecordScope,
    RecordStore,
    normalize_identifier,
    parse_timestamp,
)


MAX_RESULTS = 25
MAX_TEXT_CHARS = 8_000
MAX_VALUE_CHARS = 2_000


class ToolArgumentError(ValueError):
    """Raised when a tool call is outside its fixed case-scoped schema."""


@dataclass(frozen=True)
class ToolObservation:
    observation_id: str
    tool_name: str
    arguments: Mapping[str, Any]
    result: Mapping[str, Any]


def _schema(
    name: str,
    description: str,
    properties: dict[str, Any],
    *,
    required: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": list(required if required is not None else properties),
                "additionalProperties": False,
            },
        },
    }


TOOL_SCHEMAS = [
    _schema(
        "resolve_identity",
        "Resolve one identifier only against this audit's already-resolved subject.",
        {"identifier": {"type": "string", "minLength": 1, "maxLength": 256}},
    ),
    _schema(
        "search_records",
        "Search cutoff-eligible normalized records for one of this subject's identifiers.",
        {
            "identifier": {"type": "string", "minLength": 1, "maxLength": 256},
            "system_id": {"type": "string", "minLength": 1, "maxLength": 128},
        },
        required=("identifier",),
    ),
    _schema(
        "compare_replicas",
        "Compare cutoff-eligible copies of a resource already linked to this subject.",
        {"resource_id": {"type": "string", "minLength": 1, "maxLength": 256}},
    ),
    _schema(
        "get_activity",
        "Read cutoff-eligible activity rows that mention one of this subject's identifiers.",
        {"subject": {"type": "string", "minLength": 1, "maxLength": 256}},
    ),
    _schema(
        "get_rules",
        "Read the participant-visible deletion rule for one data category.",
        {"category": {"type": "string", "minLength": 1, "maxLength": 128}},
    ),
    _schema(
        "read_text_evidence",
        "Read one manifest-listed text capture when it is available by this audit cutoff.",
        {"evidence_id": {"type": "string", "minLength": 1, "maxLength": 256}},
    ),
]
TOOL_NAMES = frozenset(schema["function"]["name"] for schema in TOOL_SCHEMAS)


def _safe_json(value: Any, *, depth: int = 0) -> Any:
    """Bound nested evidence values before returning them to a model."""
    if depth > 5:
        return "[truncated]"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:MAX_VALUE_CHARS]
    if isinstance(value, Mapping):
        return {
            str(key)[:128]: _safe_json(child, depth=depth + 1)
            for key, child in list(value.items())[:100]
        }
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_safe_json(child, depth=depth + 1) for child in list(value)[:100]]
    return str(value)[:MAX_VALUE_CHARS]


class CaseToolbox:
    """A fixed tool registry whose data access is bound to one request cutoff."""

    def __init__(
        self,
        *,
        request: Mapping[str, str],
        identity: ResolvedIdentity,
        store: RecordStore,
        activities: Iterable[Mapping[str, Any]],
        rule_engine: RuleEngine,
        manifest: Iterable[Mapping[str, str]],
    ) -> None:
        self.request = dict(request)
        self.identity = identity
        self.store = store
        self.activities = tuple(dict(row) for row in activities)
        self.rule_engine = rule_engine
        self.audit_at = str(request["audit_at"])
        self._cutoff = parse_timestamp(self.audit_at)
        self._manifest_entries = tuple(dict(row) for row in manifest)
        self._manifest = {
            str(row.get("file_id", "")): dict(row)
            for row in self._manifest_entries
            if row.get("file_id")
        }
        self._resource_links: set[tuple[str, str, str]] = set()
        self._subject_records: dict[
            tuple[str, str, str, str, str], NormalizedRecord
        ] = {}
        self._observations: list[ToolObservation] = []

    @staticmethod
    def schemas() -> list[dict[str, Any]]:
        return json.loads(json.dumps(TOOL_SCHEMAS))

    @property
    def observations(self) -> tuple[ToolObservation, ...]:
        return tuple(self._observations)

    def fresh_for_replay(self) -> "CaseToolbox":
        """Create a clean toolbox so replay cannot rely on prior mutable state."""
        return CaseToolbox(
            request=self.request,
            identity=self.identity,
            store=self.store,
            activities=self.activities,
            rule_engine=self.rule_engine,
            manifest=self._manifest_entries,
        )

    def _identity_values(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    self.identity.user_id,
                    *self.identity.emails,
                    *self.identity.email_hashes,
                    *self.identity.phones,
                    *self.identity.customer_references,
                },
                key=str.casefold,
            )
        )

    def _canonical_subject_identifier(self, raw: str) -> str | None:
        value = raw.strip()
        if not value:
            return None
        folded = normalize_identifier(value)
        if folded == normalize_identifier(self.identity.user_id):
            return self.identity.user_id
        for email in self.identity.emails:
            if normalize_email(value) == normalize_email(email):
                return email
        for digest in self.identity.email_hashes:
            if folded == normalize_identifier(digest):
                return digest
        if re.fullmatch(r"[0-9+().\-\s]+", value):
            normalized_phone = normalize_phone(value)
            for phone in self.identity.phones:
                if normalized_phone and normalized_phone == normalize_phone(phone):
                    return phone
        for reference in self.identity.customer_references:
            if folded == normalize_identifier(reference):
                return reference
        return None

    def _record_dict(self, record: NormalizedRecord) -> dict[str, Any]:
        return {
            "capture_id": record.capture_id,
            "captured_at": record.captured_at,
            "topology": record.topology,
            "system_id": record.system_id,
            "resource_id": record.resource_id,
            "category": record.category,
            "identifiers": _safe_json(record.identifiers),
            "attributes": _safe_json(record.attributes),
        }

    def _is_subject_activity(self, row: Mapping[str, Any]) -> bool:
        rendered = " ".join(str(value) for value in row.values() if value is not None)
        folded = rendered.casefold()
        for value in self._identity_values():
            if not value:
                continue
            if value in self.identity.phones:
                digits = normalize_phone(value)
                if digits and re.search(rf"(?<!\d){re.escape(digits)}(?!\d)", normalize_phone(rendered)):
                    return True
                continue
            escaped = re.escape(value)
            if re.search(rf"(?<![\w]){escaped}(?![\w])", folded, flags=re.IGNORECASE):
                return True
        return False

    def _validate_arguments(self, name: str, arguments: Mapping[str, Any]) -> dict[str, str]:
        if not isinstance(arguments, Mapping):
            raise ToolArgumentError("tool arguments must be an object")
        required_by_tool = {
            "resolve_identity": {"identifier"},
            "search_records": {"identifier"},
            "compare_replicas": {"resource_id"},
            "get_activity": {"subject"},
            "get_rules": {"category"},
            "read_text_evidence": {"evidence_id"},
        }
        if name not in required_by_tool:
            raise ToolArgumentError(f"unknown tool: {name}")
        allowed = required_by_tool[name] | (
            {"system_id"} if name == "search_records" else set()
        )
        if set(arguments) != allowed and not (
            name == "search_records" and set(arguments) == {"identifier"}
        ):
            raise ToolArgumentError("tool arguments do not match the fixed schema")
        normalized: dict[str, str] = {}
        for key, value in arguments.items():
            if not isinstance(value, str) or not value.strip():
                raise ToolArgumentError(f"{key} must be a non-empty string")
            if len(value) > (256 if key != "system_id" and key != "category" else 128):
                raise ToolArgumentError(f"{key} exceeds the maximum length")
            normalized[key] = value.strip()
        return normalized

    def dispatch(self, name: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
        args = self._validate_arguments(name, arguments)
        if name == "resolve_identity":
            return self._resolve_identity(args["identifier"])
        if name == "search_records":
            return self._search_records(args["identifier"], args.get("system_id"))
        if name == "compare_replicas":
            return self._compare_replicas(args["resource_id"])
        if name == "get_activity":
            return self._get_activity(args["subject"])
        if name == "get_rules":
            return self._get_rules(args["category"])
        if name == "read_text_evidence":
            return self._read_text(args["evidence_id"])
        raise ToolArgumentError(f"unknown tool: {name}")

    def observe(self, name: str, arguments: Mapping[str, Any]) -> ToolObservation:
        canonical_args = json.loads(json.dumps(arguments, sort_keys=True))
        result = self.dispatch(name, canonical_args)
        observation = ToolObservation(
            observation_id=f"obs_{len(self._observations) + 1:04d}",
            tool_name=name,
            arguments=canonical_args,
            result=result,
        )
        self._observations.append(observation)
        return observation

    def _resolve_identity(self, identifier: str) -> dict[str, Any]:
        if self._canonical_subject_identifier(identifier) is None:
            return {"matches": []}
        return {
            "matches": [
                {
                    "user_id": self.identity.user_id,
                    "names": list(self.identity.names),
                    "emails": list(self.identity.emails),
                    "email_hashes": list(self.identity.email_hashes),
                    "phones": list(self.identity.phones),
                    "customer_references": list(self.identity.customer_references),
                }
            ]
        }

    def _search_records(
        self, identifier: str, system_id: str | None
    ) -> dict[str, Any]:
        canonical = self._canonical_subject_identifier(identifier)
        if canonical is None:
            return {"records": []}
        records = self.store.query(
            audit_at=self.audit_at,
            system_id=system_id,
            identifier_values=(canonical,),
        )[:MAX_RESULTS]
        result = []
        for record in records:
            key = (record.system_id, record.resource_id, record.category)
            self._resource_links.add(key)
            self._subject_records[
                (
                    record.capture_id,
                    record.system_id,
                    record.resource_id,
                    record.category,
                    record.topology,
                )
            ] = record
            result.append(self._record_dict(record))
        return {"records": result, "truncated": len(records) == MAX_RESULTS}

    def _compare_replicas(self, resource_id: str) -> dict[str, Any]:
        linked_keys = {
            key for key in self._resource_links if key[1] == resource_id
        }
        referenced = {
            linked_resource
            for record in self._subject_records.values()
            for linked_resource in referenced_resource_ids(
                record.attributes,
                own_resource_id=record.resource_id,
            )
        }
        if not linked_keys and resource_id not in referenced:
            raise ToolArgumentError("resource has not been linked to this subject")
        copies: list[dict[str, Any]] = []
        scopes: list[dict[str, Any]] = []
        for system_id, linked_resource, category in sorted(linked_keys):
            copies.extend(
                self._record_dict(record)
                for record in self.store.query(
                    audit_at=self.audit_at,
                    system_id=system_id,
                    resource_id=linked_resource,
                    category=category,
                )
            )
            scopes.extend(
                {
                    "capture_id": scope.capture_id,
                    "captured_at": scope.captured_at,
                    "topology": scope.topology,
                    "system_id": scope.system_id,
                    "category": scope.category,
                    "complete_listing": scope.complete_listing,
                }
                for scope in self.store.query_scopes(
                    audit_at=self.audit_at,
                    system_id=system_id,
                    category=category,
                )
            )
        if resource_id in referenced:
            referenced_system = system_from_resource(resource_id)
            if referenced_system is not None:
                referenced_records = self.store.query(
                    audit_at=self.audit_at,
                    system_id=referenced_system,
                    resource_id=resource_id,
                )
                copies.extend(self._record_dict(record) for record in referenced_records)
                categories = {record.category for record in referenced_records}
                for category in sorted(categories):
                    scopes.extend(
                        {
                            "capture_id": scope.capture_id,
                            "captured_at": scope.captured_at,
                            "topology": scope.topology,
                            "system_id": scope.system_id,
                            "category": scope.category,
                            "complete_listing": scope.complete_listing,
                        }
                        for scope in self.store.query_scopes(
                            audit_at=self.audit_at,
                            system_id=referenced_system,
                            category=category,
                        )
                    )
        copies = list(
            {
                (
                    row["capture_id"],
                    row["system_id"],
                    row["resource_id"],
                    row["category"],
                    row["topology"],
                ): row
                for row in copies
            }.values()
        )
        scopes = list(
            {
                (
                    row["capture_id"],
                    row["system_id"],
                    row["category"],
                    row["topology"],
                ): row
                for row in scopes
            }.values()
        )
        copies.sort(
            key=lambda row: (
                row["captured_at"], row["topology"], row["capture_id"]
            )
        )
        scopes.sort(
            key=lambda row: (
                row["captured_at"], row["topology"], row["capture_id"]
            )
        )
        return {
            "resource_id": resource_id,
            "records": copies[:MAX_RESULTS],
            "scopes": scopes[:MAX_RESULTS],
            "truncated": len(copies) > MAX_RESULTS or len(scopes) > MAX_RESULTS,
        }

    def _get_activity(self, subject: str) -> dict[str, Any]:
        if self._canonical_subject_identifier(subject) is None:
            return {"events": []}
        matching = []
        for row in self.activities:
            event_time = row.get("event_time")
            if not isinstance(event_time, str) or parse_timestamp(event_time) > self._cutoff:
                continue
            if self._is_subject_activity(row):
                matching.append(_safe_json(row))
        matching.sort(
            key=lambda row: (row.get("event_time", ""), row.get("activity_id", ""))
        )
        return {
            "events": matching[:MAX_RESULTS],
            "truncated": len(matching) > MAX_RESULTS,
        }

    def _get_rules(self, category: str) -> dict[str, Any]:
        rule = self.rule_engine.rule_for(category)
        if rule is None:
            return {"rule": None}
        return {
            "rule": {
                "rule_id": rule.rule_id,
                "data_category": rule.data_category,
                "condition": rule.condition,
                "required_action": rule.required_action,
            }
        }

    def _read_text(self, evidence_id: str) -> dict[str, Any]:
        item = self._manifest.get(evidence_id)
        if item is None:
            raise ToolArgumentError("evidence ID is not present in the manifest")
        captured_at = str(item.get("captured_at", ""))
        if not captured_at or parse_timestamp(captured_at) > self._cutoff:
            raise ToolArgumentError("evidence is not available by this audit cutoff")
        text_capture = self.store.read_text(
            audit_at=self.audit_at,
            capture_id=evidence_id,
        )
        if text_capture is None:
            raise ToolArgumentError("manifest item has no cutoff-eligible text capture")
        if (
            text_capture.file_path != str(item.get("file_path", ""))
            or parse_timestamp(text_capture.captured_at) != parse_timestamp(captured_at)
        ):
            raise ToolArgumentError("text capture does not match its manifest entry")
        return {
            "evidence_id": evidence_id,
            "file_path": text_capture.file_path,
            "origin": str(item.get("origin", "")),
            "captured_at": text_capture.captured_at,
            "text": text_capture.text[:MAX_TEXT_CHARS],
            "truncated": len(text_capture.text) > MAX_TEXT_CHARS,
        }
