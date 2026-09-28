"""Tests for derive_merge_policy (issue #186).

Covers MergePolicy derivation: blocking_stage_ids filtering, merge mode from
modules.auto_merge, require_head_bound always-true, discussion_policy defaulting
and override, external_gates from modules.sonar, and the V1 dogfood assertion.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_normalized_stage(
    stage_id: str,
    gate: str = "blocking",
    provider: str = "anthropic",
) -> object:
    """Build a minimal NormalizedStage for use in merge-policy tests."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageGate, StageKind, StageTrigger

    gate_value = StageGate(gate)
    return NormalizedStage(
        id=stage_id,
        kind=StageKind.REVIEW,
        provider=provider,
        backend="generic",
        skill=None,
        gate=gate_value,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )


def _make_config(
    auto_merge: bool | None = None,
    sonar: bool | None = None,
    require_resolved: bool | None = None,
) -> dict:
    """Build a minimal raw config dict for use in merge-policy tests."""
    config: dict = {}
    if auto_merge is not None or sonar is not None:
        modules: dict = {}
        if auto_merge is not None:
            modules["auto_merge"] = auto_merge
        if sonar is not None:
            modules["sonar"] = sonar
        config["modules"] = modules
    if require_resolved is not None:
        config["merge"] = {"discussions": {"require_resolved": require_resolved}}
    return config


def _make_trust_policy() -> object:
    """Build a minimal TrustPolicy for use in merge-policy tests."""
    from stagr.core.policy import derive_trust_policy
    return derive_trust_policy({"platform": {}})


# ---------------------------------------------------------------------------
# Dogfood config
# ---------------------------------------------------------------------------

def test_merge_policy_dogfood_config() -> None:
    """Dogfood config + blocking stages → blockingStageIds == ['review', 'security'], mode == AUTO."""
    from pathlib import Path
    import yaml  # noqa: PLC0415
    from neutral_core_tests.harness import REPO_ROOT
    from stagr.core.policy import derive_merge_policy, derive_trust_policy
    from stagr.core.enums import MergeMode

    config_path = Path(REPO_ROOT) / ".agentic" / "config.yml"
    with config_path.open() as config_file:
        raw_config = yaml.safe_load(config_file)

    trust_policy = derive_trust_policy(raw_config)

    review_stage = _make_normalized_stage("review", gate="blocking")
    security_stage = _make_normalized_stage("security", gate="blocking")
    implement_stage = _make_normalized_stage("implement-claude", gate="non_blocking")
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
    from stagr.core.enums import MergeMode

    blocking_stage = _make_normalized_stage("check", gate="blocking")
    policy = derive_merge_policy(
        _make_config(auto_merge=False),
        (blocking_stage,),
        _make_trust_policy(),
    )

    assert "check" in policy.blocking_stage_ids, (
        "BLOCKING stage id must appear in blocking_stage_ids"
    )


def test_merge_policy_non_blocking_excluded() -> None:
    """Stages with gate NON_BLOCKING are absent from blocking_stage_ids."""
    from stagr.core.policy import derive_merge_policy

    non_blocking_stage = _make_normalized_stage("implement", gate="non_blocking")
    policy = derive_merge_policy(
        _make_config(auto_merge=False),
        (non_blocking_stage,),
        _make_trust_policy(),
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
        _make_config(auto_merge=False),
        (),
        _make_trust_policy(),
    )

    assert policy.blocking_stage_ids == (), (
        f"Empty stages must produce empty blocking_stage_ids, got {policy.blocking_stage_ids}"
    )


def test_merge_policy_mixed_gates_only_blocking_included() -> None:
    """Mixed gates: only BLOCKING stage ids appear; NON_BLOCKING are excluded."""
    from stagr.core.policy import derive_merge_policy

    blocking_a = _make_normalized_stage("review", gate="blocking")
    non_blocking = _make_normalized_stage("implement", gate="non_blocking")
    blocking_b = _make_normalized_stage("security", gate="blocking")
    normalized_stages = (blocking_a, non_blocking, blocking_b)

    policy = derive_merge_policy(
        _make_config(auto_merge=False),
        normalized_stages,
        _make_trust_policy(),
    )

    assert "review" in policy.blocking_stage_ids, "'review' must be in blocking_stage_ids"
    assert "security" in policy.blocking_stage_ids, "'security' must be in blocking_stage_ids"
    assert "implement" not in policy.blocking_stage_ids, (
        "'implement' must NOT be in blocking_stage_ids"
    )
    assert len(policy.blocking_stage_ids) == 2, (
        f"Expected exactly 2 blocking ids, got {policy.blocking_stage_ids}"
    )


# ---------------------------------------------------------------------------
# MergeMode from modules.auto_merge
# ---------------------------------------------------------------------------

def test_merge_policy_mode_auto_when_auto_merge_true() -> None:
    """modules.auto_merge: true → mode == MergeMode.AUTO."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy(
        _make_config(auto_merge=True),
        (),
        _make_trust_policy(),
    )

    assert policy.mode == MergeMode.AUTO, (
        f"auto_merge: true must produce AUTO, got {policy.mode}"
    )


def test_merge_policy_mode_manual_when_auto_merge_false() -> None:
    """modules.auto_merge: false → mode == MergeMode.MANUAL."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy(
        _make_config(auto_merge=False),
        (),
        _make_trust_policy(),
    )

    assert policy.mode == MergeMode.MANUAL, (
        f"auto_merge: false must produce MANUAL, got {policy.mode}"
    )


def test_merge_policy_mode_manual_when_modules_absent() -> None:
    """Absent modules key → mode == MergeMode.MANUAL."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.enums import MergeMode

    policy = derive_merge_policy({}, (), _make_trust_policy())

    assert policy.mode == MergeMode.MANUAL, (
        f"Absent modules must default to MANUAL, got {policy.mode}"
    )


# ---------------------------------------------------------------------------
# require_head_bound always True in V1
# ---------------------------------------------------------------------------

def test_merge_policy_require_head_bound_always_true() -> None:
    """require_head_bound is always True in V1."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), _make_trust_policy())

    assert policy.require_head_bound is True, (
        f"require_head_bound must always be True in V1, got {policy.require_head_bound}"
    )


# ---------------------------------------------------------------------------
# discussion_policy
# ---------------------------------------------------------------------------

def test_merge_policy_discussion_policy_absent_is_none() -> None:
    """Absent merge.discussions key → discussion_policy is None."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), _make_trust_policy())

    assert policy.discussion_policy is None, (
        f"Absent discussions config must produce None, got {policy.discussion_policy}"
    )


def test_merge_policy_discussion_policy_require_resolved_true() -> None:
    """merge.discussions.require_resolved: true → DiscussionPolicy(require_resolved=True)."""
    from stagr.core.policy import derive_merge_policy
    from stagr.core.models import DiscussionPolicy

    policy = derive_merge_policy(
        _make_config(require_resolved=True),
        (),
        _make_trust_policy(),
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
        _make_config(require_resolved=False),
        (),
        _make_trust_policy(),
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

    policy = derive_merge_policy(
        _make_config(sonar=True),
        (),
        _make_trust_policy(),
    )

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

    policy = derive_merge_policy(
        _make_config(sonar=False),
        (),
        _make_trust_policy(),
    )

    assert policy.external_gates == (), (
        f"modules.sonar: false must produce empty external_gates, got {policy.external_gates}"
    )


def test_merge_policy_sonar_absent_no_external_gate() -> None:
    """Absent modules.sonar → external_gates is empty."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), _make_trust_policy())

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

    policy = derive_merge_policy({}, (), _make_trust_policy())

    assert isinstance(policy, MergePolicy), (
        f"Expected MergePolicy, got {type(policy)}"
    )


def test_merge_policy_result_is_frozen() -> None:
    """MergePolicy is a frozen dataclass; attribute assignment raises an error."""
    from stagr.core.policy import derive_merge_policy

    policy = derive_merge_policy({}, (), _make_trust_policy())

    raised = False
    try:
        policy.mode = "mutated"  # type: ignore[misc]
    except Exception:
        raised = True
    assert raised, "MergePolicy must be immutable (frozen dataclass)"
