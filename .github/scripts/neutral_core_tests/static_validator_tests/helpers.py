"""Shared builder functions and stub renderers for static validator tests.

All per-check test modules in this sub-package import from here to avoid
duplicating stub definitions.
"""
from __future__ import annotations


def make_normalized_stage(
    stage_id: str,
    provider: str = "stub-provider",
    backend: str = "stub-backend",
    dependencies: tuple[str, ...] = (),
):
    """Return a minimal NormalizedStage for testing."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageKind, StageGate, StageTrigger

    return NormalizedStage(
        id=stage_id,
        kind=StageKind.REVIEW,
        provider=provider,
        backend=backend,
        skill=None,
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=dependencies,
    )


def make_fresh_registry():
    """Return a new BackendRendererRegistry instance isolated from the shared singleton."""
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    return BackendRendererRegistry()


def make_routing_policy_with_fast_path(
    fast_stage_ids: tuple[str, ...],
    normal_stage_ids: tuple[str, ...],
):
    """Return a RoutingPolicy with fast_path enabled and the given route stage sets."""
    from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy

    return RoutingPolicy(
        fast_path=FastPathPolicy(
            match=PathMatchSpec(paths=("docs/**",)),
            stages=RouteStageMap(fast=fast_stage_ids, normal=normal_stage_ids),
        )
    )


def make_routing_policy_disabled():
    """Return a RoutingPolicy with fast_path disabled (fast_path=None)."""
    from stagr.core.models import RoutingPolicy
    return RoutingPolicy(fast_path=None)


class StubBackendRendererPrComment:
    """Stub BackendRenderer that produces a PR_COMMENT ExecutionPlan."""

    provider: str = "stub-provider"
    backend: str = "stub-backend"

    def render(self, stage):
        from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation
        from stagr.core.enums import GateDispositionKind, InvocationKind

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=Invocation(kind=InvocationKind.PR_COMMENT),
            gate_disposition=GateDispositionSpec(
                kind=GateDispositionKind.ALWAYS_PASS,
                selector="always",
            ),
        )


class StubBackendRendererCiComponent:
    """Stub BackendRenderer that produces a CI_COMPONENT ExecutionPlan."""

    provider: str = "stub-provider"
    backend: str = "ci-component-backend"

    def render(self, stage):
        from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation
        from stagr.core.enums import GateDispositionKind, InvocationKind

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=Invocation(kind=InvocationKind.CI_COMPONENT),
            gate_disposition=GateDispositionSpec(
                kind=GateDispositionKind.ALWAYS_PASS,
                selector="always",
            ),
        )
