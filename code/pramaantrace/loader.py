"""Load participant-visible structured evidence into the normalized store."""

from __future__ import annotations

import csv
import json
import re
import sqlite3
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

EMAIL_PATTERN = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
HASH_PATTERN = re.compile(r"\b[a-f0-9]{64}\b", re.I)
RESOURCE_PATTERN = re.compile(
    r"\b(?:resource_id|resource|record_id|object_id)\s*[=:]\s*['\"]?([A-Za-z][A-Za-z0-9_-]*_[A-Za-z0-9_-]+)",
    re.I,
)
KV_PATTERN = re.compile(
    r"""([A-Za-z][A-Za-z0-9_]*)=(?:"([^"]*)"|'([^']*)'|([^\s,]+))"""
)


@dataclass
class DatasetBundle:
    root: Path
    store: RecordStore
    tables: dict[str, list[dict[str, str]]] = field(default_factory=dict)
    evidence_file_count: int = 0
    loaded_evidence_count: int = 0
    skipped_multimodal: tuple[str, ...] = ()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


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
        if destination and isinstance(value, (str, int, float)):
            text = str(value).strip()
            if text:
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
    parent_key: str = "",
) -> int:
    count = 0
    if isinstance(value, dict):
        current_system = inherited_system
        current_collection = inherited_collection
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
                        topology="json_snapshot",
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
            if parent_key == "service_exports":
                child_system = str(key)
            if key in COLLECTION_CATEGORY:
                child_collection = key
                child_system = child_system or COLLECTION_SYSTEM.get(key)
            elif key in ("index_queries", "documents") and child_collection is None:
                child_collection = "customer_search_documents"
            if key == "records" and child_system and child_collection:
                store.add_scope(
                    RecordScope(
                        capture_id=evidence_id,
                        captured_at=captured_at,
                        topology="json_snapshot",
                        system_id=child_system,
                        category=COLLECTION_CATEGORY.get(
                            child_collection.casefold(), "OPERATIONAL_EVENT"
                        ),
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
                        topology="json_service_export",
                        system_id=child_system,
                        category=COLLECTION_CATEGORY[key],
                    )
                )
            count += _json_record_context(
                child,
                evidence_id=evidence_id,
                captured_at=captured_at,
                store=store,
                inherited_system=child_system,
                inherited_collection=child_collection,
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
    )


def normalize_text_file(
    store: RecordStore, evidence_id: str, captured_at: str, path: Path
) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    store.add_text(
        CapturedText(
            capture_id=evidence_id,
            captured_at=captured_at,
            file_path=path.as_posix(),
            text=text,
        )
    )
    count = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        pairs = {
            key.casefold(): next((value for value in values if value), "")
            for key, *values in KV_PATTERN.findall(line)
        }
        resource_match = RESOURCE_PATTERN.search(line)
        resource_id = (
            pairs.get("resource_id")
            or pairs.get("resource")
            or pairs.get("record_id")
            or pairs.get("object_id")
            or (resource_match.group(1) if resource_match else "")
        )
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
                identifiers=extract_identifiers(attributes, line),
                attributes=attributes,
            )
        )
        count += 1
    return count


def load_dataset(root: str | Path) -> DatasetBundle:
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
        elif suffix in {".png", ".jpg", ".jpeg", ".pdf"}:
            skipped.append(entry["file_id"])
        else:
            raise ValueError(
                f"{entry['file_id']}: unsupported evidence file type {suffix!r}"
            )
        if suffix in {".sql", ".json"}:
            loaded_count += 1

    return DatasetBundle(
        root=root,
        store=store,
        tables=tables,
        evidence_file_count=len(manifest),
        loaded_evidence_count=loaded_count,
        skipped_multimodal=tuple(sorted(skipped)),
    )
