"""Tests for Phase 1 error conditions (issue #193).

Covers: missing BackendRenderer raises BackendRendererNotFoundError; unresolvable
secret alias raises SecretAliasResolutionError before any PlatformRenderer call.
"""
from __future__ import annotations

from neutral_core_tests.phase1_render_loop_tests.helpers import (
    build_execution_plan,
    build_minimal_render_context,
    build_stage,
    TrackingPlatformRenderer,
)


def test_phase1_missing_backend_raises_backend_renderer_not_found_error() -> None:
    """run_phase1 raises BackendRendererNotFoundError when the registry has no match."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import (
        BackendRendererRegistry,
        BackendRendererNotFoundError,
    )

    stage = build_stage("stage-missing", provider="unknown-provider", backend="unknown-backend")
    render_context = build_minimal_render_context([stage])
    registry = BackendRendererRegistry()  # nothing registered
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    raised = False
    try:
        run_phase1(render_context, registry, platform_renderer, provider_config)
    except BackendRendererNotFoundError:
        raised = True

    assert raised, (
        "Expected BackendRendererNotFoundError when no renderer is registered "
        "for (provider, backend)"
    )


def test_phase1_unresolvable_alias_raises_before_platform_renderer() -> None:
    """run_phase1 raises SecretAliasResolutionError and does NOT call PlatformRenderer."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.errors import SecretAliasResolutionError
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-secret")
    render_context = build_minimal_render_context([stage])

    plan_with_unresolvable_alias = build_execution_plan(
        "stage-secret", secret_aliases=("MISSING_API_KEY",)
    )

    class _BackendRendererWithMissingSecret:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_unresolvable_alias

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererWithMissingSecret())
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}  # no secrets mapping at all

    raised = False
    try:
        run_phase1(render_context, registry, platform_renderer, provider_config)
    except SecretAliasResolutionError:
        raised = True

    assert raised, (
        "Expected SecretAliasResolutionError when alias has no mapping in provider_config"
    )
    assert not platform_renderer.render_stage_calls, (
        "PlatformRenderer.render_stage must NOT be called when alias resolution fails; "
        f"was called {len(platform_renderer.render_stage_calls)} time(s)"
    )
