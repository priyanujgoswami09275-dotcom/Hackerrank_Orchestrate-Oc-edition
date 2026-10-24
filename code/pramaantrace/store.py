"""Normalized, temporally gated evidence store."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp must include a timezone: {value!r}")
    return parsed.astimezone(timezone.utc)


def normalize_identifier(value: Any) -> str:
    return str(value).strip().casefold()


@dataclass(frozen=True)
class NormalizedRecord:
    capture_id: str
    captured_at: str
    topology: str
    system_id: str
    resource_id: str
    category: str
    identifiers: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    attributes: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CapturedText:
    capture_id: str
    captured_at: str
    file_path: str
    text: str


@dataclass(frozen=True)
class RecordScope:
    """A point-in-time listing scope, including scopes with zero records."""

    capture_id: str
    captured_at: str
    topology: str
    system_id: str
    category: str


class RecordStore:
    """Evidence records with no public unfiltered read API.

    Every query requires an audit cutoff and enforces the capture-time gate
    before applying any caller-provided filters.
    """

    def __init__(self) -> None:
        self.__records: list[NormalizedRecord] = []
        self.__texts: dict[str, CapturedText] = {}
        self.__scopes: list[RecordScope] = []

    def add_record(self, record: NormalizedRecord) -> None:
        # Validate timestamps when ingesting so later filtering is predictable.
        parse_timestamp(record.captured_at)
        if not all(
            (
                record.capture_id,
                record.topology,
                record.system_id,
                record.resource_id,
                record.category,
            )
        ):
            raise ValueError("normalized records require capture, topology, system, resource, and category")
        self.__records.append(record)

    def add_text(self, item: CapturedText) -> None:
        parse_timestamp(item.captured_at)
        self.__texts[item.capture_id] = item

    def add_scope(self, scope: RecordScope) -> None:
        parse_timestamp(scope.captured_at)
        if not all(
            (scope.capture_id, scope.topology, scope.system_id, scope.category)
        ):
            raise ValueError(
                "snapshot scopes require capture, topology, system, and category"
            )
        self.__scopes.append(scope)

    def query(
        self,
        *,
        audit_at: str,
        capture_id: str | None = None,
        system_id: str | None = None,
        resource_id: str | None = None,
        category: str | None = None,
        topology: str | None = None,
        identifier_values: Iterable[str] | None = None,
    ) -> list[NormalizedRecord]:
        cutoff = parse_timestamp(audit_at)
        wanted = (
            {normalize_identifier(value) for value in identifier_values}
            if identifier_values is not None
            else None
        )
        result = []
        for record in self.__records:
            # Mandatory temporal gate: no filter may bypass this condition.
            if parse_timestamp(record.captured_at) > cutoff:
                continue
            if capture_id is not None and record.capture_id != capture_id:
                continue
            if system_id is not None and record.system_id != system_id:
                continue
            if resource_id is not None and record.resource_id != resource_id:
                continue
            if category is not None and record.category != category:
                continue
            if topology is not None and record.topology != topology:
                continue
            if wanted is not None:
                indexed = {
                    normalize_identifier(value)
                    for values in record.identifiers.values()
                    for value in values
                }
                if not wanted.intersection(indexed):
                    continue
            result.append(record)
        return sorted(
            result,
            key=lambda item: (
                parse_timestamp(item.captured_at),
                item.capture_id,
                item.system_id,
                item.resource_id,
                item.topology,
            ),
        )

    def read_text(self, *, audit_at: str, capture_id: str) -> CapturedText | None:
        cutoff = parse_timestamp(audit_at)
        item = self.__texts.get(capture_id)
        if item is None or parse_timestamp(item.captured_at) > cutoff:
            return None
        return item

    def query_scopes(
        self,
        *,
        audit_at: str,
        capture_id: str | None = None,
        system_id: str | None = None,
        category: str | None = None,
        topology: str | None = None,
    ) -> list[RecordScope]:
        cutoff = parse_timestamp(audit_at)
        result = [
            scope
            for scope in self.__scopes
            if parse_timestamp(scope.captured_at) <= cutoff
            and (capture_id is None or scope.capture_id == capture_id)
            and (system_id is None or scope.system_id == system_id)
            and (category is None or scope.category == category)
            and (topology is None or scope.topology == topology)
        ]
        return sorted(
            result,
            key=lambda item: (
                parse_timestamp(item.captured_at),
                item.capture_id,
                item.system_id,
                item.category,
                item.topology,
            ),
        )

    def capture_ids(self, *, audit_at: str) -> tuple[str, ...]:
        cutoff = parse_timestamp(audit_at)
        ids = {
            record.capture_id
            for record in self.__records
            if parse_timestamp(record.captured_at) <= cutoff
        }
        ids.update(
            capture_id
            for capture_id, item in self.__texts.items()
            if parse_timestamp(item.captured_at) <= cutoff
        )
        ids.update(
            scope.capture_id
            for scope in self.__scopes
            if parse_timestamp(scope.captured_at) <= cutoff
        )
        return tuple(sorted(ids))

    def record_count(self, *, audit_at: str) -> int:
        return len(self.query(audit_at=audit_at))

