from __future__ import annotations

from datetime import datetime
import importlib
from pathlib import Path
import sys
from typing import Any

import pytest

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.identity import ResolvedIdentity  # noqa: E402
from pramaantrace.rules import RuleEngine  # noqa: E402
from pramaantrace.store import CapturedText, NormalizedRecord, RecordStore  # noqa: E402

AUDIT_AT = "2026-09-15T12:00:00Z"
USER_ID = "user_subject"
EMAIL = "subject@example.test"


def _toolbox_type() -> Any:
    try:
        module = importlib.import_module("pramaantrace.agent.tools")
    except ImportError as exc:
        pytest.fail(f"missing investigator tools module: {exc}")
    return module


def _record(
    resource_id: str,
    captured_at: str,
    *,
    topology: str = "primary",
    capture_id: str = "evidence_linked",
) -> NormalizedRecord:
    return NormalizedRecord(
        capture_id=capture_id,
        captured_at=captured_at,
        topology=topology,
        system_id="account_service",
        resource_id=resource_id,
        category="USER_PROFILE",
        identifiers={"emails": (EMAIL,), "user_ids": (USER_ID,)},
        attributes={"email": EMAIL, "user_id": USER_ID, "display_name": "Subject"},
    )


@pytest.fixture
def toolbox_fixture() -> tuple[Any, RecordStore]:
    store = RecordStore()
    store.add_record(_record("profile_before", "2026-09-15T11:59:59Z"))
    store.add_record(_record("profile_at_cutoff", AUDIT_AT, topology="regional"))
    store.add_record(_record("profile_after_cutoff", "2026-09-15T12:00:01Z"))
    store.add_text(
        CapturedText(
            capture_id="evidence_linked",
            captured_at=AUDIT_AT,
            file_path="evidence/logs/linked.log",
            text="user_subject profile_ref=profile_at_cutoff",
        )
    )
    store.add_text(
        CapturedText(
            capture_id="evidence_future",
            captured_at="2026-09-15T12:00:01Z",
            file_path="evidence/logs/future.log",
            text="future evidence",
        )
    )
    identity = ResolvedIdentity(
        user_id=USER_ID,
        names=("Subject",),
        emails=(EMAIL,),
        email_hashes=("a" * 64,),
        phones=("15551234567",),
        customer_references=("customer_subject",),
    )
    activities = [
        {
            "activity_id": "activity-before",
            "event_time": "2026-09-15T11:59:59Z",
            "event_type": "DELETE_RECORD",
            "source_system": "account_service",
            "target_system": "",
            "resource_id": "profile_before",
            "reported_result": "SUCCESS",
            "details": f"delete request for {EMAIL}",
        },
        {
            "activity_id": "activity-at-cutoff",
            "event_time": AUDIT_AT,
            "event_type": "DELETE_RECORD",
            "source_system": "account_service",
            "target_system": "",
            "resource_id": "profile_at_cutoff",
            "reported_result": "SUCCESS",
            "details": f"delete request for {EMAIL}",
        },
        {
            "activity_id": "activity-after",
            "event_time": "2026-09-15T12:00:01Z",
            "event_type": "DELETE_RECORD",
            "source_system": "account_service",
            "target_system": "",
            "resource_id": "profile_after_cutoff",
            "reported_result": "SUCCESS",
            "details": f"delete request for {EMAIL}",
        },
    ]
    rules = RuleEngine(
        [
            {
                "rule_id": "delete-profile",
                "data_category": "USER_PROFILE",
                "condition": "Always",
                "required_action": "DELETE",
            }
        ]
    )
    manifest = [
        {
            "file_id": "evidence_linked",
            "file_path": "evidence/logs/linked.log",
            "origin": "account_service",
            "captured_at": AUDIT_AT,
        },
        {
            "file_id": "evidence_future",
            "file_path": "evidence/logs/future.log",
            "origin": "account_service",
            "captured_at": "2026-09-15T12:00:01Z",
        },
    ]
    request = {"case_id": "fixture", "email": EMAIL, "audit_at": AUDIT_AT}
    toolbox = _toolbox_type().CaseToolbox(
        request=request,
        identity=identity,
        store=store,
        activities=activities,
        rule_engine=rules,
        manifest=manifest,
    )
    return toolbox, store


def test_case_tools_enforce_cutoff_on_records_activity_and_text(
    toolbox_fixture: tuple[Any, RecordStore],
) -> None:
    toolbox, _store = toolbox_fixture

    records = toolbox.dispatch("search_records", {"identifier": EMAIL})
    activity = toolbox.dispatch("get_activity", {"subject": EMAIL})
    text = toolbox.dispatch("read_text_evidence", {"evidence_id": "evidence_linked"})

    assert {row["resource_id"] for row in records["records"]} == {
        "profile_before",
        "profile_at_cutoff",
    }
    assert {row["activity_id"] for row in activity["events"]} == {
        "activity-before",
        "activity-at-cutoff",
    }
    assert text["captured_at"] == AUDIT_AT
    assert "profile_at_cutoff" in text["text"]


def test_tools_reject_unknown_evidence_ids_and_arbitrary_paths(
    toolbox_fixture: tuple[Any, RecordStore],
) -> None:
    toolbox, _store = toolbox_fixture
    tools_module = _toolbox_type()

    with pytest.raises(tools_module.ToolArgumentError):
        toolbox.dispatch("read_text_evidence", {"evidence_id": "missing-file"})
    with pytest.raises(tools_module.ToolArgumentError):
        toolbox.dispatch(
            "read_text_evidence",
            {"evidence_id": "evidence_linked", "path": "/etc/passwd"},
        )
    with pytest.raises(tools_module.ToolArgumentError):
        toolbox.dispatch("not_a_tool", {})


def test_tools_block_other_subject_identifiers_and_unobserved_resources(
    toolbox_fixture: tuple[Any, RecordStore],
) -> None:
    toolbox, _store = toolbox_fixture
    tools_module = _toolbox_type()

    assert toolbox.dispatch("resolve_identity", {"identifier": "other@example.test"})[
        "matches"
    ] == []
    assert toolbox.dispatch("search_records", {"identifier": "other@example.test"})[
        "records"
    ] == []
    with pytest.raises(tools_module.ToolArgumentError):
        toolbox.dispatch("compare_replicas", {"resource_id": "unrelated-resource"})


def test_read_text_rejects_capture_after_cutoff(
    toolbox_fixture: tuple[Any, RecordStore],
) -> None:
    toolbox, _store = toolbox_fixture
    tools_module = _toolbox_type()

    with pytest.raises(tools_module.ToolArgumentError):
        toolbox.dispatch("read_text_evidence", {"evidence_id": "evidence_future"})


def test_tool_schemas_are_fixed_and_observation_ids_are_deterministic(
    toolbox_fixture: tuple[Any, RecordStore],
) -> None:
    toolbox, _store = toolbox_fixture
    schemas = toolbox.schemas()
    names = {schema["function"]["name"] for schema in schemas}

    assert names == {
        "resolve_identity",
        "search_records",
        "compare_replicas",
        "get_activity",
        "get_rules",
        "read_text_evidence",
    }
    search_schema = next(
        schema["function"]
        for schema in schemas
        if schema["function"]["name"] == "search_records"
    )
    assert search_schema["parameters"]["required"] == ["identifier"]
    assert "system_id" not in search_schema["parameters"]["required"]
    first = toolbox.observe("search_records", {"identifier": EMAIL})
    second = toolbox.observe("get_activity", {"subject": EMAIL})
    assert first.observation_id == "obs_0001"
    assert second.observation_id == "obs_0002"
    assert first.result["records"]


def test_compare_replicas_deduplicates_direct_and_structured_paths() -> None:
    tools_module = _toolbox_type()
    store = RecordStore()
    store.add_record(
        NormalizedRecord(
            capture_id="evidence_source",
            captured_at=AUDIT_AT,
            topology="primary",
            system_id="account_service",
            resource_id="account_profile_61",
            category="USER_PROFILE",
            identifiers={"emails": (EMAIL,), "user_ids": (USER_ID,)},
            attributes={"copied_profile": "account_profile_60"},
        )
    )
    store.add_record(
        NormalizedRecord(
            capture_id="evidence_target",
            captured_at=AUDIT_AT,
            topology="primary",
            system_id="account_service",
            resource_id="account_profile_60",
            category="USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
            attributes={"email": EMAIL},
        )
    )
    identity = ResolvedIdentity(
        user_id=USER_ID,
        names=("Subject",),
        emails=(EMAIL,),
        email_hashes=(),
        phones=(),
        customer_references=(),
    )
    toolbox = tools_module.CaseToolbox(
        request={"case_id": "fixture", "email": EMAIL, "audit_at": AUDIT_AT},
        identity=identity,
        store=store,
        activities=[],
        rule_engine=RuleEngine([]),
        manifest=[],
    )
    toolbox.dispatch("search_records", {"identifier": EMAIL})

    result = toolbox.dispatch("compare_replicas", {"resource_id": "account_profile_60"})

    assert [row["resource_id"] for row in result["records"]].count("account_profile_60") == 1
