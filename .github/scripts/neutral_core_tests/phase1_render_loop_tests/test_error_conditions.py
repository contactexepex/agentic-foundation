"""Tests for Phase 1 error conditions (issue #193).

Covers: missing BackendRenderer raises BackendRendererNotFoundError; unresolvable
secret alias raises SecretAliasResolutionError before any PlatformRenderer call.
"""
from __future__ import annotations

from neutral_core_tests.phase1_render_loop_tests.helpers import (
    build_execution_plan,
    build_minimal_render_context,
    build_stage,
    build_stage_result_spec,
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


def test_phase1_alias_with_no_mapping_resolves_by_convention() -> None:
    """An alias absent from the secrets map resolves by convention (alias == env_name).

    Design-doc 03: the secrets block is optional in V1 when convention-based
    resolution is sufficient (alias == platform secret name).  run_phase1 must
    NOT raise SecretAliasResolutionError for an unmapped alias; instead it
    passes the alias through as the env_name so operators do not need to
    duplicate identity mappings.
    """
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-convention")
    render_context = build_minimal_render_context([stage])

    plan_with_unmapped_alias = build_execution_plan(
        "stage-convention", secret_aliases=("MY_CUSTOM_SECRET",)
    )

    class _BackendRendererWithUnmappedAlias:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_unmapped_alias

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererWithUnmappedAlias())

    received_plans: list = []

    class _CapturingRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    provider_config: dict = {}  # no secrets mapping — convention applies

    run_phase1(render_context, registry, _CapturingRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage must be called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"MY_CUSTOM_SECRET": "MY_CUSTOM_SECRET"}, (
        f"Convention fallback must set env_name = alias; got {env_names!r}"
    )


def test_phase1_second_stage_plan_mismatch_prevents_all_render_stage_calls() -> None:
    """Preparation pass fails before any render_stage when a later stage's plan has wrong stage_id."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage_ok = build_stage("stage-ok")
    stage_bad = build_stage("stage-bad")
    render_context = build_minimal_render_context([stage_ok, stage_bad])

    class _SecondStageMismatchBackendRenderer:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            if stage_arg.id == "stage-bad":
                # Return a plan with the wrong stage_id to trigger a ValueError
                # in the preparation pass before any render_stage call.
                return build_execution_plan("wrong-stage-id")
            return build_execution_plan(stage_arg.id)

    registry = BackendRendererRegistry()
    registry.register(_SecondStageMismatchBackendRenderer())
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    raised = False
    try:
        run_phase1(render_context, registry, platform_renderer, provider_config)
    except ValueError:
        raised = True

    assert raised, (
        "Expected ValueError when second stage's BackendRenderer returns a plan "
        "with the wrong stage_id"
    )
    assert not platform_renderer.render_stage_calls, (
        "PlatformRenderer.render_stage must NOT be called for any stage when the "
        "preparation pass fails; was called "
        f"{len(platform_renderer.render_stage_calls)} time(s)"
    )


def test_phase1_mismatched_plan_stage_id_raises_value_error() -> None:
    """run_phase1 raises ValueError when BackendRenderer returns plan for wrong stage."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("correct-stage-id")
    render_context = build_minimal_render_context([stage])

    class _MismatchingBackendRenderer:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return build_execution_plan("wrong-stage-id")

    registry = BackendRendererRegistry()
    registry.register(_MismatchingBackendRenderer())
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    raised = False
    try:
        run_phase1(render_context, registry, platform_renderer, provider_config)
    except ValueError:
        raised = True

    assert raised, (
        "Expected ValueError when BackendRenderer returns an ExecutionPlan "
        "with a stage_id that does not match the stage being processed"
    )
    assert not platform_renderer.render_stage_calls, (
        "PlatformRenderer.render_stage must NOT be called when plan stage_id mismatch is "
        f"detected; was called {len(platform_renderer.render_stage_calls)} time(s)"
    )


def test_phase1_mismatched_stage_result_id_raises_value_error() -> None:
    """run_phase1 raises ValueError when PlatformRenderer returns wrong stage_id."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    from neutral_core_tests.phase1_render_loop_tests.helpers import (
        build_execution_plan,
        build_stage_result_spec,
    )

    stage = build_stage("correct-stage-id")
    render_context = build_minimal_render_context([stage])

    class _MismatchingPlatformRenderer:
        def render_stage(self, plan, stage_arg, ctx):
            return build_stage_result_spec("wrong-stage-id")

        def render_routing(self, ctx) -> None:
            pass

        def render_governance(self, specs, ctx) -> None:
            pass

    class _IdentityBackendRenderer:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return build_execution_plan(stage_arg.id)

    registry = BackendRendererRegistry()
    registry.register(_IdentityBackendRenderer())
    provider_config: dict = {}

    raised = False
    try:
        run_phase1(render_context, registry, _MismatchingPlatformRenderer(), provider_config)
    except ValueError:
        raised = True

    assert raised, (
        "Expected ValueError when PlatformRenderer returns a StageResultSpec "
        "with a stage_id that does not match the stage being processed"
    )
