"""Tests for derive_trust_policy (issue #184).

Covers TrustPolicy derivation from the raw M1 config dict: trusted_roles
validation, same_repo_only → fork_policy mapping, human_merge_label defaulting
and override, and the V-S14 error path for unrecognised role strings.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(
    trusted_roles: list[str] | None = None,
    same_repo_only: bool | None = None,
    human_merge_label: str | None = None,
) -> dict:
    """Build a minimal raw config dict for use in trust-policy tests."""
    platform: dict = {}
    if trusted_roles is not None:
        platform["trusted_roles"] = trusted_roles
    if same_repo_only is not None:
        platform["same_repo_only"] = same_repo_only
    if human_merge_label is not None:
        platform.setdefault("labels", {})["human_merge"] = human_merge_label
    return {"platform": platform}


# ---------------------------------------------------------------------------
# Dogfood config
# ---------------------------------------------------------------------------

def test_trust_policy_dogfood_config() -> None:
    """Dogfood config's trusted_roles [owner, member, collaborator] → OWNER/MEMBER/COLLABORATOR,
    same_repo_only absent → DENY, labels.human_merge 'human-merge' → 'human-merge'.
    """
    from pathlib import Path
    import yaml  # noqa: PLC0415 — available in the CI environment
    from neutral_core_tests.harness import REPO_ROOT
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import AuthorRole, ForkPolicy

    config_path = Path(REPO_ROOT) / ".agentic" / "config.yml"
    with config_path.open() as config_file:
        raw_config = yaml.safe_load(config_file)

    policy = derive_trust_policy(raw_config)

    assert AuthorRole.OWNER in policy.trusted_roles, "OWNER must be trusted in dogfood config"
    assert AuthorRole.MEMBER in policy.trusted_roles, "MEMBER must be trusted in dogfood config"
    assert AuthorRole.COLLABORATOR in policy.trusted_roles, (
        "COLLABORATOR must be trusted in dogfood config"
    )
    assert len(policy.trusted_roles) == 3, (
        f"Expected exactly 3 trusted roles, got {policy.trusted_roles}"
    )
    assert policy.fork_policy == ForkPolicy.DENY, (
        f"Expected DENY fork policy from dogfood config, got {policy.fork_policy}"
    )
    assert policy.human_merge_label == "human-merge", (
        f"Expected 'human-merge' label, got {policy.human_merge_label!r}"
    )


# ---------------------------------------------------------------------------
# fork_policy / same_repo_only mapping
# ---------------------------------------------------------------------------

def test_trust_policy_default_fork_policy_is_deny() -> None:
    """Absent same_repo_only defaults to true → ForkPolicy.DENY."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import ForkPolicy

    policy = derive_trust_policy(_make_config(trusted_roles=["owner"]))

    assert policy.fork_policy == ForkPolicy.DENY, (
        f"Absent same_repo_only must default to DENY, got {policy.fork_policy}"
    )


def test_trust_policy_explicit_fork_policy() -> None:
    """same_repo_only: false → ForkPolicy.ALLOW_UNPRIVILEGED."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import ForkPolicy

    policy = derive_trust_policy(
        _make_config(trusted_roles=["owner"], same_repo_only=False)
    )

    assert policy.fork_policy == ForkPolicy.ALLOW_UNPRIVILEGED, (
        f"Expected ALLOW_UNPRIVILEGED, got {policy.fork_policy}"
    )


# ---------------------------------------------------------------------------
# human_merge_label defaulting and override
# ---------------------------------------------------------------------------

def test_trust_policy_default_human_merge_label() -> None:
    """Absent platform.labels.human_merge defaults to 'human-merge'."""
    from stagr.core.policy import derive_trust_policy

    policy = derive_trust_policy(_make_config(trusted_roles=["owner"]))

    assert policy.human_merge_label == "human-merge", (
        f"Absent labels.human_merge must default to 'human-merge', "
        f"got {policy.human_merge_label!r}"
    )


def test_trust_policy_custom_human_merge_label() -> None:
    """platform.labels.human_merge: 'no-merge' → human_merge_label == 'no-merge'."""
    from stagr.core.policy import derive_trust_policy

    policy = derive_trust_policy(
        _make_config(trusted_roles=["owner"], human_merge_label="no-merge")
    )

    assert policy.human_merge_label == "no-merge", (
        f"Expected 'no-merge', got {policy.human_merge_label!r}"
    )


# ---------------------------------------------------------------------------
# trusted_roles — content and exclusion
# ---------------------------------------------------------------------------

def test_trust_policy_contributor_not_in_defaults() -> None:
    """When trusted_roles lists only 'owner', CONTRIBUTOR is not present."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import AuthorRole

    policy = derive_trust_policy(_make_config(trusted_roles=["owner"]))

    assert AuthorRole.CONTRIBUTOR not in policy.trusted_roles, (
        "CONTRIBUTOR must not appear unless explicitly listed in trusted_roles"
    )
    assert AuthorRole.OWNER in policy.trusted_roles, "OWNER must be present"
    assert len(policy.trusted_roles) == 1, (
        f"Expected exactly 1 trusted role, got {policy.trusted_roles}"
    )


def test_trust_policy_absent_trusted_roles_key_uses_default() -> None:
    """When trusted_roles key is absent, the schema default (owner/member/collaborator) applies."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import AuthorRole

    policy = derive_trust_policy({"platform": {}})

    assert AuthorRole.OWNER in policy.trusted_roles, "OWNER must be in schema default"
    assert AuthorRole.MEMBER in policy.trusted_roles, "MEMBER must be in schema default"
    assert AuthorRole.COLLABORATOR in policy.trusted_roles, (
        "COLLABORATOR must be in schema default"
    )
    assert len(policy.trusted_roles) == 3, (
        f"Schema default must be exactly 3 roles, got {policy.trusted_roles}"
    )


# ---------------------------------------------------------------------------
# V-S14: unrecognised role string
# ---------------------------------------------------------------------------

def test_trust_policy_unrecognized_role_raises() -> None:
    """An unrecognised role string raises StaticValidationError referencing V-S14."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.models import StaticValidationError

    raised = False
    try:
        derive_trust_policy(_make_config(trusted_roles=["superadmin"]))
    except StaticValidationError as exc:
        raised = True
        assert "V-S14" in str(exc), (
            f"Error must reference V-S14, got: {exc}"
        )
        assert "superadmin" in str(exc), (
            f"Error must name the offending role, got: {exc}"
        )
    assert raised, "Expected StaticValidationError for unrecognised role 'superadmin'"


def test_trust_policy_unrecognized_role_names_bad_value() -> None:
    """V-S14 error message names the specific unrecognised role string."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.models import StaticValidationError

    raised = False
    try:
        derive_trust_policy(_make_config(trusted_roles=["owner", "alien_role"]))
    except StaticValidationError as exc:
        raised = True
        assert "alien_role" in str(exc), (
            f"Error message must name 'alien_role', got: {exc}"
        )
    assert raised, "Expected StaticValidationError for 'alien_role'"


# ---------------------------------------------------------------------------
# Absent / empty platform section
# ---------------------------------------------------------------------------

def test_trust_policy_absent_platform_section() -> None:
    """Config with no platform key applies schema defaults: owner/member/collaborator, DENY, 'human-merge'."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.enums import AuthorRole, ForkPolicy

    policy = derive_trust_policy({})

    assert AuthorRole.OWNER in policy.trusted_roles, (
        "Absent platform must yield default OWNER role"
    )
    assert AuthorRole.MEMBER in policy.trusted_roles, (
        "Absent platform must yield default MEMBER role"
    )
    assert AuthorRole.COLLABORATOR in policy.trusted_roles, (
        "Absent platform must yield default COLLABORATOR role"
    )
    assert len(policy.trusted_roles) == 3, (
        f"Absent platform must yield exactly 3 default roles, got {policy.trusted_roles}"
    )
    assert policy.fork_policy == ForkPolicy.DENY
    assert policy.human_merge_label == "human-merge"


def test_trust_policy_empty_trusted_roles() -> None:
    """An explicit empty trusted_roles list produces an empty tuple."""
    from stagr.core.policy import derive_trust_policy

    policy = derive_trust_policy(_make_config(trusted_roles=[]))

    assert policy.trusted_roles == (), (
        f"Empty trusted_roles list must produce empty tuple, got {policy.trusted_roles}"
    )


# ---------------------------------------------------------------------------
# Return type and immutability
# ---------------------------------------------------------------------------

def test_trust_policy_returns_trust_policy_instance() -> None:
    """derive_trust_policy returns a TrustPolicy instance."""
    from stagr.core.policy import derive_trust_policy
    from stagr.core.models import TrustPolicy

    policy = derive_trust_policy(_make_config(trusted_roles=["owner"]))

    assert isinstance(policy, TrustPolicy), (
        f"Expected TrustPolicy, got {type(policy)}"
    )


def test_trust_policy_result_is_frozen() -> None:
    """TrustPolicy is a frozen dataclass; attribute assignment raises FrozenInstanceError."""
    from stagr.core.policy import derive_trust_policy

    policy = derive_trust_policy(_make_config(trusted_roles=["owner"]))

    raised = False
    try:
        policy.human_merge_label = "mutated"  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "TrustPolicy must be immutable (frozen dataclass)"
