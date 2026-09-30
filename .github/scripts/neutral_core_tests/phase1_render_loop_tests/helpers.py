"""Shared stubs and helpers for Phase 1 render loop tests.

All test modules in this sub-package import from here to avoid duplicating
stub definitions.
"""
from __future__ import annotations


def build_stage(stage_id: str, provider: str = "testprovider", backend: str = "testbackend"):
    """Return a minimal NormalizedStage for the given stage_id."""
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
        dependencies=(),
    )


def build_minimal_render_context(stages):
    """Return a RenderContext containing the given stages."""
    from stagr.core.models import (
        RenderContext,
        RoutingPolicy,
        MergePolicy,
        TrustPolicy,
        DiscussionPolicy,
    )
    from stagr.core.enums import AuthorRole, ForkPolicy

    return RenderContext(
        stages=tuple(stages),
        routing_policy=RoutingPolicy(fast_path=None),
        merge_policy=MergePolicy(
            blocking_stage_ids=tuple(stage.id for stage in stages),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="1",
    )


def build_execution_plan(stage_id: str, secret_aliases: tuple = ()):
    """Return a minimal ExecutionPlan with alias-only SecretRef entries."""
    from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation, SecretRef
    from stagr.core.enums import GateDispositionKind, InvocationKind

    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.CI_COMPONENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        ),
        required_secrets=tuple(SecretRef(alias=alias) for alias in secret_aliases),
    )


def build_stage_result_spec(stage_id: str):
    """Return a minimal StageResultSpec for the given stage_id."""
    from stagr.core.models import StageResultSpec, StageResultProvenance
    from stagr.core.enums import StageResultSignalKind

    return StageResultSpec(
        stage_id=stage_id,
        signal_kind=StageResultSignalKind.CHECK_RUN,
        signal_selector=f"test/{stage_id}",
        provenance=StageResultProvenance(publisher_identity="github-app[bot]"),
    )


def build_stage_render(stage_id: str):
    """Return a minimal StageRender (result spec plus artifact) for the given stage_id."""
    from stagr.core.models import RenderedArtifact, StageRender

    return StageRender(
        result_spec=build_stage_result_spec(stage_id),
        artifact=RenderedArtifact(path=f"stages/{stage_id}.yml", content=f"# stage {stage_id}\n"),
    )


class TrackingPlatformRenderer:
    """PlatformRenderer stub that records all render_stage calls.

    render_routing and render_governance raise AssertionError when called,
    so any Phase 1 loop that invokes them fails the test immediately.
    """

    def __init__(self) -> None:
        self.render_stage_calls: list = []

    def render_stage(self, plan, stage, render_context):
        self.render_stage_calls.append((plan, stage, render_context))
        return build_stage_render(stage.id)

    def render_routing(self, render_context):
        raise AssertionError(
            "render_routing must NOT be called during Phase 1 "
            "(Phase 2 method invoked unexpectedly)"
        )

    def render_governance(self, result_specs, render_context):
        raise AssertionError(
            "render_governance must NOT be called during Phase 1 "
            "(Phase 2 method invoked unexpectedly)"
        )
