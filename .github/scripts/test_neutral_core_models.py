#!/usr/bin/env python3
"""Tests for neutral core data models and enumerations (Group A: issues #173–#178).

Run with: python .github/scripts/test_neutral_core_models.py
No pytest required. Exit 0 = all pass.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

# Allow imports from the repo root.
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

failures: list[str] = []


def _fail(name: str, exc: Exception) -> None:
    failures.append(name)
    print(f"FAIL  {name}")
    traceback.print_exc()
    print()


def _ok(name: str) -> None:
    print(f"ok    {name}")


# ---------------------------------------------------------------------------
# #173 — Enumerations
# ---------------------------------------------------------------------------


def test_enum_string_values() -> None:
    """All enum members have the correct string values per design doc."""
    from stagr.core.enums import (
        AuthorRole,
        EvidenceKind,
        ForkPolicy,
        InvocationKind,
        MergeMode,
        StageGate,
        StageKind,
        StageResultConclusion,
        StageResultSignalKind,
        StageResultState,
        StageTrigger,
    )

    # StageKind
    assert StageKind("review") is StageKind.REVIEW
    assert StageKind("security") is StageKind.SECURITY
    assert StageKind("build") is StageKind.BUILD
    assert StageKind("test") is StageKind.TEST
    assert StageKind("deploy") is StageKind.DEPLOY
    assert StageKind("custom") is StageKind.CUSTOM
    assert StageKind("implement") is StageKind.IMPLEMENT

    # StageGate
    assert StageGate("blocking") is StageGate.BLOCKING
    assert StageGate("non_blocking") is StageGate.NON_BLOCKING

    # StageTrigger
    assert StageTrigger("pr_opened") is StageTrigger.PR_OPENED
    assert StageTrigger("pr_updated") is StageTrigger.PR_UPDATED
    assert StageTrigger("manual") is StageTrigger.MANUAL
    assert StageTrigger("issue_labeled") is StageTrigger.ISSUE_LABELED

    # AuthorRole — CONTRIBUTOR must exist but is not trusted by default
    assert AuthorRole("contributor") is AuthorRole.CONTRIBUTOR
    assert AuthorRole("owner") is AuthorRole.OWNER

    # ForkPolicy
    assert ForkPolicy("deny") is ForkPolicy.DENY
    assert ForkPolicy("allow_unprivileged") is ForkPolicy.ALLOW_UNPRIVILEGED

    # MergeMode
    assert MergeMode("auto") is MergeMode.AUTO
    assert MergeMode("manual") is MergeMode.MANUAL

    # InvocationKind
    assert InvocationKind("pr_comment") is InvocationKind.PR_COMMENT
    assert InvocationKind("ci_component") is InvocationKind.CI_COMPONENT

    # StageResultSignalKind — all three variants exist
    assert StageResultSignalKind("check_run") is StageResultSignalKind.CHECK_RUN
    assert StageResultSignalKind("commit_status") is StageResultSignalKind.COMMIT_STATUS

    # StageResultState
    assert StageResultState("completed") is StageResultState.COMPLETED
    assert StageResultState("failed") is StageResultState.FAILED

    # StageResultConclusion — BLOCKED is distinct from FAILED
    assert StageResultConclusion("pass") is StageResultConclusion.PASS
    assert StageResultConclusion("blocked") is StageResultConclusion.BLOCKED
    assert StageResultConclusion("failed") is StageResultConclusion.FAILED
    assert StageResultConclusion("unknown") is StageResultConclusion.UNKNOWN

    # No platform-specific names in enum values
    for enum_cls in [StageKind, StageGate, StageTrigger, AuthorRole, ForkPolicy,
                     MergeMode, InvocationKind, StageResultSignalKind,
                     StageResultState, StageResultConclusion, EvidenceKind]:
        for member in enum_cls:
            val = member.value
            for forbidden in ["pull_request_target", "workflow_dispatch_event",
                               "permissions", "github_token"]:
                assert forbidden not in val.lower(), \
                    f"{enum_cls.__name__}.{member.name} value '{val}' contains platform-specific name"


# ---------------------------------------------------------------------------
# #174 — NormalizedStage
# ---------------------------------------------------------------------------


def test_normalized_stage_construction() -> None:
    """NormalizedStage round-trips correctly; no enabled field; model may be None."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageKind, StageGate, StageTrigger

    stage = NormalizedStage(
        id="review",
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill="code-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
        dependencies=(),
        model=None,
    )
    assert stage.id == "review"
    assert stage.model is None
    assert stage.gate is StageGate.BLOCKING
    assert len(stage.triggers) == 2

    # No `enabled` field
    assert not hasattr(stage, "enabled"), "NormalizedStage must not have an `enabled` field"


def test_normalized_stage_empty_dependencies() -> None:
    """A NormalizedStage with empty dependencies is valid."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageKind, StageGate, StageTrigger

    stage = NormalizedStage(
        id="security",
        kind=StageKind.SECURITY,
        provider="openai",
        backend="codex",
        skill="security-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )
    assert stage.dependencies == ()


# ---------------------------------------------------------------------------
# #175 — ExecutionPlan
# ---------------------------------------------------------------------------


def test_execution_plan_requires_gate_disposition() -> None:
    """ExecutionPlan without gate_disposition raises ValueError."""
    from stagr.core.models import ExecutionPlan, Invocation
    from stagr.core.enums import InvocationKind

    inv = Invocation(kind=InvocationKind.PR_COMMENT)
    try:
        ExecutionPlan(
            stage_id="review",
            invocation=inv,
            gate_disposition=None,  # type: ignore[arg-type]
        )
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "gate_disposition" in str(exc)


def test_execution_plan_valid() -> None:
    """ExecutionPlan with all required fields constructs and has no platform-specific fields."""
    from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation, SecretRef
    from stagr.core.enums import InvocationKind

    inv = Invocation(kind=InvocationKind.PR_COMMENT, params={"comment_template": "review me"})
    gate = GateDispositionSpec(kind="conclusion_field", params={"field": "conclusion"})
    plan = ExecutionPlan(
        stage_id="review",
        invocation=inv,
        gate_disposition=gate,
        required_secrets=(SecretRef(alias="CODEX_API_KEY", env_name="OPENAI_API_KEY"),),
    )
    assert plan.stage_id == "review"
    assert plan.invocation.kind is InvocationKind.PR_COMMENT
    assert len(plan.required_secrets) == 1
    assert plan.evidence == ()

    # No platform-specific fields
    assert not hasattr(plan, "permissions")
    assert not hasattr(plan, "runs_on")


# ---------------------------------------------------------------------------
# #176 — SecretRef, EvidenceSpec, GateDispositionSpec
# ---------------------------------------------------------------------------


def test_evidence_spec_construction() -> None:
    """EvidenceSpec and supporting types construct correctly."""
    from stagr.core.models import (
        CorrelationSpec,
        EvidenceSpec,
        EvidenceSuccessCondition,
        GateDispositionSpec,
        SecretRef,
    )
    from stagr.core.enums import EvidenceKind

    secret = SecretRef(alias="API_KEY", env_name="OPENAI_API_KEY")
    assert secret.alias == "API_KEY"

    corr = CorrelationSpec(field="pull_request_review_id", value="42")
    cond = EvidenceSuccessCondition(operator="contains", value="Completed")
    ev = EvidenceSpec(
        kind=EvidenceKind.PR_COMMENT,
        selector="pr_comment:codex_review",
        correlation=corr,
        success_condition=cond,
    )
    assert ev.kind is EvidenceKind.PR_COMMENT
    assert ev.selector == "pr_comment:codex_review"

    # GateDispositionSpec separate from EvidenceSpec
    gate = GateDispositionSpec(kind="exit_code", params={"success": 0})
    assert gate.kind == "exit_code"


# ---------------------------------------------------------------------------
# #177 — StageResultSpec and StageResultSignal
# ---------------------------------------------------------------------------


def test_stage_result_signal_requires_head_sha() -> None:
    """StageResultSignal without head_sha raises ValueError."""
    from stagr.core.models import StageResultSignal
    from stagr.core.enums import StageResultState, StageResultConclusion

    try:
        StageResultSignal(
            stage_id="review",
            head_sha="",
            state=StageResultState.COMPLETED,
            conclusion=StageResultConclusion.PASS,
        )
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "head_sha" in str(exc)


def test_stage_result_spec_construction() -> None:
    """StageResultSpec and StageResultSignal construct correctly."""
    from stagr.core.models import (
        StageResultProvenance,
        StageResultSignal,
        StageResultSpec,
    )
    from stagr.core.enums import (
        StageResultConclusion,
        StageResultSignalKind,
        StageResultState,
    )

    prov = StageResultProvenance(publisher_identity="app-install-123")
    spec = StageResultSpec(
        stage_id="review",
        signal_kind=StageResultSignalKind.CHECK_RUN,
        signal_selector="stagr/review",
        provenance=prov,
    )
    assert spec.signal_kind is StageResultSignalKind.CHECK_RUN

    signal = StageResultSignal(
        stage_id="review",
        head_sha="abc123",
        state=StageResultState.COMPLETED,
        conclusion=StageResultConclusion.PASS,
    )
    assert signal.head_sha == "abc123"
    assert signal.conclusion is StageResultConclusion.PASS

    # BLOCKED is distinct from FAILED
    blocked = StageResultConclusion.BLOCKED
    failed = StageResultConclusion.FAILED
    assert blocked is not failed


# ---------------------------------------------------------------------------
# #178 — RenderContext
# ---------------------------------------------------------------------------


def test_render_context_construction() -> None:
    """RenderContext constructs with all required fields; no StageResultSpec[] field."""
    from stagr.core.models import (
        DiscussionPolicy,
        ExternalGate,
        FastPathPolicy,
        MergePolicy,
        NormalizedStage,
        PathMatchSpec,
        RenderContext,
        RouteStageMap,
        RoutingPolicy,
        TrustPolicy,
    )
    from stagr.core.enums import (
        AuthorRole,
        ForkPolicy,
        MergeMode,
        StageGate,
        StageKind,
        StageTrigger,
    )

    stage = NormalizedStage(
        id="review",
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill="code-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )
    trust = TrustPolicy(
        trusted_roles=(AuthorRole.OWNER, AuthorRole.MEMBER, AuthorRole.COLLABORATOR),
        fork_policy=ForkPolicy.DENY,
        human_merge_label="human-merge",
    )
    routing = RoutingPolicy(fast_path=None)
    merge = MergePolicy(
        mode=MergeMode.AUTO,
        blocking_stage_ids=("review",),
        require_head_bound=True,
    )
    ctx = RenderContext(
        stages=(stage,),
        routing_policy=routing,
        merge_policy=merge,
        trust_policy=trust,
        platform="github",
        config_version="1",
    )
    assert ctx.platform == "github"
    assert len(ctx.stages) == 1

    # No StageResultSpec[] field in RenderContext
    assert not hasattr(ctx, "stage_result_specs")
    assert not hasattr(ctx, "result_specs")


def test_render_context_is_immutable() -> None:
    """RenderContext is frozen — mutation raises."""
    from stagr.core.models import MergePolicy, RenderContext, RoutingPolicy, TrustPolicy
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode

    ctx = RenderContext(
        stages=(),
        routing_policy=RoutingPolicy(fast_path=None),
        merge_policy=MergePolicy(
            mode=MergeMode.MANUAL,
            blocking_stage_ids=(),
            require_head_bound=True,
        ),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="1",
    )
    try:
        ctx.platform = "gitlab"  # type: ignore[misc]
        assert False, "Should have raised FrozenInstanceError"
    except Exception as exc:
        assert "frozen" in str(exc).lower() or "cannot" in str(exc).lower()


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

_TESTS = [
    test_enum_string_values,
    test_normalized_stage_construction,
    test_normalized_stage_empty_dependencies,
    test_execution_plan_requires_gate_disposition,
    test_execution_plan_valid,
    test_evidence_spec_construction,
    test_stage_result_signal_requires_head_sha,
    test_stage_result_spec_construction,
    test_render_context_construction,
    test_render_context_is_immutable,
]

if __name__ == "__main__":
    for t in _TESTS:
        try:
            t()
            _ok(t.__name__)
        except Exception as exc:
            _fail(t.__name__, exc)

    if failures:
        print(f"\n{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print(f"\n{len(_TESTS)} tests passed.")
