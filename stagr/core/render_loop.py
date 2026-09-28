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

from .backend_renderer_registry import BackendRendererRegistry
from .models import ExecutionPlan, NormalizedStage, RenderContext, SecretRef, StageResultSpec

if TYPE_CHECKING:
    from .platform_renderer import PlatformRenderer


_PROVIDER_API_KEY_ALIAS = "PROVIDER_API_KEY"


def _resolve_secret_aliases(
    plan: ExecutionPlan,
    provider_name: str,
    provider_config: dict,
) -> ExecutionPlan:
    """Return a new ExecutionPlan with every SecretRef.env_name filled in.

    Resolution precedence for each SecretRef.alias (design-doc 03, V-S12):

    1. Explicit mapping: ``provider_config["providers"][provider_name]["secrets"][alias]``
    2. Provider ``api_key_secret`` field when alias is ``PROVIDER_API_KEY``
    3. Convention: alias is itself the platform secret name (env_name = alias).
       The ``secrets`` block is optional in V1; when omitted, aliases ARE the
       platform secret names.

    The original plan is not mutated; a new frozen ExecutionPlan is returned
    via ``dataclasses.replace``.
    """
    provider_entry: dict = (
        provider_config
        .get("providers", {})
        .get(provider_name, {})
    )
    provider_secrets: dict[str, str] = provider_entry.get("secrets", {})
    api_key_secret: str | None = provider_entry.get("api_key_secret")

    resolved_secret_refs: list[SecretRef] = []
    for secret_ref in plan.required_secrets:
        # 1. Explicit alias → env_name mapping in the provider secrets block.
        env_name: str | None = provider_secrets.get(secret_ref.alias)

        # 2. Semantic mapping: PROVIDER_API_KEY → api_key_secret field.
        if env_name is None and secret_ref.alias == _PROVIDER_API_KEY_ALIAS and api_key_secret:
            env_name = api_key_secret

        # 3. Convention fallback: alias is the platform secret name.
        if env_name is None:
            env_name = secret_ref.alias

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
    3. Resolve each ``SecretRef.alias`` via the three-level precedence in
       ``_resolve_secret_aliases`` (explicit mapping → ``api_key_secret`` →
       convention), before the PlatformRenderer is called.
    4. Call ``platform_renderer.render_stage(resolved_plan, stage, context)``
       to get a ``StageResultSpec``.
    5. Collect and return all ``StageResultSpec`` objects.

    Phase 1 invariant: ``render_routing`` and ``render_governance`` are never
    called here. ``context.routing_policy`` and ``context.merge_policy`` are
    never read.

    Returns a list of length ``len(context.stages)`` in stage order.
    """
    # Preparation pass: validate every plan and resolve every alias before any render_stage call.
    # This prevents a partially-rendered pipeline when a later stage has an unresolvable alias —
    # render_stage is a file-producing operation (e.g. writing a workflow file), so atomicity
    # requires all static checks to succeed first.
    prepared: list[tuple[ExecutionPlan, NormalizedStage]] = []
    for stage in context.stages:
        backend_renderer = registry.get(stage.provider, stage.backend)

        unresolved_plan: ExecutionPlan = backend_renderer.render(stage)
        if unresolved_plan.stage_id != stage.id:
            raise ValueError(
                f"BackendRenderer returned an ExecutionPlan with stage_id "
                f"{unresolved_plan.stage_id!r} but was called for stage "
                f"{stage.id!r}; the renderer must return a plan for the "
                f"stage it received."
            )

        resolved_plan: ExecutionPlan = _resolve_secret_aliases(
            unresolved_plan, stage.provider, provider_config
        )
        prepared.append((resolved_plan, stage))

    # Rendering pass: only reached when all stages have a validated, fully-resolved plan.
    stage_result_specs: list[StageResultSpec] = []
    for resolved_plan, stage in prepared:
        stage_result_spec: StageResultSpec = platform_renderer.render_stage(
            resolved_plan, stage, context
        )
        if stage_result_spec.stage_id != stage.id:
            raise ValueError(
                f"PlatformRenderer returned a StageResultSpec with stage_id "
                f"{stage_result_spec.stage_id!r} but was called for stage "
                f"{stage.id!r}; the renderer must return a result for the "
                f"stage it received."
            )
        stage_result_specs.append(stage_result_spec)

    return stage_result_specs
