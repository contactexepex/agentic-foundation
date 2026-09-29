"""Tests for derive_merge_policy — require_head_bound, discussion_policy,
return type, and immutability (issue #186).
"""
from __future__ import annotations

from neutral_core_tests.merge_test_helpers import make_config, make_trust_policy


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
        policy.require_head_bound = False  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "MergePolicy must be immutable (frozen dataclass)"
