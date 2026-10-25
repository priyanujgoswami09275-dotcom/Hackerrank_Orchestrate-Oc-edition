from __future__ import annotations

import importlib
from pathlib import Path
import sys
from typing import Any

import pytest

CODE = Path(__file__).resolve().parents[1]
if str(CODE) not in sys.path:
    sys.path.insert(0, str(CODE))

from pramaantrace.agent.loop import CandidateLink  # noqa: E402
from pramaantrace.agent.tools import CaseToolbox  # noqa: E402
from pramaantrace.identity import ResolvedIdentity  # noqa: E402
from pramaantrace.rules import RuleEngine  # noqa: E402
from pramaantrace.store import NormalizedRecord, RecordStore  # noqa: E402

AUDIT_AT = "2026-09-15T12:00:00Z"
EMAIL = "subject@example.test"
USER_ID = "user_subject"


def _verifier_module() -> Any:
    try:
        return importlib.import_module("pramaantrace.agent.verifier")
    except ImportError as exc:
        pytest.fail(f"missing candidate verifier module: {exc}")


def _record(
    capture_id: str,
    resource_id: str,
    system_id: str,
    category: str,
    *,
    identifiers: dict[str, tuple[str, ...]] | None = None,
    attributes: dict[str, Any] | None = None,
    captured_at: str = AUDIT_AT,
    topology: str = "primary",
) -> NormalizedRecord:
    return NormalizedRecord(
        capture_id=capture_id,
        captured_at=captured_at,
        topology=topology,
        system_id=system_id,
        resource_id=resource_id,
        category=category,
        identifiers=identifiers or {},
        attributes=attributes or {},
    )


def _identity() -> ResolvedIdentity:
    return ResolvedIdentity(
        user_id=USER_ID,
        names=("Subject",),
        emails=(EMAIL,),
        email_hashes=("a" * 64,),
        phones=("15551234567",),
        customer_references=("customer_subject",),
    )


def _toolbox(store: RecordStore, *, activities: list[dict[str, str]] | None = None) -> CaseToolbox:
    return CaseToolbox(
        request={"case_id": "fixture", "email": EMAIL, "audit_at": AUDIT_AT},
        identity=_identity(),
        store=store,
        activities=activities or [],
        rule_engine=RuleEngine([]),
        manifest=[],
    )


def _search_subject(toolbox: CaseToolbox) -> Any:
    return toolbox.observe("search_records", {"identifier": EMAIL})


def test_direct_identifier_record_is_accepted_after_observation_replay() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_profile",
            "account_profile_41",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,), "user_ids": (USER_ID,)},
        )
    )
    toolbox = _toolbox(store)
    observation = _search_subject(toolbox)
    candidate = CandidateLink("account_profile_41", "capture_profile", observation.observation_id)

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate,),
        (observation,),
        toolbox,
        store,
    )

    assert verified == (("account_service", "account_profile_41", "USER_PROFILE"),)


def test_structured_reference_from_subject_linked_record_is_accepted() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_source",
            "account_profile_42",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
            attributes={"analytics_source": "analytics_profile_71"},
        )
    )
    store.add_record(
        _record(
            "capture_target",
            "analytics_profile_71",
            "analytics_platform",
            "ANALYTICS_PROFILE",
            attributes={"email": EMAIL},
            topology="regional_replica",
        )
    )
    toolbox = _toolbox(store)
    source_observation = _search_subject(toolbox)
    target_observation = toolbox.observe(
        "compare_replicas", {"resource_id": "analytics_profile_71"}
    )
    candidate = CandidateLink(
        "analytics_profile_71", "capture_target", target_observation.observation_id
    )

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate,),
        (source_observation, target_observation),
        toolbox,
        store,
    )

    assert verified == (("analytics_platform", "analytics_profile_71", "ANALYTICS_PROFILE"),)


@pytest.mark.parametrize(
    "candidate_factory",
    [
        lambda obs: CandidateLink("account_profile_44", "capture_missing", "obs_fake"),
        lambda obs: CandidateLink("account_profile_other", "capture_other", obs.observation_id),
    ],
    ids=["fake-observation-and-resource", "candidate-not-in-observation"],
)
def test_unknown_or_mismatched_candidate_is_rejected(candidate_factory: Any) -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_profile",
            "account_profile_43",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
        )
    )
    toolbox = _toolbox(store)
    observation = _search_subject(toolbox)

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate_factory(observation),),
        (observation,),
        toolbox,
        store,
    )

    assert verified == ()


def test_cross_subject_record_cannot_be_claimed_through_subject_observation() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_subject",
            "account_profile_45",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
        )
    )
    store.add_record(
        _record(
            "capture_other",
            "account_profile_46",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": ("other@example.test",), "user_ids": ("user_other",)},
        )
    )
    toolbox = _toolbox(store)
    observation = _search_subject(toolbox)
    candidate = CandidateLink(
        "account_profile_46", "capture_other", observation.observation_id
    )

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT}, _identity(), (candidate,), (observation,), toolbox, store
    )

    assert verified == ()


def test_replay_does_not_trust_unrecorded_prior_toolbox_state() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_profile",
            "account_profile_50",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
        )
    )
    toolbox = _toolbox(store)
    _search_subject(toolbox)  # Deliberately omit this observation from the trace.
    compare = toolbox.observe("compare_replicas", {"resource_id": "account_profile_50"})
    candidate = CandidateLink(
        "account_profile_50", "capture_profile", compare.observation_id
    )

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate,),
        (compare,),
        toolbox,
        store,
    )

    assert verified == ()


def test_ambiguous_reference_shared_with_another_subject_is_rejected() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_subject_source",
            "account_profile_47",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
            attributes={"analytics_source": "analytics_profile_72"},
        )
    )
    store.add_record(
        _record(
            "capture_other_source",
            "account_profile_48",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": ("other@example.test",)},
            attributes={"analytics_source": "analytics_profile_72"},
        )
    )
    store.add_record(
        _record(
            "capture_analytics",
            "analytics_profile_72",
            "analytics_platform",
            "ANALYTICS_PROFILE",
        )
    )
    toolbox = _toolbox(store)
    source = _search_subject(toolbox)
    target = toolbox.observe("compare_replicas", {"resource_id": "analytics_profile_72"})
    candidate = CandidateLink("analytics_profile_72", "capture_analytics", target.observation_id)

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate,),
        (source, target),
        toolbox,
        store,
    )

    assert verified == ()


def test_bare_404_activity_and_post_cutoff_record_are_not_findings() -> None:
    module = _verifier_module()
    store = RecordStore()
    store.add_record(
        _record(
            "capture_future",
            "account_profile_49",
            "account_service",
            "USER_PROFILE",
            identifiers={"emails": (EMAIL,)},
            captured_at="2026-09-15T12:00:01Z",
        )
    )
    activity = {
        "activity_id": "activity_404",
        "event_time": "2026-09-15T11:59:00Z",
        "event_type": "LOOKUP_COMPLETED",
        "source_system": "account_service",
        "target_system": "",
        "resource_id": "account_profile_49",
        "reported_result": "404",
        "details": f"lookup returned 404 for {EMAIL}",
    }
    toolbox = _toolbox(store, activities=[activity])
    observation = toolbox.observe("get_activity", {"subject": EMAIL})
    candidate = CandidateLink("account_profile_49", "capture_future", observation.observation_id)

    verified = module.verify_candidate_links(
        {"audit_at": AUDIT_AT},
        _identity(),
        (candidate,),
        (observation,),
        toolbox,
        store,
    )

    assert verified == ()
