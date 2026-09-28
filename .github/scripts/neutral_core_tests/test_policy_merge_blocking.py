"""Tests for derive_merge_policy — blocking_stage_ids derivation (issue #186).

Covers: dogfood config assertion, BLOCKING/NON_BLOCKING filtering,
empty stage list, and mixed-gate stage lists.
"""
from __future__ import annotations

from neutral_core_tests.merge_test_helpers import (
    make_config,
    make_normalized_stage,
    make_trust_policy,
)


# ---------------------------------------------------------------------------
# Dogfood config
# ---------------------------------------------------------------------------

def test_merge_policy_dogfood_config() -> None:
    """Dogfood config + blocking stages → blockingStageIds == {'review', 'security'}, mode == AUTO."""
    from pathlib import Path
    import yaml  # noqa: PLC0415
    from neutral_core_tests.harness import REPO_ROOT
    from stagr.core.policy import derive_merge_policy, derive_trust_policy
    from stagr.core.enums import MergeMode

    config_path = Path(REPO_ROOT) / ".agentic" / "config.yml"
    with config_path.open() as config_file:
        raw_config = yaml.safe_load(config_file)

    trust_policy = derive_trust_policy(raw_config)

    review_stage = make_normalized_stage("review", gate="blocking")
    security_stage = make_normalized_stage("security", gate="blocking")
    implement_stage = make_normalized_stage("implement-claude", gate="non_blocking")
    normalized_stages = (implement_stage, review_stage, security_stage)

    policy = derive_merge_policy(raw_config, normalized_stages, trust_policy)

    assert set(policy.blocking_stage_ids) == {"review", "security"}, (
        f"Expected blocking stage ids to be {{'review', 'security'}}, "
        f"got {policy.blocking_stage_ids}"
    )
    assert len(policy.blocking_stage_ids) == 2, (
        f"Expected exactly 2 blocking stage ids, got {policy.blocking_stage_ids}"
    )
    assert policy.mode == MergeMode.AUTO, (
        f"Dogfood config has auto_merge: true, expected AUTO, got {policy.mode}"
    )


# ---------------------------------------------------------------------------
# blocking_stage_ids filtering
# ---------------------------------------------------------------------------

def test_merge_policy_blocking_stages_included() -> None:
    """Stages with gate BLOCKING appear in blocking_stage_ids."""
    from stagr.core.policy import derive_merge_policy

    blocking_stage = make_normalized_stage("check", gate="blocking")
    policy = derive_merge_policy(
        make_config(auto_merge=False),
        (blocking_stage,),
        make_trust_policy(),
    )

    assert "check" in policy.blocking_stage_ids, (
        "BLOCKING stage id must appear in blocking_stage_ids"
    )


def test_merge_policy_non_blocking_excluded() -> None:
    """Stages with gate NON_BLOCKING are absent from blocking_stage_ids."""
    from stagr.core.policy import derive_merge_policy

    non_blocking_stage = make_normalized_stage("implement", gate="non_blocking")
    policy = derive_merge_policy(
        make_config(auto_merge=False),
        (non_blocking_stage,),
        make_trust_policy(),
    )

    assert "implement" not in policy.blocking_stage_ids, (
        "NON_BLOCKING stage must NOT appear in blocking_stage_ids"
    )
    assert policy.blocking_stage_ids == (), (
        f"Expected empty blocking_stage_ids, got {policy.blocking_stage_ids}"
    )


def test_merge_policy_empty_stages_produces_empty_blocking_ids() -> None:
    """Empty normalized_stages tuple → empty blocking_stage_ids."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy(
        make_config(auto_merge=False),
        (),
        make_trust_policy(),
    )

    assert policy.blocking_stage_ids == (), (
        f"Empty stages must produce empty blocking_stage_ids, got {policy.blocking_stage_ids}"
    )


def test_merge_policy_mixed_gates_only_blocking_included() -> None:
    """Mixed gates: only BLOCKING stage ids appear; NON_BLOCKING are excluded."""
    from stagr.core.policy import derive_merge_policy

    blocking_a = make_normalized_stage("review", gate="blocking")
    non_blocking = make_normalized_stage("implement", gate="non_blocking")
    blocking_b = make_normalized_stage("security", gate="blocking")
    normalized_stages = (blocking_a, non_blocking, blocking_b)

    policy = derive_merge_policy(
        make_config(auto_merge=False),
        normalized_stages,
        make_trust_policy(),
    )

    assert "review" in policy.blocking_stage_ids, "'review' must be in blocking_stage_ids"
    assert "security" in policy.blocking_stage_ids, "'security' must be in blocking_stage_ids"
    assert "implement" not in policy.blocking_stage_ids, (
        "'implement' must NOT be in blocking_stage_ids"
    )
    assert len(policy.blocking_stage_ids) == 2, (
        f"Expected exactly 2 blocking ids, got {policy.blocking_stage_ids}"
    )
