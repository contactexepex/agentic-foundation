"""Tests for the OpenAICodexBackendRenderer (issue #190).

Covers: invocation kind (PR_COMMENT), required secret alias contract
(TRUSTED_COMMENTER_TOKEN, env_name=None), gate disposition kind
(EXPLICIT_PASS_MARKER — Spike B result), evidence presence and kind
(REVIEW_RESULT), head-SHA correlation, Protocol conformance, renderer
identity (provider + backend), and stage-kind dispatch (review command vs
security review command).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _build_review_normalized_stage():
    """Return a valid NormalizedStage representing a code-review stage."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage

    return NormalizedStage(
        id="review",
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill="code-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
        dependencies=(),
    )


def _build_security_normalized_stage():
    """Return a valid NormalizedStage representing a security-review stage."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage

    return NormalizedStage(
        id="security",
        kind=StageKind.SECURITY,
        provider="openai",
        backend="codex",
        skill="security-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
        dependencies=(),
    )


def _build_renderer():
    """Return an OpenAICodexBackendRenderer instance."""
    from stagr.core.renderers.openai_codex_backend_renderer import (
        OpenAICodexBackendRenderer,
    )

    return OpenAICodexBackendRenderer()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_codex_renderer_invocation_kind_is_pr_comment() -> None:
    """render() returns an ExecutionPlan with invocation.kind == PR_COMMENT."""
    from stagr.core.enums import InvocationKind

    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    assert execution_plan.invocation.kind is InvocationKind.PR_COMMENT, (
        f"Expected invocation.kind PR_COMMENT, got {execution_plan.invocation.kind!r}"
    )


def test_codex_renderer_required_secret_alias_and_no_env_name() -> None:
    """required_secrets has exactly one SecretRef with alias TRUSTED_COMMENTER_TOKEN and env_name None."""
    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    assert len(execution_plan.required_secrets) == 1, (
        f"Expected exactly 1 required secret, got {len(execution_plan.required_secrets)}"
    )
    secret_ref = execution_plan.required_secrets[0]
    assert secret_ref.alias == "TRUSTED_COMMENTER_TOKEN", (
        f"Expected alias 'TRUSTED_COMMENTER_TOKEN', got {secret_ref.alias!r}"
    )
    assert secret_ref.env_name is None, (
        f"BackendRenderer must not set SecretRef.env_name; "
        f"got env_name={secret_ref.env_name!r} for alias={secret_ref.alias!r}"
    )


def test_codex_renderer_gate_disposition_kind_is_explicit_pass_marker() -> None:
    """gate_disposition.kind == EXPLICIT_PASS_MARKER (Spike B: thread correlation not reliably observable)."""
    from stagr.core.enums import GateDispositionKind

    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    assert execution_plan.gate_disposition.kind is GateDispositionKind.EXPLICIT_PASS_MARKER, (
        f"Expected gate_disposition.kind EXPLICIT_PASS_MARKER (Spike B result), "
        f"got {execution_plan.gate_disposition.kind!r}"
    )


def test_codex_renderer_evidence_has_one_review_result_spec() -> None:
    """evidence contains exactly one EvidenceSpec with kind == REVIEW_RESULT."""
    from stagr.core.enums import EvidenceKind

    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    assert len(execution_plan.evidence) == 1, (
        f"Expected exactly 1 EvidenceSpec, got {len(execution_plan.evidence)}"
    )
    evidence_spec = execution_plan.evidence[0]
    assert evidence_spec.kind is EvidenceKind.REVIEW_RESULT, (
        f"Expected evidence[0].kind REVIEW_RESULT, got {evidence_spec.kind!r}"
    )


def test_codex_renderer_evidence_head_sha_correlation_is_true() -> None:
    """evidence[0].correlation.head_sha is True (evidence must bind to the current head commit)."""
    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    head_sha_correlation = execution_plan.evidence[0].correlation
    assert head_sha_correlation.head_sha is True, (
        f"Expected evidence[0].correlation.head_sha True, "
        f"got {head_sha_correlation.head_sha!r}"
    )


def test_codex_renderer_protocol_conformance() -> None:
    """isinstance(renderer, BackendRenderer) passes (runtime Protocol check)."""
    from stagr.core.backend_renderer import BackendRenderer

    renderer = _build_renderer()

    assert isinstance(renderer, BackendRenderer), (
        f"OpenAICodexBackendRenderer must satisfy the BackendRenderer Protocol; "
        f"isinstance check failed for type {type(renderer)}"
    )


def test_codex_renderer_provider_and_backend_match_config() -> None:
    """renderer.provider == 'openai' and renderer.backend matches the BACKEND_CODEX constant."""
    from stagr.render.constants import BACKEND_CODEX

    renderer = _build_renderer()

    assert renderer.provider == "openai", (
        f"Expected provider 'openai', got {renderer.provider!r}"
    )
    assert renderer.backend == BACKEND_CODEX, (
        f"Expected backend '{BACKEND_CODEX}' (from BACKEND_CODEX constant), "
        f"got {renderer.backend!r}"
    )


def test_codex_renderer_review_stage_posts_codex_review_command() -> None:
    """A REVIEW stage invocation.params['body'] contains '@codex review' (not the security command)."""
    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    comment_body = execution_plan.invocation.params.get("body", "")
    assert "@codex review" in comment_body, (
        f"Expected invocation body to contain '@codex review', got {comment_body!r}"
    )
    assert "security" not in comment_body, (
        f"REVIEW stage must not post the security review command; got {comment_body!r}"
    )


def test_codex_renderer_security_stage_posts_security_review_command() -> None:
    """A SECURITY stage invocation.params['body'] contains '@codex security review'."""
    renderer = _build_renderer()
    security_stage = _build_security_normalized_stage()

    execution_plan = renderer.render(security_stage)

    comment_body = execution_plan.invocation.params.get("body", "")
    assert "@codex security review" in comment_body, (
        f"Expected invocation body to contain '@codex security review', "
        f"got {comment_body!r}"
    )


def test_codex_renderer_gate_disposition_has_no_scope() -> None:
    """gate_disposition.scope is None for EXPLICIT_PASS_MARKER (scope required only for NO_OPEN_THREADS)."""
    renderer = _build_renderer()
    review_stage = _build_review_normalized_stage()

    execution_plan = renderer.render(review_stage)

    assert execution_plan.gate_disposition.scope is None, (
        f"EXPLICIT_PASS_MARKER gate_disposition must have scope=None; "
        f"got {execution_plan.gate_disposition.scope!r}"
    )
