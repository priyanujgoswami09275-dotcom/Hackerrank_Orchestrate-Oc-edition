"""Identity reconstruction from the current snapshot and historical audit log."""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from typing import Iterable, Mapping

from .loader import read_csv_rows
from .store import RecordStore, normalize_identifier, parse_timestamp


PHONE_DIGITS = re.compile(r"\D+")
EMAIL_HASH = re.compile(r"^[a-f0-9]{64}$", re.I)
EMPTY_IDENTIFIERS = {"", "null", "none", "nan", "n/a", "unknown"}


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def email_sha256(value: str) -> str:
    return hashlib.sha256(normalize_email(value).encode("utf-8")).hexdigest()


def normalize_phone(value: str) -> str:
    return PHONE_DIGITS.sub("", value)


@dataclass(frozen=True)
class ResolvedIdentity:
    user_id: str
    names: tuple[str, ...]
    emails: tuple[str, ...]
    email_hashes: tuple[str, ...]
    phones: tuple[str, ...]
    customer_references: tuple[str, ...]


class IdentityResolver:
    """Resolve identifiers that are valid or historically known by audit_at."""

    def __init__(
        self,
        identity_rows: Iterable[Mapping[str, str]],
        audit_rows: Iterable[Mapping[str, str]],
    ) -> None:
        self._identities = {
            row["user_id"]: dict(row) for row in identity_rows if row.get("user_id")
        }
        self._events: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in audit_rows:
            if row.get("user_id"):
                parse_timestamp(row["event_time"])
                self._events[row["user_id"]].append(dict(row))
        for events in self._events.values():
            events.sort(key=lambda row: (parse_timestamp(row["event_time"]), row["audit_id"]))

    @classmethod
    def from_dataset(cls, root: str) -> "IdentityResolver":
        from pathlib import Path

        dataset = Path(root) / "dataset"
        return cls(
            read_csv_rows(dataset / "user_identities.csv"),
            read_csv_rows(dataset / "user_audit_log.csv"),
        )

    def _events_as_of(self, user_id: str, audit_at: str) -> list[dict[str, str]]:
        cutoff = parse_timestamp(audit_at)
        return [
            event
            for event in self._events.get(user_id, ())
            if parse_timestamp(event["event_time"]) <= cutoff
        ]

    def _field_state_as_of(
        self, user_id: str, field_name: str, audit_at: str
    ) -> str:
        row = self._identities[user_id]
        events = [
            event
            for event in self._events_as_of(user_id, audit_at)
            if event.get("field_name") == field_name
        ]
        snapshot_time = parse_timestamp(row["updated_at"])
        cutoff = parse_timestamp(audit_at)
        if snapshot_time <= cutoff:
            # Move forward only through changes after the snapshot and by audit_at.
            current = row.get(field_name, "")
            for event in events:
                event_time = parse_timestamp(event["event_time"])
                if snapshot_time < event_time <= cutoff:
                    current = event["new_value"]
            return current
        else:
            # A future snapshot is not read as state at the cutoff. Rebuild only
            # from history visible by audit_at; if no such history exists, abstain.
            return events[-1]["new_value"] if events else ""

    def identifiers_for(self, user_id: str, audit_at: str) -> ResolvedIdentity | None:
        if user_id not in self._identities:
            return None
        parse_timestamp(audit_at)
        row = self._identities[user_id]
        events = self._events_as_of(user_id, audit_at)
        snapshot_visible = parse_timestamp(row["updated_at"]) <= parse_timestamp(audit_at)
        field_names = {
            "email": set(),
            "email_hash": set(),
            "phone": set(),
            "customer_reference": set(),
        }
        for event in events:
            field_name = event["field_name"]
            if field_name in field_names:
                for value in (event["old_value"], event["new_value"]):
                    if value.strip().casefold() not in EMPTY_IDENTIFIERS:
                        field_names[field_name].add(value.strip())
        if snapshot_visible:
            for field_name in field_names:
                value = row.get(field_name, "").strip()
                if value.casefold() not in EMPTY_IDENTIFIERS:
                    field_names[field_name].add(value)
        for field_name in field_names:
            value = self._field_state_as_of(user_id, field_name, audit_at)
            if value.strip().casefold() not in EMPTY_IDENTIFIERS:
                field_names[field_name].add(value.strip())

        emails = {normalize_email(value) for value in field_names["email"] if value}
        hashes = {
            normalize_identifier(value)
            for value in field_names["email_hash"]
            if EMAIL_HASH.fullmatch(value.strip())
        }
        hashes.update(email_sha256(value) for value in emails)
        phones = {normalize_phone(value) for value in field_names["phone"] if value}
        references = {
            value.strip()
            for value in field_names["customer_reference"]
            if value.strip()
        }

        names = (
            {row["name"].strip()}
            if snapshot_visible and row.get("name", "").strip()
            else set()
        )
        return ResolvedIdentity(
            user_id=user_id,
            names=tuple(sorted(names, key=str.casefold)),
            emails=tuple(sorted(emails)),
            email_hashes=tuple(sorted(hashes)),
            phones=tuple(sorted(phones)),
            customer_references=tuple(sorted(references)),
        )

    def resolve_email(self, email: str, audit_at: str) -> tuple[ResolvedIdentity, ...]:
        normalized = normalize_email(email)
        hashed = email_sha256(normalized)
        matches = []
        for user_id in sorted(self._identities):
            identity = self.identifiers_for(user_id, audit_at)
            if identity and (
                normalized in identity.emails or hashed in identity.email_hashes
            ):
                matches.append(identity)
        return tuple(matches)

    def resolve_identifier(
        self, identifier: str, audit_at: str
    ) -> tuple[ResolvedIdentity, ...]:
        value = identifier.strip()
        normalized = normalize_identifier(value)
        if "@" in value:
            return self.resolve_email(value, audit_at)
        if EMAIL_HASH.fullmatch(value):
            field_name = "email_hashes"
            wanted = {normalized}
        elif value.lower().startswith("user_"):
            field_name = "user_ids"
            wanted = {normalized}
        elif value.lower().startswith("customer_"):
            field_name = "customer_references"
            wanted = {normalized}
        else:
            field_name = "phones"
            wanted = {normalize_phone(value)}

        matches = []
        for user_id in sorted(self._identities):
            identity = self.identifiers_for(user_id, audit_at)
            if identity is None:
                continue
            if field_name == "user_ids":
                values = (identity.user_id,)
            else:
                values = getattr(identity, field_name)
            normalized_values = (
                {normalize_identifier(item) for item in values}
                if field_name != "phones"
                else {normalize_phone(item) for item in values}
            )
            if wanted.intersection(normalized_values):
                matches.append(identity)
            elif field_name == "user_ids" and normalize_identifier(user_id) in wanted:
                matches.append(identity)
        return tuple(matches)

    def current_hash_match_count(self) -> tuple[int, int]:
        matched = 0
        total = 0
        for row in self._identities.values():
            email = normalize_email(row.get("email", ""))
            if not email:
                continue
            total += 1
            matched += int(email_sha256(email) == row.get("email_hash", "").casefold())
        return matched, total

    def enrich_customer_references(
        self,
        identity: ResolvedIdentity,
        *,
        audit_at: str,
        store: RecordStore,
    ) -> ResolvedIdentity:
        """Join references only through already-resolved, cutoff-visible identifiers."""
        values = {
            identity.user_id,
            *identity.emails,
            *identity.email_hashes,
            *identity.phones,
            *identity.customer_references,
        }
        records = store.query(audit_at=audit_at, identifier_values=values)
        references = set(identity.customer_references)
        for record in records:
            references.update(record.identifiers.get("customer_references", ()))
        return replace(
            identity,
            customer_references=tuple(sorted(references, key=str.casefold)),
        )
