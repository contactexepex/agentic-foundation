"""Shared builders for codex renderer tests."""
from __future__ import annotations


def build_review_normalized_stage():
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


def build_security_normalized_stage():
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


def build_renderer():
    """Return an OpenAICodexBackendRenderer instance."""
    from stagr.core.renderers.openai_codex_backend_renderer import (
        OpenAICodexBackendRenderer,
    )

    return OpenAICodexBackendRenderer()
