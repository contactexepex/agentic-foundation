"""Tests for NormalizedStage (issue #174)."""
from __future__ import annotations


def test_normalized_stage_construction() -> None:
    """NormalizedStage round-trips correctly; no enabled field; model and skill may be None."""
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
    assert stage.skill == "code-review"
    assert stage.model is None
    assert stage.gate is StageGate.BLOCKING
    assert len(stage.triggers) == 2

    # IMPLEMENT-type stage: skill is None, gate is NON_BLOCKING
    implement_stage = NormalizedStage(
        id="implement-claude",
        kind=StageKind.IMPLEMENT,
        provider="anthropic",
        backend="claude-code",
        skill=None,
        gate=StageGate.NON_BLOCKING,
        triggers=(StageTrigger.MANUAL,),
        dependencies=(),
    )
    assert implement_stage.skill is None
    assert implement_stage.gate is StageGate.NON_BLOCKING

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
