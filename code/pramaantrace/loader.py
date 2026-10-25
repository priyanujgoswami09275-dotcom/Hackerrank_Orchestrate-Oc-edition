"""Load participant-visible structured evidence into the normalized store."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .store import (
    CapturedText,
    NormalizedRecord,
    RecordScope,
    RecordStore,
    parse_timestamp,
)


IDENTIFIER_KEYS = {
    "email": "emails",
    "email_address": "emails",
    "customer_email": "emails",
    "owner_email": "emails",
    "requester_email": "emails",
    "email_hash": "email_hashes",
    "email_sha256": "email_hashes",
    "phone": "phones",
    "owner_phone": "phones",
    "requester_phone": "phones",
    "user_id": "user_ids",
    "subject_reference": "user_ids",
    "subject_ref": "user_ids",
    "user_ref": "user_ids",
    "customer_reference": "customer_references",
    "customer_ref": "customer_references",
    "name": "names",
    "full_name": "names",
    "display_name": "names",
    "requester_name": "names",
}

# Lookup/search echo keys that carry the requesting subject's identifier
# (email, hash, phone, or stable reference). They are not user-authored
# fields; their destination is inferred from the value shape.
LINK_IDENTIFIER_KEYS = frozenset(
    {"lookup_key", "query", "subject_key", "search_term", "correlation_key"}
)

# Column layout of readback handover rows: "- <ts> | <system> | <resource> | <type> | <status> | <subject>".
PIPE_ROW_PATTERN = re.compile(
    r"^\s*-\s*(\S+)\s+\|\s+([a-z][a-z_]+)\s+\|\s+([A-Za-z][A-Za-z0-9_-]*_[A-Za-z0-9_-]+)"
    r"\s+\|\s+([A-Za-z0-9_]+)\s+\|\s+([A-Za-z0-9_ ]+?)\s+\|\s+(.*?)\s*$"
)

PIPE_TYPE_CATEGORY = {
    "USER_PROFILE": "USER_PROFILE",
    "SECONDARY_IDENTIFIER": "SECONDARY_IDENTIFIER",
    "SEARCH_INDEX_ENTRY": "SEARCH_INDEX_ENTRY",
    "CACHE_ENTRY": "CACHE_ENTRY",
    "SUPPORT_MESSAGE": "SUPPORT_MESSAGE",
    "SUPPORT_ATTACHMENT": "SUPPORT_ATTACHMENT",
    "ANALYTICS_PROFILE": "ANALYTICS_PROFILE",
    "PRODUCT_TELEMETRY": "PRODUCT_TELEMETRY",
    "USER_EXPORT": "USER_EXPORT",
    "MARKETING_PROFILE": "MARKETING_PROFILE",
    "EMAIL_DELIVERY_LOG": "EMAIL_DELIVERY_LOG",
    "SECURITY_AUDIT_LOG": "SECURITY_AUDIT_LOG",
    "AUDIT_RECORD": "SECURITY_AUDIT_LOG",
    "LEGAL_HOLD_RECORD": "LEGAL_HOLD_RECORD",
    "BACKUP_ARCHIVE": "BACKUP_ARCHIVE",
    "ACCOUNT_TOMBSTONE": "ACCOUNT_TOMBSTONE",
    "DATA_FLOW": "DATA_FLOW",
}

SYSTEM_BY_TABLE = {
    "customer_profiles": ("account_service", "USER_PROFILE"),
    "customer_profiles_primary": ("account_service", "USER_PROFILE"),
    "customer_profiles_failover_replica": ("account_service", "USER_PROFILE"),
    "customer_data_primary": (None, None),  # Explicit packed-record adapter.
    "customer_data_read_replica": (None, None),
    "customer_data_replica_ap_south": (None, None),
    "customer_data_replica_eu_west": (None, None),
    "customer_data_reporting_replica": (None, None),
    "customer_data_failover_replica": (None, None),
    "customer_search_documents": ("search_service", "SEARCH_INDEX_ENTRY"),
    "customer_analytics_profiles": ("analytics_platform", "ANALYTICS_PROFILE"),
    "support_records": ("support_platform", "SUPPORT_MESSAGE"),
    "customer_exports": ("export_service", "USER_EXPORT"),
    "connector_subscriptions": ("integration_service", "DATA_FLOW"),
    "backup_restore_entries": ("backup_service", "BACKUP_ARCHIVE"),
    "security_audit_records": ("security_service", "SECURITY_AUDIT_LOG"),
    "snapshot_scope": (None, "METADATA"),
    "search_documents_primary": ("search_service", "SEARCH_INDEX_ENTRY"),
}

COLLECTION_CATEGORY = {
    "customer_profiles": "USER_PROFILE",
    "profile_lookups": "USER_PROFILE",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "customer_analytics_reports": "ANALYTICS_PROFILE",
    "profiles": "ANALYTICS_PROFILE",
    "product_telemetry": "PRODUCT_TELEMETRY",
    "telemetry": "PRODUCT_TELEMETRY",
    "backup_catalog": "BACKUP_ARCHIVE",
    "restore_entries": "BACKUP_ARCHIVE",
    "backup_restore_entries": "BACKUP_ARCHIVE",
    "connector_configurations": "DATA_FLOW",
    "connectors": "DATA_FLOW",
    "connector_subscriptions": "DATA_FLOW",
    "retained_order_records": "LEGAL_HOLD_RECORD",
    "customer_search_documents": "SEARCH_INDEX_ENTRY",
    "index_queries": "SEARCH_INDEX_ENTRY",
    "search_documents": "SEARCH_INDEX_ENTRY",
    "security_audit_events": "SECURITY_AUDIT_LOG",
    "audit_records": "SECURITY_AUDIT_LOG",
    "security_audit_records": "SECURITY_AUDIT_LOG",
    "support_conversations": "SUPPORT_MESSAGE",
    "tickets": "SUPPORT_MESSAGE",
    "support_records": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT",
    "attachments": "SUPPORT_ATTACHMENT",
    "customer_export_jobs": "USER_EXPORT",
    "exports": "USER_EXPORT",
    "customer_exports": "USER_EXPORT",
}

COLLECTION_SYSTEM = {
    "customer_profiles": "account_service",
    "profile_lookups": "account_service",
    "deleted_customer_references": "identity_service",
    "customer_analytics_reports": "analytics_platform",
    "profiles": "analytics_platform",
    "product_telemetry": "analytics_platform",
    "telemetry": "analytics_platform",
    "backup_catalog": "backup_service",
    "restore_entries": "backup_service",
    "backup_restore_entries": "backup_service",
    "connector_configurations": "integration_service",
    "connectors": "integration_service",
    "connector_subscriptions": "integration_service",
    "retained_order_records": "legal_service",
    "customer_search_documents": "search_service",
    "index_queries": "search_service",
    "search_documents": "search_service",
    "security_audit_events": "security_service",
    "audit_records": "security_service",
    "security_audit_records": "security_service",
    "support_conversations": "support_platform",
    "tickets": "support_platform",
    "support_records": "support_platform",
    "ticket_attachments": "support_platform",
    "attachments": "support_platform",
    "customer_export_jobs": "export_service",
    "exports": "export_service",
    "customer_exports": "export_service",
}

SQL_TABLES_WITHOUT_RECORDS = {"snapshot_scope"}
MEDIA_CACHE_VERSION = 2

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
HASH_PATTERN = re.compile(r"\b[a-f0-9]{64}\b", re.I)
HASH_VALUE_PATTERN = re.compile(r"^[a-f0-9]{64}$", re.I)
USER_REF_VALUE_PATTERN = re.compile(r"^(?:user|customer)_[A-Za-z0-9_-]+$", re.I)
PHONE_VALUE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()\-.]{5,20}$")
RESOURCE_PATTERN = re.compile(
    r"\b(?:resource_id|resource|record_id|object_id)\s*[=:]\s*['\"]?([A-Za-z][A-Za-z0-9_-]*_[A-Za-z0-9_-]+)",
    re.I,
)
MEDIA_RESOURCE_PATTERN = re.compile(
    r"\b(?:account|search|data_flow|analytics|export|support|backup|audit|"
    r"tombstone|legal|marketing|order|email|cache|telemetry|profile)_"
    r"[A-Za-z0-9-]+\b",
    re.I,
)
KV_PATTERN = re.compile(
    r"""([A-Za-z][A-Za-z0-9_]*)=(?:"([^"]*)"|'([^']*)'|([^\s,]+))"""
)
MEDIA_EMAIL_PATTERN = re.compile(
    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I
)
MEDIA_USER_PATTERN = re.compile(r"\buser_[A-Za-z0-9-]+\b", re.I)

MEDIA_CATEGORY_BY_PREFIX = {
    "account": "USER_PROFILE",
    "search": "SEARCH_INDEX_ENTRY",
    "data_flow": "DATA_FLOW",
    "analytics": "ANALYTICS_PROFILE",
    "export": "USER_EXPORT",
    "support": "SUPPORT_MESSAGE",
    "backup": "BACKUP_ARCHIVE",
    "audit": "SECURITY_AUDIT_LOG",
    "tombstone": "ACCOUNT_TOMBSTONE",
    "legal": "LEGAL_HOLD_RECORD",
    "marketing": "MARKETING_PROFILE",
    "order": "LEGAL_HOLD_RECORD",
    "email": "EMAIL_DELIVERY_LOG",
    "cache": "CACHE_ENTRY",
    "telemetry": "PRODUCT_TELEMETRY",
    "profile": "USER_PROFILE",
}

MEDIA_SYSTEM_BY_PREFIX = {
    "account": "account_service",
    "search": "search_service",
    "data_flow": "integration_service",
    "analytics": "analytics_platform",
    "export": "export_service",
    "support": "support_platform",
    "backup": "backup_service",
    "audit": "security_service",
    "tombstone": "identity_service",
    "legal": "legal_service",
    "marketing": "marketing_platform",
    "order": "order_service",
    "email": "downstream_delivery_service",
    "cache": "cache_service",
    "telemetry": "analytics_platform",
    "profile": "account_service",
}


@dataclass
class DatasetBundle:
    root: Path
    store: RecordStore
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    evidence_file_count: int = 0
    loaded_evidence_count: int = 0
    skipped_multimodal: tuple[str, ...] = ()
    media_backends: tuple[str, ...] = ()
    media_processed_count: int = 0
    media_record_count: int = 0


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def enrich_enabled() -> bool:
    """Feature flag for linkage enrichments (E1 sniffing, trace pairing).

    Default off: behavior is byte-identical to the pre-enrichment baseline so
    A/B comparisons stay meaningful. Opt in with PRAMAANTRACE_ENRICH=1.
    """
    return os.environ.get("PRAMAANTRACE_ENRICH", "").strip().casefold() in {
        "1",
        "true",
        "yes",
    }


def _sniff_link_identifier(value: str) -> str | None:
    """Map a lookup/search-echo value to its identifier bucket by shape."""
    text = value.strip()
    if not text or text.casefold() in {"null", "none", "nan", "n/a", "unknown", "nil", "null;"}:
        return None
    if HASH_VALUE_PATTERN.fullmatch(text):
        return "email_hashes"
    if "@" in text:
        return "emails" if EMAIL_PATTERN.fullmatch(text) else None
    reference = USER_REF_VALUE_PATTERN.fullmatch(text)
    if reference:
        return (
            "user_ids"
            if text.casefold().startswith("user_")
            else "customer_references"
        )
    if PHONE_VALUE_PATTERN.fullmatch(text):
        return "phones"
    return None


def _canonical_readback_attributes(pairs: Mapping[str, str], line: str) -> dict[str, Any]:
    """Normalize readback-specific field shapes into canonical policy fields.

    Covers two generic readback shapes (no case-specific logic):

    * handover/list rows: ``- <ts> | <system> | <resource> | <type> | <status> | <subject>``
      whose status column states the observed record state.
    * lookup lines that already answer a restore-policy question with
      ``eligible=``/``deletion_block=`` pairs.

    Returns canonical attribute overrides; an empty dict leaves the record as
    parsed.
    """
    canonical: dict[str, Any] = {}
    row = PIPE_ROW_PATTERN.match(line)
    if row:
        _ts, system, resource, record_type, status, subject = row.groups()
        status = status.strip()
        record_type = record_type.upper()
        category = PIPE_TYPE_CATEGORY.get(record_type)
        if category:
            canonical["data_category"] = category
        canonical["readback_status"] = status
        canonical["_pipe_resource"] = resource
        if system:
            canonical["system_id"] = system.strip()
        if subject and not subject.strip().casefold().startswith("no direct"):
            canonical["subject_reference"] = subject.strip()
        if status == "NOT_FOUND":
            canonical["status_code"] = "404"
        if record_type == "BACKUP_ARCHIVE":
            if status in {"ACTIVE", "RESTORABLE"}:
                canonical["restore_allowed"] = True
            elif status in {"BLOCKED", "RESTORE_BLOCKED"}:
                canonical["restore_allowed"] = False
        elif record_type == "DATA_FLOW":
            if status == "ACTIVE":
                canonical["enabled"] = True
            elif status in {"DISABLED", "INACTIVE", "STOPPED"}:
                canonical["enabled"] = False
        elif record_type in {"SUPPORT_MESSAGE", "SUPPORT_ATTACHMENT"}:
            if status == "IDENTIFIABLE":
                canonical["identifiable"] = True
            elif status == "REDACTED":
                canonical["redacted"] = True
        elif record_type == "SECURITY_AUDIT_LOG" and status == "FOUND":
            canonical["integrity_check"] = "passed"
        return canonical

    if "eligible" in pairs or "deletion_block" in pairs:
        if "eligible" in pairs:
            eligible = _truthy(pairs.get("eligible", ""))
            block = (
                _truthy(pairs.get("deletion_block", ""))
                if "deletion_block" in pairs
                else False
            )
            canonical["restore_allowed"] = bool(eligible) and not block
        return canonical
    return {}


def _truthy(value: str) -> bool:
    return str(value).strip().casefold() in {
        "1",
        "true",
        "yes",
        "enabled",
        "allowed",
        "active",
    }


def flatten_values(value: Any, key: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(value, Mapping):
        for child_key, child_value in value.items():
            yield from flatten_values(child_value, str(child_key))
    elif isinstance(value, list):
        for child in value:
            yield from flatten_values(child, key)
    elif value is not None:
        yield key.casefold(), value


def extract_identifiers(attributes: Mapping[str, Any], raw_text: str = "") -> dict[str, tuple[str, ...]]:
    found: dict[str, set[str]] = {}
    for key, value in flatten_values(attributes):
        destination = IDENTIFIER_KEYS.get(key)
        if not destination and enrich_enabled() and str(key) in LINK_IDENTIFIER_KEYS:
            destination = _sniff_link_identifier(str(value))
        if destination and isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text and text.casefold() not in {"null", "none", "nan", "n/a", "unknown"}:
                found.setdefault(destination, set()).add(text)
    for email in EMAIL_PATTERN.findall(raw_text):
        found.setdefault("emails", set()).add(email)
    for value in HASH_PATTERN.findall(raw_text):
        found.setdefault("email_hashes", set()).add(value.casefold())
    return {key: tuple(sorted(values, key=str.casefold)) for key, values in sorted(found.items())}


def infer_system(collection: str | None, record: Mapping[str, Any], inherited: str | None) -> str:
    for key in ("system_id", "origin_system", "data_store", "service", "system"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().strip('"')
    if inherited:
        return inherited
    if collection:
        system = COLLECTION_SYSTEM.get(collection.casefold())
        if system:
            return system
    raise ValueError(f"unable to map evidence record to a system (collection={collection!r})")


def infer_category(
    collection: str | None, record: Mapping[str, Any], system_id: str
) -> str:
    for key in ("data_category", "category", "record_type"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
            if normalized in {
                "USER_PROFILE",
                "SECONDARY_IDENTIFIER",
                "SEARCH_INDEX_ENTRY",
                "CACHE_ENTRY",
                "SUPPORT_MESSAGE",
                "SUPPORT_ATTACHMENT",
                "ANALYTICS_PROFILE",
                "PRODUCT_TELEMETRY",
                "USER_EXPORT",
                "MARKETING_PROFILE",
                "EMAIL_DELIVERY_LOG",
                "SECURITY_AUDIT_LOG",
                "LEGAL_HOLD_RECORD",
                "BACKUP_ARCHIVE",
                "ACCOUNT_TOMBSTONE",
                "DATA_FLOW",
            }:
                return normalized
    if collection:
        category = COLLECTION_CATEGORY.get(collection.casefold())
        if category:
            return category
    system_defaults = {
        "account_service": "USER_PROFILE",
        "analytics_platform": "ANALYTICS_PROFILE",
        "backup_service": "BACKUP_ARCHIVE",
        "export_service": "USER_EXPORT",
        "identity_service": "ACCOUNT_TOMBSTONE",
        "integration_service": "DATA_FLOW",
        "search_service": "SEARCH_INDEX_ENTRY",
        "security_service": "SECURITY_AUDIT_LOG",
        "support_platform": "SUPPORT_MESSAGE",
        "legal_service": "LEGAL_HOLD_RECORD",
        "search_index_service": "SEARCH_INDEX_ENTRY",
        "support_replica": "SUPPORT_MESSAGE",
        "downstream_delivery_service": "EMAIL_DELIVERY_LOG",
    }
    return system_defaults.get(system_id, "OPERATIONAL_EVENT")


def system_from_resource(resource_id: str) -> str | None:
    prefix = resource_id.casefold().split("_", 1)[0]
    return {
        "account": "account_service",
        "analytics": "analytics_platform",
        "audit": "security_service",
        "backup": "backup_service",
        "data": "integration_service",
        "export": "export_service",
        "legal": "legal_service",
        "search": "search_service",
        "support": "support_platform",
        "tombstone": "identity_service",
    }.get(prefix)


def topology_for_sql(path: Path, table: str) -> str:
    name = path.name.casefold()
    table_name = table.casefold()
    if "failover" in table_name:
        return "failover_replica"
    if "read_replica" in table_name:
        return "read_replica"
    if "replica_ap_south" in table_name:
        return "regional_replica_ap_south"
    if "replica_eu_west" in table_name:
        return "regional_replica_eu_west"
    if "reporting_replica" in table_name:
        return "reporting_replica"
    if table_name.endswith("_primary") or table_name == "customer_data_primary":
        return "primary"
    if "failover" in name:
        return "failover_replica"
    if "read_replica" in name:
        return "read_replica"
    if "regional_replicas" in name:
        return "regional_replica"
    if "reporting_replica" in name:
        return "reporting_replica"
    if "primary" in name:
        return "primary"
    if "inventory" in name:
        return "inventory_snapshot"
    return "single_system_snapshot"


def normalize_sql_file(
    store: RecordStore, evidence_id: str, captured_at: str, path: Path
) -> int:
    text = path.read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    count = 0
    try:
        connection.executescript(text)
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        if not tables:
            raise ValueError(f"{evidence_id}: SQL snapshot contains no tables")
        for table in tables:
            adapter = SYSTEM_BY_TABLE.get(table)
            if adapter is None:
                raise ValueError(f"{evidence_id}: unmapped SQL table {table!r}")
            system_id, category = adapter
            columns = [
                row[1]
                for row in connection.execute(f'PRAGMA table_info("{table}")')
            ]
            if table in SQL_TABLES_WITHOUT_RECORDS:
                continue
            if "resource_id" not in columns:
                raise ValueError(
                    f"{evidence_id}: mapped SQL table {table!r} lacks resource_id"
                )
            if table.startswith("customer_data_"):
                for record_system, collection in connection.execute(
                    f'SELECT DISTINCT origin_system, collection_name FROM "{table}" '
                    "ORDER BY origin_system, collection_name"
                ):
                    store.add_scope(
                        RecordScope(
                            capture_id=evidence_id,
                            captured_at=captured_at,
                            topology=topology_for_sql(path, table),
                            system_id=str(record_system),
                            category=COLLECTION_CATEGORY.get(
                                str(collection).casefold(), "OPERATIONAL_EVENT"
                            ),
                            complete_listing=True,
                        )
                    )
            elif system_id is not None and category is not None:
                store.add_scope(
                    RecordScope(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology=topology_for_sql(path, table),
                        system_id=system_id,
                        category=category,
                        complete_listing=True,
                    )
                )
            for values in connection.execute(f'SELECT * FROM "{table}"'):
                attributes = dict(zip(columns, values))
                if table.startswith("customer_data_"):
                    try:
                        record_attributes = json.loads(attributes["record_json"])
                    except (TypeError, json.JSONDecodeError) as exc:
                        raise ValueError(
                            f"{evidence_id}: invalid record_json in {table!r}"
                        ) from exc
                    if not isinstance(record_attributes, dict):
                        raise ValueError(
                            f"{evidence_id}: non-object record_json in {table!r}"
                        )
                    collection = str(attributes["collection_name"])
                    record_system = str(attributes["origin_system"])
                    record_category = infer_category(
                        collection, record_attributes, record_system
                    )
                    resource_id = str(
                        record_attributes.get("resource_id")
                        or attributes["resource_id"]
                    )
                    normalized_attributes = {
                        **record_attributes,
                        "_origin_system": record_system,
                        "_collection": collection,
                        "_snapshot_table": table,
                        "_snapshot_resource_id": attributes["resource_id"],
                    }
                    record_system_id = record_system
                else:
                    if system_id is None or category is None:
                        raise ValueError(
                            f"{evidence_id}: no SQL adapter for table {table!r}"
                        )
                    record_system_id = system_id
                    record_category = category
                    resource_id = str(attributes["resource_id"])
                    normalized_attributes = attributes
                store.add_record(
                    NormalizedRecord(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology=topology_for_sql(path, table),
                        system_id=record_system_id,
                        resource_id=resource_id,
                        category=record_category,
                        identifiers=extract_identifiers(normalized_attributes),
                        attributes=normalized_attributes,
                    )
                )
                count += 1
        return count
    finally:
        connection.close()


def _json_record_context(
    value: Any,
    *,
    evidence_id: str,
    captured_at: str,
    store: RecordStore,
    inherited_system: str | None = None,
    inherited_collection: str | None = None,
    inherited_topology: str = "json_record_snapshot",
    parent_key: str = "",
) -> int:
    count = 0
    if isinstance(value, dict):
        current_system = inherited_system
        current_collection = inherited_collection
        current_topology = inherited_topology
        for key in ("system_id", "origin_system", "data_store", "service"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                current_system = item.strip()
                break
        for key in ("collection", "collection_name"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                current_collection = item.strip()
                break

        if parent_key == "service_exports":
            # The child keys under service_exports are the source system IDs.
            pass
        if "resource_id" in value:
            system_id = infer_system(current_collection, value, current_system)
            category = infer_category(current_collection, value, system_id)
            resource_id = str(value["resource_id"]).strip()
            if resource_id:
                store.add_record(
                    NormalizedRecord(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology=current_topology,
                        system_id=system_id,
                        resource_id=resource_id,
                        category=category,
                        identifiers=extract_identifiers(value),
                        attributes=value,
                    )
                )
                count += 1

        for key, child in value.items():
            child_system = current_system
            child_collection = current_collection
            child_topology = current_topology
            if parent_key == "service_exports":
                child_system = str(key)
                child_topology = "json_service_export"
            if key in COLLECTION_CATEGORY:
                child_collection = key
                child_system = child_system or COLLECTION_SYSTEM.get(key)
                if key == "profile_lookups":
                    child_topology = "service_readback"
            elif key in ("index_queries", "documents") and child_collection is None:
                child_collection = "customer_search_documents"
            if key == "records" and child_system and child_collection:
                store.add_scope(
                    RecordScope(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology=current_topology,
                        system_id=child_system,
                        category=COLLECTION_CATEGORY.get(
                            child_collection.casefold(), "OPERATIONAL_EVENT"
                        ),
                        complete_listing=current_topology
                        in {"json_snapshot_bundle", "json_record_snapshot"},
                    )
                )
            elif (
                key in COLLECTION_CATEGORY
                and isinstance(child, (list, dict))
                and child_system
            ):
                store.add_scope(
                    RecordScope(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology=child_topology,
                        system_id=child_system,
                        category=COLLECTION_CATEGORY[key],
                        complete_listing=child_topology
                        in {"json_snapshot_bundle", "json_record_snapshot"},
                    )
                )
            count += _json_record_context(
                child,
                evidence_id=evidence_id,
                captured_at=captured_at,
                store=store,
                inherited_system=child_system,
                inherited_collection=child_collection,
                inherited_topology=child_topology,
                parent_key=str(key),
            )
    elif isinstance(value, list):
        for child in value:
            count += _json_record_context(
                child,
                evidence_id=evidence_id,
                captured_at=captured_at,
                store=store,
                inherited_system=inherited_system,
                inherited_collection=inherited_collection,
                inherited_topology=inherited_topology,
                parent_key=parent_key,
            )
    return count


def normalize_json_file(
    store: RecordStore, evidence_id: str, captured_at: str, path: Path
) -> int:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{evidence_id}: invalid JSON in {path.name}") from exc
    return _json_record_context(
        document,
        evidence_id=evidence_id,
        captured_at=captured_at,
        store=store,
        inherited_topology=(
            "json_snapshot_bundle"
            if isinstance(document, dict) and "snapshots" in document
            else "json_service_export"
            if isinstance(document, dict) and "service_exports" in document
            else "json_record_snapshot"
        ),
    )


def normalize_text_file(
    store: RecordStore, evidence_id: str, captured_at: str, path: Path
) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    return normalize_text_content(
        store,
        evidence_id=evidence_id,
        captured_at=captured_at,
        file_path=path.as_posix(),
        text=text,
    )


def normalize_text_content(
    store: RecordStore,
    *,
    evidence_id: str,
    captured_at: str,
    file_path: str,
    text: str,
) -> int:
    store.add_text(
        CapturedText(
            capture_id=evidence_id,
            captured_at=captured_at,
            file_path=file_path,
            text=text,
        )
    )
    count = 0
    lines = text.splitlines()
    parsed: list[tuple[int, str, dict[str, str]]] = []
    for line_no, line in enumerate(lines, start=1):
        pairs = {
            key.casefold(): next((value for value in values if value), "")
            for key, *values in KV_PATTERN.findall(line)
        }
        parsed.append((line_no, line, pairs))

    # Trace pairing: request rows of one operation often split the resource id
    # and the looking-up subject across consecutive lines with a shared
    # trace_id (e.g. lookup.started carries lookup_key, query.completed carries
    # resource_id). Join them per trace so the subject links to the resource.
    trace_links: dict[str, tuple[str, str]] = {}
    if enrich_enabled():
        seen_trace_values: dict[str, set[tuple[str, str]]] = {}
        for _line_no, line, pairs in parsed:
            trace_id = str(pairs.get("trace_id", "")).strip()
            if not trace_id:
                continue
            for key in LINK_IDENTIFIER_KEYS:
                value = pairs.get(key, "")
                if value and _sniff_link_identifier(value):
                    seen_trace_values.setdefault(trace_id, set()).add((key, value))
        for trace_id, entries in seen_trace_values.items():
            keys = {key for key, _ in entries}
            values = {value for _, value in entries}
            if len(keys) == 1 and len(values) == 1:
                key = next(iter(keys))
                value = next(iter(values))
                trace_links[trace_id] = (key, value)

    for line_no, line, pairs in parsed:
        effective_line = line
        resource_match = RESOURCE_PATTERN.search(line)
        resource_id = (
            pairs.get("resource_id")
            or pairs.get("resource")
            or pairs.get("record_id")
            or pairs.get("object_id")
            or (resource_match.group(1) if resource_match else "")
        )
        canonical: dict[str, Any] = {}
        if enrich_enabled():
            trace_id = str(pairs.get("trace_id", "")).strip()
            link = trace_links.get(trace_id)
            if link and not pairs.get(link[0]):
                # Merge the partner line's subject identifier into this line's
                # attributes so extract_identifiers can see it, and extend the
                # scanned text so email/hash extraction applies as well.
                key, value = link
                pairs = {**pairs, key: value}
                effective_line = f"{line} {key}={value}"
            canonical = _canonical_readback_attributes(pairs, line)
            if canonical:
                resource_id = resource_id or str(canonical.get("_pipe_resource", ""))
                pairs = {**pairs, **canonical}
        if not resource_id:
            continue
        resource_id = str(resource_id).strip().strip("\\\"'")
        system_id = (
            pairs.get("service")
            or pairs.get("system_id")
            or pairs.get("system")
            or pairs.get("source_system")
            or pairs.get("target_system")
            or pairs.get("destination")
            or system_from_resource(resource_id)
            or "unclassified_text"
        ).strip().strip("\\\"'")
        attributes: dict[str, Any] = {
            **pairs,
            "line_no": line_no,
            "raw_line": line,
        }
        collection = pairs.get("collection") or pairs.get("data_category")
        category = infer_category(collection, attributes, system_id)
        store.add_record(
            NormalizedRecord(
                capture_id=evidence_id,
                captured_at=captured_at,
                topology="text_event",
                system_id=system_id,
                resource_id=resource_id,
                category=category,
                identifiers=extract_identifiers(attributes, effective_line),
                attributes=attributes,
            )
        )
        count += 1
    return count


def _cache_directory() -> Path:
    configured = os.environ.get("PRAMAANTRACE_MEDIA_CACHE")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "pramaantrace" / "media"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "pramaantrace" / "media"


def _eligible_media_entries(
    manifest: Iterable[Mapping[str, str]],
    request_rows: Iterable[Mapping[str, str]],
) -> list[Mapping[str, str]]:
    cutoffs = [
        parse_timestamp(row["audit_at"])
        for row in request_rows
        if row.get("audit_at")
    ]
    if not cutoffs:
        return []
    latest_cutoff = max(cutoffs)
    return [
        entry
        for entry in manifest
        if Path(entry["file_path"]).suffix.casefold()
        in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".pdf"}
        and parse_timestamp(entry["captured_at"]) <= latest_cutoff
    ]


def _vision_ocr(assets: list[Path]) -> tuple[dict[str, dict[str, Any]], str]:
    if not assets:
        return {}, ""
    if sys.platform == "darwin":
        script = Path(__file__).with_name("vision_ocr.swift")
        executable = os.environ.get("SWIFT_EXECUTABLE", "swift")
        if shutil_which(executable):
            try:
                completed = subprocess.run(
                    [executable, str(script), *map(str, assets)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                if completed.returncode == 0:
                    results = json.loads(completed.stdout)
                    return {
                        str(Path(item["path"]).resolve()): {
                            "text": str(item.get("text", "")),
                            "lines": item.get("lines", []),
                        }
                        for item in results
                    }, "Apple Vision"
            except (OSError, json.JSONDecodeError, KeyError, TypeError):
                # Vision can be unavailable even when Swift is installed.
                # Try the portable backend before marking media unprocessed.
                pass

    return _tesseract_ocr(assets)


def _tesseract_ocr(assets: list[Path]) -> tuple[dict[str, dict[str, Any]], str]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {}, ""
    try:
        pytesseract.get_tesseract_version()
    except Exception:
        return {}, ""

    pdfium = None
    if any(path.suffix.casefold() == ".pdf" for path in assets):
        try:
            import pypdfium2 as pdfium_module

            pdfium = pdfium_module
        except ImportError:
            pass

    extracted: dict[str, dict[str, Any]] = {}
    for path in assets:
        try:
            if path.suffix.casefold() == ".pdf":
                if pdfium is None:
                    continue
                document = pdfium.PdfDocument(str(path))
                page_text = []
                for page in document:
                    bitmap = page.render(scale=2)
                    with bitmap.to_pil() as image:
                        page_text.append(pytesseract.image_to_string(image))
                close = getattr(document, "close", None)
                if callable(close):
                    close()
                text = "\n".join(page_text).strip()
            else:
                with Image.open(path) as image:
                    text = pytesseract.image_to_string(image)
            extracted[str(path.resolve())] = {"text": text, "lines": []}
        except Exception:
            # Keep other eligible assets usable. The caller records each
            # unprocessed file and reports partial media coverage.
            continue
    return extracted, "Tesseract" if extracted else ""


def shutil_which(executable: str) -> str | None:
    # Kept small and local so the loader has no optional third-party dependency.
    from shutil import which

    return which(executable)


def _pdf_text(path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    reader = PdfReader(path)
    return "\n".join(page.extract_text() or "" for page in reader.pages).strip()


def _media_resource_records(
    store: RecordStore,
    *,
    evidence_id: str,
    captured_at: str,
    text: str,
    lines: Iterable[Mapping[str, Any]] = (),
) -> int:
    """Normalize strongly associated resource/identifier mentions from OCR text.

    A media-derived record is emitted only when a resource token is close to
    at least one explicit email or stable user reference in the same artifact.
    The complete OCR text is also retained as gated evidence text.
    """
    line_list = [
        line
        for line in lines
        if isinstance(line, Mapping) and isinstance(line.get("text"), str)
    ]
    located_resources: list[dict[str, Any]] = []
    located_identifiers: list[dict[str, Any]] = []
    if line_list:
        for line in line_list:
            line_text = str(line["text"])
            x = float(line.get("x", 0.0))
            y = float(line.get("y", 0.0))
            width = float(line.get("width", 0.0))
            height = float(line.get("height", 0.0))
            for match in MEDIA_RESOURCE_PATTERN.finditer(line_text):
                located_resources.append(
                    {
                        "resource_id": match.group(),
                        "x": x + width / 2,
                        "y": y + height / 2,
                        "line": line_text,
                    }
                )
            for pattern, key in (
                (MEDIA_EMAIL_PATTERN, "emails"),
                (MEDIA_USER_PATTERN, "user_ids"),
            ):
                for match in pattern.finditer(line_text):
                    located_identifiers.append(
                        {
                            "kind": key,
                            "value": match.group().casefold(),
                            "x": x + width / 2,
                            "y": y + height / 2,
                            "line": line_text,
                        }
                    )
        resource_groups: dict[str, list[dict[str, Any]]] = {}
        for occurrence in located_resources:
            resource_groups.setdefault(
                occurrence["resource_id"].casefold(), []
            ).append(occurrence)
        resources = [
            min(
                occurrences,
                key=lambda occurrence: min(
                    (
                        abs(candidate["y"] - occurrence["y"])
                        + 0.12 * abs(candidate["x"] - occurrence["x"])
                        for candidate in located_identifiers
                    ),
                    default=float("inf"),
                ),
            )
            for _, occurrences in sorted(resource_groups.items())
        ]
    else:
        emails = list(MEDIA_EMAIL_PATTERN.finditer(text))
        users = list(MEDIA_USER_PATTERN.finditer(text))
        identifiers = sorted(
            [
                {
                    "position": match.start(),
                    "kind": "emails",
                    "value": match.group().casefold(),
                }
                for match in emails
            ]
            + [
                {
                    "position": match.start(),
                    "kind": "user_ids",
                    "value": match.group().casefold(),
                }
                for match in users
            ],
            key=lambda item: item["position"],
        )
        resources = [
            {
                "resource_id": match.group(),
                "position": match.start(),
            }
            for match in MEDIA_RESOURCE_PATTERN.finditer(text)
        ]
    count = 0
    seen_resources = set()
    for occurrence in resources:
        resource_id = occurrence["resource_id"]
        if resource_id.casefold() in seen_resources:
            continue
        seen_resources.add(resource_id.casefold())
        if line_list:
            resource_x = occurrence["x"]
            resource_y = occurrence["y"]
            if not located_identifiers:
                continue
            scores = [
                abs(candidate["y"] - resource_y)
                + 0.12 * abs(candidate["x"] - resource_x)
                for candidate in located_identifiers
            ]
            best_score = min(scores)
            if best_score > 0.08:
                continue
            nearest_items = [
                candidate
                for candidate, score in zip(located_identifiers, scores)
                if score <= best_score + 0.004
            ]
            # Use the table row around the resource as evidence context; this
            # avoids joining adjacent users merely because they occur on one
            # screenshot.
            context = "\n".join(
                str(line["text"])
                for line in line_list
                if abs(
                    float(line.get("y", 0.0))
                    + float(line.get("height", 0.0)) / 2
                    - resource_y
                )
                <= 0.018
            )
            local_identifiers = {
                key: tuple(
                    sorted(
                        {
                            item["value"]
                            for item in nearest_items
                            if item["kind"] == key
                        }
                    )
                )
                for key in ("emails", "user_ids")
            }
        else:
            nearest = min(
                identifiers,
                key=lambda item: abs(item["position"] - occurrence["position"]),
                default=None,
            )
            # Avoid inferring membership from a whole page when unrelated rows
            # are listed together. Text proximity is only a fallback when the
            # extractor does not expose layout coordinates.
            if (
                nearest is None
                or abs(nearest["position"] - occurrence["position"]) > 300
            ):
                continue
            left = max(
                0,
                min(occurrence["position"], nearest["position"]) - 120,
            )
            right = min(
                len(text),
                max(
                    occurrence["position"] + len(resource_id),
                    nearest["position"] + len(nearest["value"]),
                )
                + 120,
            )
            context = text[left:right]
            local_identifiers = {
                key: tuple(
                    sorted(
                        {
                            item["value"]
                            for item in identifiers
                            if item["kind"] == key
                            and left <= item["position"] < right
                        }
                    )
                )
                for key in ("emails", "user_ids")
            }
        prefix = next(
            (
                candidate
                for candidate in sorted(
                    MEDIA_CATEGORY_BY_PREFIX, key=len, reverse=True
                )
                if resource_id.casefold().startswith(candidate + "_")
            ),
            "",
        )
        category = MEDIA_CATEGORY_BY_PREFIX.get(prefix)
        system_id = MEDIA_SYSTEM_BY_PREFIX.get(prefix)
        lowered_document = text.casefold()
        if (
            prefix == "support"
            and "attachment" in lowered_document
            and re.search(r"\bfile\s+[\w .-]+\.(?:pdf|png|jpe?g)\b", text, re.I)
            and re.search(r"\buploader\s+customer\b", text, re.I)
        ):
            category = "SUPPORT_ATTACHMENT"
        if not category or not system_id:
            continue
        attrs: dict[str, Any] = {
            "resource_id": resource_id,
            "media_context": context,
            **{
                key[:-1] if key.endswith("s") else key: values[0]
                for key, values in local_identifiers.items()
                if values
            },
        }
        if category == "SUPPORT_ATTACHMENT":
            owner_values = local_identifiers.get("emails") or local_identifiers.get(
                "user_ids"
            )
            if owner_values:
                attrs["uploaded_by"] = owner_values[0]
            attrs["shared"] = bool(
                re.search(r"\bshared\s+(?:with|among|by)\b", text, re.I)
            )
        if category == "DATA_FLOW":
            snippet = context.casefold()
            if any(token in snippet for token in ("continuous sync", "continuous", "enabled", "active")):
                attrs["enabled"] = True
            elif any(token in snippet for token in ("disabled", "paused", "inactive", "stopped")):
                attrs["enabled"] = False
        elif category == "BACKUP_ARCHIVE":
            snippet = context.casefold()
            if any(token in snippet for token in ("restore allowed: yes", "restore permitted: yes", "restore access: allowed")):
                attrs["restore_allowed"] = True
            elif any(token in snippet for token in ("restore blocked", "restore allowed: no", "restore access: blocked")):
                attrs["restore_allowed"] = False
        store.add_record(
            NormalizedRecord(
                capture_id=evidence_id,
                captured_at=captured_at,
                topology="media_observation",
                system_id=system_id,
                resource_id=resource_id,
                category=category,
                identifiers={
                    key: values for key, values in local_identifiers.items() if values
                },
                attributes=attrs,
            )
        )
        count += 1
    return count


def load_media_evidence(
    *,
    dataset: Path,
    manifest: Iterable[Mapping[str, str]],
    request_rows: Iterable[Mapping[str, str]],
    store: RecordStore,
    cache_dir: Path | None = None,
) -> tuple[int, int, tuple[str, ...], tuple[str, ...]]:
    """Read only cutoff-eligible media, caching extracted text outside the repo."""
    entries = _eligible_media_entries(manifest, request_rows)
    if not entries:
        return 0, 0, (), ()
    disable_cache = os.environ.get(
        "PRAMAANTRACE_DISABLE_MEDIA_CACHE", ""
    ).strip().casefold() in {"1", "true", "yes"}
    cache = None if disable_cache else (cache_dir or _cache_directory())
    if cache is not None:
        cache.mkdir(parents=True, exist_ok=True)

    uncached: list[tuple[Mapping[str, str], Path, str, Path]] = []
    text_by_id: dict[
        str, tuple[str, str, Path, list[dict[str, Any]]]
    ] = {}
    for entry in sorted(entries, key=lambda row: row["file_id"]):
        source = (dataset / entry["file_path"]).resolve()
        if dataset.resolve() not in source.parents:
            raise ValueError(f"{entry['file_id']}: media path escapes dataset/")
        if not source.is_file():
            raise FileNotFoundError(f"{entry['file_id']}: missing media {source.name}")
        # Files are opened only after the manifest time is known eligible for
        # at least one requested audit cutoff.
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        cache_key = hashlib.sha256(
            f"pramaantrace-media-v{MEDIA_CACHE_VERSION}:{digest}".encode("ascii")
        ).hexdigest()
        cached_path = cache / f"{cache_key}.json" if cache is not None else None
        if cached_path is not None and cached_path.is_file():
            try:
                cached = json.loads(cached_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                cached = {}
            if (
                cached.get("sha256") == digest
                and cached.get("cache_version") == MEDIA_CACHE_VERSION
                and isinstance(cached.get("text"), str)
            ):
                text_by_id[entry["file_id"]] = (
                    cached["text"],
                    cached.get("backend", "cache"),
                    source,
                    cached.get("lines", []),
                )
                continue
        uncached.append((entry, source, digest, cached_path))

    pending_ocr: list[Path] = []
    for item in uncached:
        entry, source, digest, cached_path = item
        if source.suffix.casefold() == ".pdf":
            extracted = _pdf_text(source)
            if extracted.strip():
                text_by_id[entry["file_id"]] = (extracted, "pypdf", source, [])
                if cached_path is not None:
                    cache_payload = {
                        "sha256": digest,
                        "cache_version": MEDIA_CACHE_VERSION,
                        "backend": "pypdf",
                        "text": extracted,
                        "lines": [],
                    }
                    cached_path.write_text(
                        json.dumps(
                            cache_payload, ensure_ascii=False, sort_keys=True
                        ),
                        encoding="utf-8",
                    )
                continue
        pending_ocr.append(source)

    ocr_results, ocr_backend = (
        _vision_ocr(pending_ocr) if pending_ocr else ({}, "")
    )
    unavailable = []
    for item in uncached:
        entry, source, digest, cached_path = item
        key = str(source.resolve())
        if (
            entry["file_id"] in text_by_id
            and source.suffix.casefold() == ".pdf"
        ):
            continue
        ocr_result = ocr_results.get(key)
        if ocr_result is None:
            unavailable.append(entry["file_id"])
            continue
        text = str(ocr_result.get("text", ""))
        lines = list(ocr_result.get("lines", []))
        text_by_id[entry["file_id"]] = (text, ocr_backend, source, lines)
        if cached_path is not None:
            cached_path.write_text(
                json.dumps(
                    {
                        "sha256": digest,
                        "cache_version": MEDIA_CACHE_VERSION,
                        "backend": ocr_backend,
                        "text": text,
                        "lines": lines,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

    record_count = 0
    backends = set()
    for entry in sorted(entries, key=lambda row: row["file_id"]):
        result = text_by_id.get(entry["file_id"])
        if result is None:
            continue
        text, backend, source, lines = result
        backends.add(backend)
        store.add_text(
            CapturedText(
                capture_id=entry["file_id"],
                captured_at=entry["captured_at"],
                file_path=entry["file_path"],
                text=text,
            )
        )
        record_count += _media_resource_records(
            store,
            evidence_id=entry["file_id"],
            captured_at=entry["captured_at"],
            text=text,
            lines=lines,
        )
    return (
        record_count,
        len(text_by_id),
        tuple(sorted(unavailable)),
        tuple(sorted(backends)),
    )


def load_dataset(
    root: str | Path,
    *,
    media_request_rows: Iterable[Mapping[str, str]] | None = None,
    include_media: bool = True,
) -> DatasetBundle:
    root = Path(root).resolve()
    dataset = root / "dataset"
    if not dataset.is_dir():
        raise FileNotFoundError(f"dataset directory not found: {dataset}")

    input_csv_names = (
        "deletion_requests.csv",
        "deletion_rules.csv",
        "evidence_files.csv",
        "sample_deletion_requests.csv",
        "system_activity.csv",
        "user_audit_log.csv",
        "user_identities.csv",
    )
    tables = {
        name: read_csv_rows(dataset / name)
        for name in input_csv_names
    }
    manifest = tables["evidence_files.csv"]
    store = RecordStore()
    loaded_count = 0
    skipped = []

    for entry in sorted(manifest, key=lambda row: row["file_id"]):
        relative = Path(entry["file_path"])
        path = (dataset / relative).resolve()
        if dataset.resolve() not in path.parents:
            raise ValueError(f"{entry['file_id']}: evidence path escapes dataset/")
        if not path.is_file():
            raise FileNotFoundError(f"{entry['file_id']}: missing evidence {relative}")
        captured_at = entry["captured_at"]
        parse_timestamp(captured_at)
        suffix = path.suffix.casefold()
        if suffix == ".sql":
            normalize_sql_file(store, entry["file_id"], captured_at, path)
        elif suffix == ".json":
            normalize_json_file(store, entry["file_id"], captured_at, path)
        elif suffix in {".log", ".txt"}:
            normalize_text_file(store, entry["file_id"], captured_at, path)
            loaded_count += 1
        elif suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".pdf"}:
            continue
        else:
            raise ValueError(
                f"{entry['file_id']}: unsupported evidence file type {suffix!r}"
            )
        if suffix in {".sql", ".json"}:
            loaded_count += 1

    media_requests = (
        list(media_request_rows)
        if media_request_rows is not None
        else tables["deletion_requests.csv"]
    )
    if include_media:
        media_record_count, media_processed_count, skipped_media, media_backends = load_media_evidence(
            dataset=dataset,
            manifest=manifest,
            request_rows=media_requests,
            store=store,
        )
    else:
        media_record_count, media_processed_count = 0, 0
        skipped_media, media_backends = (), ()
    skipped.extend(skipped_media)
    return DatasetBundle(
        root=root,
        store=store,
        tables=tables,
        evidence_file_count=len(manifest),
        loaded_evidence_count=loaded_count,
        skipped_multimodal=tuple(sorted(skipped)),
        media_backends=media_backends,
        media_processed_count=media_processed_count,
        media_record_count=media_record_count,
    )
