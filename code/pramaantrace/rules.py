"""Data-driven deletion-policy application."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable, Mapping

from .identity import normalize_phone
from .loader import read_csv_rows
from .store import parse_timestamp


@dataclass(frozen=True)
class Rule:
    rule_id: str
    data_category: str
    condition: str
    required_action: str


class RuleEngine:
    def __init__(self, rows: Iterable[Mapping[str, str]]) -> None:
        self._rules = {
            row["data_category"]: Rule(
                row["rule_id"],
                row["data_category"],
                row["condition"],
                row["required_action"],
            )
            for row in rows
        }

    @classmethod
    def from_dataset(cls, root: str) -> "RuleEngine":
        from pathlib import Path

        return cls(read_csv_rows(Path(root) / "dataset" / "deletion_rules.csv"))

    def rule_for(self, category: str) -> Rule | None:
        return self._rules.get(category)

    def disposition(
        self,
        category: str,
        attributes: Mapping[str, Any],
        *,
        audit_at: str,
        identity_values: Iterable[str] = (),
    ) -> str | None:
        rule = self.rule_for(category)
        if rule is None:
            return None
        action = rule.required_action
        folded = {
            str(value).strip().casefold()
            for value in identity_values
            if str(value).strip()
        }

        if category == "SUPPORT_ATTACHMENT":
            owner = str(attributes.get("uploaded_by", "")).strip().casefold()
            shared = bool(attributes.get("shared") or attributes.get("shared_with"))
            # Delete only when ownership is explicitly attributable to this subject.
            return "DELETE" if owner and owner in folded and not shared else "RETAIN"

        if category == "SECURITY_AUDIT_LOG":
            retention = (
                attributes.get("retention_until")
                or attributes.get("retention_until_at")
            )
            if not retention:
                return "RETAIN"
            return (
                "RETAIN"
                if parse_timestamp(str(retention)) >= parse_timestamp(audit_at)
                else "DELETE"
            )

        if category == "LEGAL_HOLD_RECORD":
            active = attributes.get("legal_hold") or attributes.get("hold_active")
            if isinstance(active, str):
                active = active.strip().casefold() in {"true", "1", "yes", "active"}
            retained_until = attributes.get("retained_until")
            if active:
                return "RETAIN"
            if retained_until:
                return (
                    "RETAIN"
                    if parse_timestamp(str(retained_until)) >= parse_timestamp(audit_at)
                    else "DELETE"
                )
            return "RETAIN"

        return action

    @staticmethod
    def has_prohibited_identifiers(
        category: str,
        attributes: Mapping[str, Any],
        *,
        identity_values: Iterable[str],
    ) -> bool:
        values = {
            str(value).strip().casefold()
            for value in identity_values
            if str(value).strip()
        }

        def matches_subject(field: str, value: Any) -> bool:
            text = str(value).strip()
            if not text:
                return False
            if "phone" in field.casefold():
                return normalize_phone(text) in {
                    normalize_phone(item) for item in values
                }
            return text.casefold() in values

        if category == "ACCOUNT_TOMBSTONE":
            return any(
                attributes.get(field) not in (None, "")
                for field in ("name", "full_name", "email", "phone", "email_hash")
            ) or bool(
                attributes.get("customer_reference")
                and matches_subject(
                    "customer_reference", attributes["customer_reference"]
                )
            )
        if category == "ANALYTICS_PROFILE" or category == "PRODUCT_TELEMETRY":
            direct_fields = (
                "email",
                "email_hash",
                "phone",
                "user_id",
                "subject_reference",
                "customer_reference",
            )
            return any(
                matches_subject(field, attributes.get(field, ""))
                for field in direct_fields
                if attributes.get(field) not in (None, "")
            )
        if category == "SUPPORT_MESSAGE":
            direct_fields = (
                "email",
                "requester_email",
                "phone",
                "requester_phone",
                "email_hash",
                "subject_reference",
            )
            return any(
                matches_subject(field, attributes.get(field, ""))
                for field in direct_fields
                if attributes.get(field) not in (None, "")
            ) or any(
                token.casefold() in values
                for field in ("message_excerpt", "message_text")
                for token in re.findall(
                    r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
                    str(attributes.get(field, "")),
                    flags=re.I,
                )
            )
        return any(
            matches_subject(key, value)
            for key, value in attributes.items()
            if key.casefold()
            in {
                "email",
                "customer_email",
                "owner_email",
                "requester_email",
                "email_hash",
                "phone",
                "owner_phone",
                "requester_phone",
            }
            and value not in (None, "")
        )
