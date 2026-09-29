"""Tests for V-S08: Platform invocation compatibility.

V-S08 verifies that the platform supports every InvocationKind produced by
the configured backend renderers.
"""
from __future__ import annotations

from neutral_core_tests.static_validator_tests.helpers import (
    make_fresh_registry,
    make_normalized_stage,
    StubBackendRendererCiComponent,
    StubBackendRendererPrComment,
)


def test_v_s08_passes_when_invocation_kind_supported() -> None:
    """V-S08 raises no error when the backend's invocation kind is in the supported set."""
    from stagr.core.enums import InvocationKind
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = make_fresh_registry()
    renderer = StubBackendRendererPrComment()
    registry.register(renderer)
    stage = make_normalized_stage("review-stage")

    supported_kinds = frozenset({InvocationKind.PR_COMMENT})
    validate_platform_invocation_compatibility((stage,), registry, supported_kinds)


def test_v_s08_raises_for_unsupported_invocation_kind() -> None:
    """V-S08 raises StaticValidationError when CI_COMPONENT is used on a platform that lacks support."""
    from stagr.core.enums import InvocationKind
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = make_fresh_registry()
    renderer = StubBackendRendererCiComponent()
    registry.register(renderer)
    stage = make_normalized_stage(
        "implement-stage",
        provider="stub-provider",
        backend="ci-component-backend",
    )

    # Platform supports only PR_COMMENT — CI_COMPONENT is not in the set.
    supported_kinds = frozenset({InvocationKind.PR_COMMENT, InvocationKind.API_CALL})

    try:
        validate_platform_invocation_compatibility((stage,), registry, supported_kinds)
        assert False, "Expected StaticValidationError but no exception was raised"  # noqa: B011
    except StaticValidationError as error:
        error_message = str(error)
        assert "V-S08" in error_message, (
            f"Error message must contain 'V-S08'; got: {error_message!r}"
        )
        assert "ci_component" in error_message, (
            f"Error message must name the unsupported kind; got: {error_message!r}"
        )


def test_v_s08_names_stage_in_error() -> None:
    """V-S08 error message includes the stage id."""
    from stagr.core.enums import InvocationKind
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = make_fresh_registry()
    renderer = StubBackendRendererCiComponent()
    registry.register(renderer)
    stage = make_normalized_stage(
        "named-stage",
        provider="stub-provider",
        backend="ci-component-backend",
    )

    try:
        validate_platform_invocation_compatibility(
            (stage,), registry, frozenset({InvocationKind.PR_COMMENT})
        )
        assert False, "Expected StaticValidationError"  # noqa: B011
    except StaticValidationError as error:
        assert "named-stage" in str(error), (
            f"Error must name the stage id; got: {str(error)!r}"
        )


def test_v_s08_github_renderer_declares_only_what_it_really_renders() -> None:
    """GitHubPlatformRenderer declares PR_COMMENT and nothing else: the only kind it performs."""
    from stagr.core.enums import InvocationKind
    from stagr.platforms.github.renderer import GitHubPlatformRenderer

    assert GitHubPlatformRenderer.SUPPORTED_INVOCATION_KINDS == frozenset({InvocationKind.PR_COMMENT}), (
        "GitHubPlatformRenderer must declare exactly {PR_COMMENT}; other kinds render placeholder steps"
    )


def test_v_s08_rejects_implement_stage_on_github() -> None:
    """The shipped Claude Code implement backend (CI_COMPONENT) is rejected for GitHub; Codex review passes."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage, StaticValidationError
    from stagr.core.renderers.anthropic_claude_backend_renderer import AnthropicClaudeBackendRenderer
    from stagr.core.renderers.openai_codex_backend_renderer import OpenAICodexBackendRenderer
    from stagr.core.static_validator import validate_platform_invocation_compatibility
    from stagr.platforms.github.renderer import GitHubPlatformRenderer

    registry = make_fresh_registry()
    registry.register(AnthropicClaudeBackendRenderer())
    registry.register(OpenAICodexBackendRenderer())
    supported_kinds = GitHubPlatformRenderer.SUPPORTED_INVOCATION_KINDS

    def make_stage(stage_id: str, kind: StageKind, provider: str, backend: str, gate: StageGate) -> NormalizedStage:
        return NormalizedStage(
            id=stage_id, kind=kind, provider=provider, backend=backend, skill=None,
            gate=gate, triggers=(StageTrigger.MANUAL,), dependencies=(),
        )

    review_stage = make_stage("review", StageKind.REVIEW, "openai", "codex", StageGate.BLOCKING)
    validate_platform_invocation_compatibility((review_stage,), registry, supported_kinds)

    implement_stage = make_stage(
        "implement", StageKind.IMPLEMENT, "anthropic", "claude-code-action", StageGate.NON_BLOCKING
    )
    try:
        validate_platform_invocation_compatibility((implement_stage,), registry, supported_kinds)
    except StaticValidationError as error:
        assert "V-S08" in str(error) and "implement" in str(error), str(error)
        return
    raise AssertionError("expected V-S08 to reject the CI_COMPONENT implement stage on GitHub")
