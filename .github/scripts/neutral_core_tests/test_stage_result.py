"""Tests for StageResultSpec and StageResultSignal (issue #177)."""
from __future__ import annotations


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
    assert StageResultConclusion.BLOCKED is not StageResultConclusion.FAILED
