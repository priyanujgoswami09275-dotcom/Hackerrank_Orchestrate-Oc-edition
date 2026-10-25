"""Deterministic structured resource-reference extraction."""

from __future__ import annotations

import re
from typing import Any, Mapping

from .loader import flatten_values, system_from_resource


REFERENCE_SHAPE_PATTERN = re.compile(r"^[a-z][a-z_]*[a-z]_[0-9]+$")
REFERENCE_KEY_EXCLUSIONS = frozenset(
    {
        "resource_id",
        "trace_id",
        "capture_id",
        "file_id",
        "evidence_id",
        "conn_id",
        "request_id",
    }
)


def referenced_resource_ids(
    attributes: Mapping[str, Any], *, own_resource_id: str
) -> set[str]:
    """Return shaped resource IDs explicitly present in structured attributes."""
    referenced: set[str] = set()
    for key, value in flatten_values(attributes):
        if key in REFERENCE_KEY_EXCLUSIONS:
            continue
        text = str(value).strip().strip("\\\"'")
        if not REFERENCE_SHAPE_PATTERN.fullmatch(text):
            continue
        if text == own_resource_id:
            continue
        if text.casefold().startswith(("user_", "customer_")):
            continue
        if system_from_resource(text) is None:
            continue
        referenced.add(text)
    return referenced
