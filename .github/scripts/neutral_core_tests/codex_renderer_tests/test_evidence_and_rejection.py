"""Tests for OpenAICodexBackendRenderer gate disposition scope, evidence details, and rejection."""
from __future__ import annotations

from neutral_core_tests.codex_renderer_tests.helpers import (
    build_renderer,
    build_review_normalized_stage,
    build_security_normalized_stage,
)


def test_codex_renderer_gate_disposition_scope_is_codex_bot_head_bound() -> None:
    """gate_disposition.scope is FindingScopeSpec(created_by=codex-bot, head_sha=True, invocation_correlation=None)."""
    renderer = build_renderer()
    review_stage = build_review_normalized_stage()
    execution_plan = renderer.render(review_stage)
    scope = execution_plan.gate_disposition.scope
    assert scope is not None, "NO_OPEN_THREADS gate_disposition must have scope set"
    assert scope.created_by == "chatgpt-codex-connector[bot]", (
        f"Expected scope.created_by 'chatgpt-codex-connector[bot]'; got {scope.created_by!r}"
    )
    assert scope.head_sha is True, f"Expected scope.head_sha True; got {scope.head_sha!r}"
    assert scope.invocation_correlation is None


def test_codex_renderer_security_stage_gate_disposition_is_no_open_threads() -> None:
    """SECURITY gate_disposition uses NO_OPEN_THREADS (security marker lacks a clean-pass verdict field)."""
    from stagr.core.enums import GateDispositionKind

    renderer = build_renderer()
    security_stage = build_security_normalized_stage()
    execution_plan = renderer.render(security_stage)
    assert execution_plan.gate_disposition.kind is GateDispositionKind.NO_OPEN_THREADS, (
        f"Expected SECURITY gate_disposition.kind NO_OPEN_THREADS; "
        f"got {execution_plan.gate_disposition.kind!r}"
    )
    scope = execution_plan.gate_disposition.scope
    assert scope is not None and scope.created_by == "chatgpt-codex-connector[bot]", (
        f"Expected SECURITY scope.created_by 'chatgpt-codex-connector[bot]'; got scope={scope!r}"
    )


def test_codex_renderer_review_stage_evidence_success_condition_is_completed() -> None:
    """REVIEW stage evidence uses COMPLETED (design-doc 06: the reviewer finished, regardless of findings)."""
    from stagr.core.enums import EvidenceSuccessCondition

    renderer = build_renderer()
    review_stage = build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    evidence_spec = execution_plan.evidence[0]
    assert evidence_spec.success_condition is EvidenceSuccessCondition.COMPLETED, (
        f"Expected REVIEW stage evidence success_condition COMPLETED (design-doc 06); "
        f"got {evidence_spec.success_condition!r}"
    )


def test_codex_renderer_security_stage_evidence_is_comment_match() -> None:
    """SECURITY stage produces EvidenceSpec with kind == COMMENT_MATCH (not REVIEW_RESULT)."""
    from stagr.core.enums import EvidenceKind

    renderer = build_renderer()
    security_stage = build_security_normalized_stage()

    execution_plan = renderer.render(security_stage)

    assert len(execution_plan.evidence) == 1, (
        f"Expected exactly 1 EvidenceSpec for security stage, "
        f"got {len(execution_plan.evidence)}"
    )
    evidence_spec = execution_plan.evidence[0]
    assert evidence_spec.kind is EvidenceKind.COMMENT_MATCH, (
        f"Expected evidence[0].kind COMMENT_MATCH for security stage, "
        f"got {evidence_spec.kind!r}"
    )


def test_codex_renderer_security_stage_evidence_success_condition_is_match_found() -> None:
    """SECURITY stage EvidenceSpec uses MATCH_FOUND success condition."""
    from stagr.core.enums import EvidenceSuccessCondition

    renderer = build_renderer()
    security_stage = build_security_normalized_stage()

    execution_plan = renderer.render(security_stage)

    evidence_spec = execution_plan.evidence[0]
    assert evidence_spec.success_condition is EvidenceSuccessCondition.MATCH_FOUND, (
        f"Expected SECURITY stage evidence success_condition MATCH_FOUND; "
        f"got {evidence_spec.success_condition!r}"
    )


def test_codex_renderer_security_stage_evidence_selector_is_verified_marker() -> None:
    """SECURITY stage EvidenceSpec.selector is the compound completed-marker expression.

    Empirically grounded: auto-merge.yml.tmpl and gate_behavior.py both require the
    marker prefix AND "status":"completed" — a marker with status="running" must not
    satisfy MATCH_FOUND (gate_behavior.py: "gate: a security review still running blocks").
    The compound selector encodes both requirements: marker prefix + status=completed.
    """
    renderer = build_renderer()
    security_stage = build_security_normalized_stage()

    execution_plan = renderer.render(security_stage)

    evidence_spec = execution_plan.evidence[0]
    assert evidence_spec.selector == "codex-security-review:v1 status=completed", (
        f"Expected evidence selector 'codex-security-review:v1 status=completed' "
        f"(compound expression requiring marker prefix AND status=completed; "
        f"a running-state marker must not match); got {evidence_spec.selector!r}"
    )


def test_codex_renderer_security_stage_evidence_sha_field_is_head_sha() -> None:
    """SECURITY stage CorrelationSpec.sha_field is 'headSha' (the JSON field in the codex-security-review:v1 blob)."""
    renderer = build_renderer()
    security_stage = build_security_normalized_stage()

    execution_plan = renderer.render(security_stage)

    correlation = execution_plan.evidence[0].correlation
    assert correlation.sha_field == "headSha", (
        f"Expected evidence correlation sha_field 'headSha' (field within the "
        f"codex-security-review:v1 JSON blob); got {correlation.sha_field!r}"
    )


def test_codex_renderer_unsupported_stage_kind_raises_value_error() -> None:
    """render() raises ValueError for stage kinds other than REVIEW and SECURITY."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage

    renderer = build_renderer()
    implement_stage = NormalizedStage(
        id="implement",
        kind=StageKind.IMPLEMENT,
        provider="openai",
        backend="codex",
        skill=None,
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.MANUAL,),
        dependencies=(),
    )

    raised = False
    try:
        renderer.render(implement_stage)
    except ValueError:
        raised = True

    assert raised, (
        "Expected ValueError when rendering an IMPLEMENT stage with "
        "OpenAICodexBackendRenderer"
    )


def test_codex_renderer_non_blocking_stage_raises_value_error() -> None:
    """render() raises ValueError for NON_BLOCKING stages (V1 shared-scope requires BLOCKING gate).

    The V1 conservative shared-scope mode sets NO_OPEN_THREADS scoped only by
    createdBy + headSha. If a NON_BLOCKING (advisory) stage were rendered, its
    unresolved findings would count in the shared scope of any co-sharing BLOCKING
    stage, silently turning the advisory stage into a merge gate. The renderer
    rejects NON_BLOCKING stages to enforce the gate-semantics constraint.
    """
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage

    renderer = build_renderer()
    advisory_review_stage = NormalizedStage(
        id="advisory-review",
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill="code-review",
        gate=StageGate.NON_BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )

    raised = False
    try:
        renderer.render(advisory_review_stage)
    except ValueError:
        raised = True

    assert raised, (
        "Expected ValueError when rendering a NON_BLOCKING REVIEW stage with "
        "OpenAICodexBackendRenderer (V1 shared-scope NO_OPEN_THREADS requires "
        "BLOCKING gate semantics)"
    )
