"""Tests for SecretRef, EvidenceSpec, CorrelationSpec, and GateDispositionSpec (issue #176)."""
from __future__ import annotations


def test_evidence_spec_construction() -> None:
    """EvidenceSpec and supporting types construct correctly."""
    from stagr.core.models import (
        CorrelationSpec,
        EvidenceSpec,
        FindingScopeSpec,
        GateDispositionSpec,
        SecretRef,
    )
    from stagr.core.enums import (
        EvidenceKind,
        EvidenceSuccessCondition,
        GateDispositionKind,
    )

    # BackendRenderer declares alias only — env_name is None until Phase 1 resolves it
    secret = SecretRef(alias="PROVIDER_API_KEY")
    assert secret.alias == "PROVIDER_API_KEY"
    assert secret.env_name is None
    # After Phase 1 resolution, env_name is filled in
    resolved = SecretRef(alias="PROVIDER_API_KEY", env_name="OPENAI_API_KEY")
    assert resolved.env_name == "OPENAI_API_KEY"

    # CorrelationSpec: head_sha + sha_field (not field + value)
    corr = CorrelationSpec(head_sha=True, sha_field="first_code_block_sha")
    assert corr.head_sha is True

    # EvidenceSuccessCondition is an enum, not a dataclass
    cond = EvidenceSuccessCondition.COMPLETED
    ev = EvidenceSpec(
        kind=EvidenceKind.REVIEW_RESULT,
        selector="codex_review:stagr",
        correlation=corr,
        success_condition=cond,
    )
    assert ev.kind is EvidenceKind.REVIEW_RESULT
    assert ev.selector == "codex_review:stagr"
    assert ev.success_condition is EvidenceSuccessCondition.COMPLETED

    # GateDispositionSpec with ALWAYS_PASS needs no scope
    gate = GateDispositionSpec(kind=GateDispositionKind.ALWAYS_PASS, selector="")
    assert gate.kind is GateDispositionKind.ALWAYS_PASS
    assert gate.scope is None

    # GateDispositionSpec with NO_OPEN_THREADS requires scope
    scope = FindingScopeSpec(
        created_by="codex-bot",
        head_sha=True,
        invocation_correlation="review-run-id",
    )
    gate_scoped = GateDispositionSpec(
        kind=GateDispositionKind.NO_OPEN_THREADS,
        selector="",
        scope=scope,
    )
    assert gate_scoped.scope is not None
    assert gate_scoped.scope.created_by == "codex-bot"

    # NO_OPEN_THREADS without scope raises ValueError
    try:
        GateDispositionSpec(kind=GateDispositionKind.NO_OPEN_THREADS, selector="")
        assert False, "Should have raised ValueError"
    except ValueError as exc:
        assert "NO_OPEN_THREADS" in str(exc) or "scope" in str(exc)
