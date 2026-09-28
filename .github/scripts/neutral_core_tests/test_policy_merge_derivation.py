"""Tests for derive_merge_policy — mode, require_head_bound, discussion_policy,
external_gates, return type, and immutability (issue #186).
"""
from __future__ import annotations

from neutral_core_tests.merge_test_helpers import make_config, make_trust_policy


# ---------------------------------------------------------------------------
# MergeMode from modules.auto_merge
# ---------------------------------------------------------------------------

def test_merge_policy_mode_auto_when_auto_merge_true() -> None:
    """modules.auto_merge: true → mode == MergeMode.AUTO."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy(make_config(auto_merge=True), (), make_trust_policy())

    assert policy.mode == MergeMode.AUTO, (
        f"auto_merge: true must produce AUTO, got {policy.mode}"
    )


def test_merge_policy_mode_manual_when_auto_merge_false() -> None:
    """modules.auto_merge: false → mode == MergeMode.MANUAL."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy(make_config(auto_merge=False), (), make_trust_policy())

    assert policy.mode == MergeMode.MANUAL, (
        f"auto_merge: false must produce MANUAL, got {policy.mode}"
    )


def test_merge_policy_mode_manual_when_modules_absent() -> None:
    """Absent modules key → mode == MergeMode.MANUAL."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy({}, (), make_trust_policy())

    assert policy.mode == MergeMode.MANUAL, (
        f"Absent modules must default to MANUAL, got {policy.mode}"
    )


# ---------------------------------------------------------------------------
# require_head_bound always True in V1
# ---------------------------------------------------------------------------

def test_merge_policy_require_head_bound_always_true() -> None:
    """require_head_bound is always True in V1."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), make_trust_policy())

    assert policy.require_head_bound is True, (
        f"require_head_bound must always be True in V1, got {policy.require_head_bound}"
    )


# ---------------------------------------------------------------------------
# discussion_policy
# ---------------------------------------------------------------------------

def test_merge_policy_discussion_policy_absent_is_none() -> None:
    """Absent merge.discussions key → discussion_policy is None."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), make_trust_policy())

    assert policy.discussion_policy is None, (
        f"Absent discussions config must produce None, got {policy.discussion_policy}"
    )


def test_merge_policy_discussion_policy_require_resolved_true() -> None:
    """merge.discussions.require_resolved: true → DiscussionPolicy(require_resolved=True)."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.models import DiscussionPolicy

    policy = derive_merge_policy(
        make_config(require_resolved=True), (), make_trust_policy()
    )

    assert policy.discussion_policy is not None, (
        "discussion_policy must not be None when require_resolved is set"
    )
    assert isinstance(policy.discussion_policy, DiscussionPolicy), (
        f"Expected DiscussionPolicy, got {type(policy.discussion_policy)}"
    )
    assert policy.discussion_policy.require_resolved is True, (
        f"Expected require_resolved=True, got {policy.discussion_policy.require_resolved}"
    )


def test_merge_policy_discussion_policy_require_resolved_false() -> None:
    """merge.discussions.require_resolved: false → DiscussionPolicy(require_resolved=False)."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy(
        make_config(require_resolved=False), (), make_trust_policy()
    )

    assert policy.discussion_policy is not None
    assert policy.discussion_policy.require_resolved is False, (
        f"Expected require_resolved=False, got {policy.discussion_policy.require_resolved}"
    )


# ---------------------------------------------------------------------------
# external_gates from modules.sonar
# ---------------------------------------------------------------------------

def test_merge_policy_sonar_true_adds_external_gate() -> None:
    """modules.sonar: true → external_gates contains the sonarqubecloud gate."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy(make_config(sonar=True), (), make_trust_policy())

    assert len(policy.external_gates) == 1, (
        f"modules.sonar: true must produce exactly 1 external gate, "
        f"got {len(policy.external_gates)}"
    )
    gate = policy.external_gates[0]
    assert gate.check_run_name == "sonarqubecloud", (
        f"Expected check_run_name='sonarqubecloud', got {gate.check_run_name!r}"
    )
    assert gate.required_presence == "when_present", (
        f"V1 sonar gate must be when_present, got {gate.required_presence!r}"
    )
    assert gate.required_conclusion == "success", (
        f"V1 sonar gate must require success, got {gate.required_conclusion!r}"
    )


def test_merge_policy_sonar_false_no_external_gate() -> None:
    """modules.sonar: false → external_gates is empty."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy(make_config(sonar=False), (), make_trust_policy())

    assert policy.external_gates == (), (
        f"modules.sonar: false must produce empty external_gates, got {policy.external_gates}"
    )


def test_merge_policy_sonar_absent_no_external_gate() -> None:
    """Absent modules.sonar → external_gates is empty."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), make_trust_policy())

    assert policy.external_gates == (), (
        f"Absent modules.sonar must produce empty external_gates, got {policy.external_gates}"
    )


# ---------------------------------------------------------------------------
# Return type and immutability
# ---------------------------------------------------------------------------

def test_merge_policy_returns_merge_policy_instance() -> None:
    """derive_merge_policy returns a MergePolicy instance."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.models import MergePolicy

    policy = derive_merge_policy({}, (), make_trust_policy())

    assert isinstance(policy, MergePolicy), (
        f"Expected MergePolicy, got {type(policy)}"
    )


def test_merge_policy_result_is_frozen() -> None:
    """MergePolicy is a frozen dataclass; attribute assignment raises an error."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), make_trust_policy())

    raised = False
    try:
        policy.mode = "mutated"  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "MergePolicy must be immutable (frozen dataclass)"
