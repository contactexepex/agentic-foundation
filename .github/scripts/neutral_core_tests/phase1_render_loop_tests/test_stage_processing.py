"""Tests for Phase 1 stage processing happy paths (issue #193).

Covers: two-stage output order, result count matching stage count, empty
stage list, and multiple secrets fully resolved.
"""
from __future__ import annotations

from neutral_core_tests.phase1_render_loop_tests.helpers import (
    build_execution_plan,
    build_minimal_render_context,
    build_stage,
    build_stage_result_spec,
    TrackingPlatformRenderer,
)


def test_phase1_two_stages_returns_two_specs() -> None:
    """run_phase1 with 2 stages returns exactly 2 StageResultSpecs in stage order."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage_alpha = build_stage("stage-alpha")
    stage_beta = build_stage("stage-beta")
    render_context = build_minimal_render_context([stage_alpha, stage_beta])

    class _IdentityBackendRenderer:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage):
            return build_execution_plan(stage.id)

    registry = BackendRendererRegistry()
    registry.register(_IdentityBackendRenderer())
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    result = run_phase1(render_context, registry, platform_renderer, provider_config)

    assert len(result) == 2, (
        f"Expected 2 StageResultSpecs for 2 stages; got {len(result)}"
    )
    assert result[0].stage_id == "stage-alpha", (
        f"First spec must have stage_id 'stage-alpha'; got {result[0].stage_id!r}"
    )
    assert result[1].stage_id == "stage-beta", (
        f"Second spec must have stage_id 'stage-beta'; got {result[1].stage_id!r}"
    )


def test_phase1_result_count_equals_stage_count() -> None:
    """Returned list length equals len(context.stages) for any number of stages."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stages = [build_stage(f"stage-{index}") for index in range(5)]
    render_context = build_minimal_render_context(stages)

    class _IdentityBackendRenderer:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage):
            return build_execution_plan(stage.id)

    registry = BackendRendererRegistry()
    registry.register(_IdentityBackendRenderer())
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    result = run_phase1(render_context, registry, platform_renderer, provider_config)

    assert len(result) == len(stages), (
        f"Expected {len(stages)} specs; got {len(result)}"
    )


def test_phase1_empty_stages_returns_empty_list() -> None:
    """run_phase1 with zero stages returns an empty list."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    render_context = build_minimal_render_context([])
    registry = BackendRendererRegistry()
    platform_renderer = TrackingPlatformRenderer()
    provider_config: dict = {}

    result = run_phase1(render_context, registry, platform_renderer, provider_config)

    assert result == [], (
        f"Expected empty list for zero stages; got {result!r}"
    )


def test_phase1_provider_api_key_resolved_from_api_key_secret() -> None:
    """PROVIDER_API_KEY alias falls back to providers.<provider>.api_key_secret when no secrets map entry exists."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-api-key")
    render_context = build_minimal_render_context([stage])

    plan_with_provider_api_key = build_execution_plan(
        "stage-api-key", secret_aliases=("PROVIDER_API_KEY",)
    )

    class _BackendRendererWithProviderApiKey:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_provider_api_key

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererWithProviderApiKey())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    # api_key_secret field present; no explicit secrets map for PROVIDER_API_KEY.
    provider_config = {
        "providers": {
            "testprovider": {
                "api_key_secret": "TESTPROVIDER_API_KEY",
            },
        },
    }

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"PROVIDER_API_KEY": "TESTPROVIDER_API_KEY"}, (
        f"PROVIDER_API_KEY must resolve via api_key_secret; got {env_names!r}"
    )


def test_phase1_explicit_secrets_map_takes_precedence_over_api_key_secret() -> None:
    """An explicit secrets map entry beats the api_key_secret fallback for PROVIDER_API_KEY."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-precedence")
    render_context = build_minimal_render_context([stage])

    plan_with_provider_api_key = build_execution_plan(
        "stage-precedence", secret_aliases=("PROVIDER_API_KEY",)
    )

    class _BackendRendererExplicit:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_provider_api_key

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererExplicit())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    # Both explicit secrets map and api_key_secret present — explicit map must win.
    provider_config = {
        "providers": {
            "testprovider": {
                "api_key_secret": "FALLBACK_KEY",
                "secrets": {
                    "PROVIDER_API_KEY": "EXPLICIT_API_KEY",
                },
            },
        },
    }

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"PROVIDER_API_KEY": "EXPLICIT_API_KEY"}, (
        f"Explicit secrets map must take precedence over api_key_secret; got {env_names!r}"
    )


def test_phase1_multiple_secrets_all_resolved() -> None:
    """All SecretRef entries in the plan are resolved when the mapping covers all aliases."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-multi-secret")
    render_context = build_minimal_render_context([stage])

    plan_with_two_aliases = build_execution_plan(
        "stage-multi-secret",
        secret_aliases=("FIRST_KEY", "SECOND_KEY"),
    )

    class _BackendRendererWithTwoSecrets:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_two_aliases

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererWithTwoSecrets())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    provider_config = {
        "providers": {
            "testprovider": {
                "secrets": {
                    "FIRST_KEY": "FIRST_ENV_VAR",
                    "SECOND_KEY": "SECOND_ENV_VAR",
                },
            },
        },
    }

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"FIRST_KEY": "FIRST_ENV_VAR", "SECOND_KEY": "SECOND_ENV_VAR"}, (
        f"Unexpected resolved env_names mapping: {env_names!r}"
    )


def test_phase1_provider_api_key_resolves_to_provider_default_when_providers_absent() -> None:
    """PROVIDER_API_KEY resolves to the provider's established default when no providers config."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-anthropic-default", provider="anthropic")
    render_context = build_minimal_render_context([stage])

    plan_with_provider_api_key = build_execution_plan(
        "stage-anthropic-default", secret_aliases=("PROVIDER_API_KEY",)
    )

    class _AnthropicBackendRenderer:
        provider = "anthropic"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_provider_api_key

    registry = BackendRendererRegistry()
    registry.register(_AnthropicBackendRenderer())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    provider_config: dict = {}  # no providers block — provider default must apply

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"PROVIDER_API_KEY": "ANTHROPIC_API_KEY"}, (
        f"PROVIDER_API_KEY for anthropic must resolve to ANTHROPIC_API_KEY; got {env_names!r}"
    )


def test_phase1_trusted_commenter_token_resolves_to_remediation_token_when_platform_absent() -> None:
    """TRUSTED_COMMENTER_TOKEN resolves to REMEDIATION_TOKEN when no platform.auth config."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-commenter-default")
    render_context = build_minimal_render_context([stage])

    plan_with_commenter_token = build_execution_plan(
        "stage-commenter-default", secret_aliases=("TRUSTED_COMMENTER_TOKEN",)
    )

    class _BackendRendererWithCommenterToken:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_commenter_token

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererWithCommenterToken())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    provider_config: dict = {}  # no platform.auth — default must apply

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"TRUSTED_COMMENTER_TOKEN": "REMEDIATION_TOKEN"}, (
        f"TRUSTED_COMMENTER_TOKEN must resolve to REMEDIATION_TOKEN when platform absent; got {env_names!r}"
    )


def test_phase1_platform_auth_token_secret_overrides_trusted_commenter_default() -> None:
    """platform.auth.token_secret overrides the REMEDIATION_TOKEN default for TRUSTED_COMMENTER_TOKEN."""
    from stagr.core.render_loop import run_phase1
    from stagr.core.backend_renderer_registry import BackendRendererRegistry

    stage = build_stage("stage-commenter-override")
    render_context = build_minimal_render_context([stage])

    plan_with_commenter_token = build_execution_plan(
        "stage-commenter-override", secret_aliases=("TRUSTED_COMMENTER_TOKEN",)
    )

    class _BackendRendererOverride:
        provider = "testprovider"
        backend = "testbackend"

        def render(self, stage_arg):
            return plan_with_commenter_token

    registry = BackendRendererRegistry()
    registry.register(_BackendRendererOverride())

    received_plans: list = []

    class _CapturingPlatformRenderer(TrackingPlatformRenderer):
        def render_stage(self, plan, stage_arg, render_context_arg):
            received_plans.append(plan)
            return build_stage_result_spec(stage_arg.id)

    provider_config = {
        "platform": {
            "auth": {
                "token_secret": "MY_CUSTOM_PAT",
            },
        },
    }

    run_phase1(render_context, registry, _CapturingPlatformRenderer(), provider_config)

    assert received_plans, "PlatformRenderer.render_stage was not called"
    resolved_plan = received_plans[0]
    env_names = {ref.alias: ref.env_name for ref in resolved_plan.required_secrets}
    assert env_names == {"TRUSTED_COMMENTER_TOKEN": "MY_CUSTOM_PAT"}, (
        f"platform.auth.token_secret must override REMEDIATION_TOKEN default; got {env_names!r}"
    )
