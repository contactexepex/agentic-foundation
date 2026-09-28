"""Phase 1 rendering loop.

Implements ``run_phase1``, which drives the per-stage
BackendRenderer → ExecutionPlan → PlatformRenderer pipeline described in
design-docs/04-render-time-architecture.md.

Phase 1 invariant: routing and merge policy are never read here. The loop
structure enforces this — neither RenderContext.routing_policy nor
RenderContext.merge_policy is accessed. PlatformRenderer Phase 2 methods
(render_routing, render_governance) are never called from this module.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING

from .backend_renderer_registry import BackendRendererNotFoundError, BackendRendererRegistry
from .errors import SecretAliasResolutionError
from .models import ExecutionPlan, RenderContext, SecretRef, StageResultSpec

if TYPE_CHECKING:
    from .platform_renderer import PlatformRenderer


def _resolve_secret_aliases(
    plan: ExecutionPlan,
    provider_name: str,
    provider_config: dict,
) -> ExecutionPlan:
    """Return a new ExecutionPlan with every SecretRef.env_name filled in.

    For each SecretRef in ``plan.required_secrets``, looks up the env_name via
    ``provider_config["providers"][provider_name]["secrets"][alias]``. Raises
    ``SecretAliasResolutionError`` when an alias has no mapping.

    The original plan is not mutated; a new frozen ExecutionPlan is returned
    via ``dataclasses.replace``.
    """
    provider_secrets: dict[str, str] = (
        provider_config
        .get("providers", {})
        .get(provider_name, {})
        .get("secrets", {})
    )

    resolved_secret_refs: list[SecretRef] = []
    for secret_ref in plan.required_secrets:
        env_name = provider_secrets.get(secret_ref.alias)
        if env_name is None:
            raise SecretAliasResolutionError(
                f"No mapping for secret alias {secret_ref.alias!r} on stage "
                f"{plan.stage_id!r} (provider={provider_name!r}). "
                f"Add 'providers.{provider_name}.secrets.{secret_ref.alias}' "
                f"to the provider configuration."
            )
        resolved_secret_refs.append(
            dataclasses.replace(secret_ref, env_name=env_name)
        )

    return dataclasses.replace(
        plan,
        required_secrets=tuple(resolved_secret_refs),
    )


def run_phase1(
    context: RenderContext,
    registry: BackendRendererRegistry,
    platform_renderer: "PlatformRenderer",
    provider_config: dict,
) -> list[StageResultSpec]:
    """Execute Phase 1 of the rendering pipeline for all stages in context.

    For each NormalizedStage in ``context.stages``:

    1. Look up the BackendRenderer in ``registry`` for
       ``(stage.provider, stage.backend)``; raises
       ``BackendRendererNotFoundError`` when none is found.
    2. Call ``backend_renderer.render(stage)`` to get an ``ExecutionPlan``
       with alias-only ``SecretRef`` values (``env_name`` not yet set).
    3. Resolve each ``SecretRef.alias`` from
       ``provider_config["providers"][stage.provider]["secrets"][alias]``;
       raises ``SecretAliasResolutionError`` when an alias has no mapping,
       before the PlatformRenderer is called.
    4. Call ``platform_renderer.render_stage(resolved_plan, stage, context)``
       to get a ``StageResultSpec``.
    5. Collect and return all ``StageResultSpec`` objects.

    Phase 1 invariant: ``render_routing`` and ``render_governance`` are never
    called here. ``context.routing_policy`` and ``context.merge_policy`` are
    never read.

    Returns a list of length ``len(context.stages)`` in stage order.
    """
    stage_result_specs: list[StageResultSpec] = []

    for stage in context.stages:
        backend_renderer = registry.get(stage.provider, stage.backend)

        unresolved_plan: ExecutionPlan = backend_renderer.render(stage)

        resolved_plan: ExecutionPlan = _resolve_secret_aliases(
            unresolved_plan, stage.provider, provider_config
        )

        stage_result_spec: StageResultSpec = platform_renderer.render_stage(
            resolved_plan, stage, context
        )
        stage_result_specs.append(stage_result_spec)

    return stage_result_specs
