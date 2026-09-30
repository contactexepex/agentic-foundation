"""Shared test helpers for GitHubPlatformRenderer tests."""
from __future__ import annotations

from stagr.core.enums import (
    AuthorRole,
    ForkPolicy,
    GateDispositionKind,
    InvocationKind,
    StageGate,
    StageKind,
    StageTrigger,
)
from stagr.core.models import (
    DiscussionPolicy,
    ExecutionPlan,
    GateDispositionSpec,
    Invocation,
    MergePolicy,
    NormalizedStage,
    RenderContext,
    RoutingPolicy,
    SecretRef,
    TrustPolicy,
)
from stagr.platforms.github.renderer import GitHubPlatformRenderer

# Publisher credentials used across all tests.
TEST_PUBLISHER_APP_ID = "99001"
TEST_PUBLISHER_PRIVATE_KEY_SECRET = "STAGR_APP_PRIVATE_KEY"


def build_renderer() -> GitHubPlatformRenderer:
    """Return a GitHubPlatformRenderer with test-fixture credentials."""
    return GitHubPlatformRenderer(
        publisher_app_id=TEST_PUBLISHER_APP_ID,
        publisher_private_key_secret=TEST_PUBLISHER_PRIVATE_KEY_SECRET,
    )


def build_stage(
    stage_id: str = "review",
    triggers: tuple[StageTrigger, ...] = (StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
    gate: StageGate = StageGate.BLOCKING,
) -> NormalizedStage:
    """Return a NormalizedStage for use in renderer tests."""
    return NormalizedStage(
        id=stage_id,
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill=None,
        gate=gate,
        triggers=triggers,
        dependencies=(),
    )


def build_execution_plan(
    stage_id: str = "review",
    required_secrets: tuple[SecretRef, ...] = (),
) -> ExecutionPlan:
    """Return a minimal ExecutionPlan for the given stage.

    Uses a synchronous CI_COMPONENT invocation: a plan with no evidence is only valid when the
    invocation completes inside the execute job (see stage_signal_config).
    """
    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.CI_COMPONENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        ),
        required_secrets=required_secrets,
    )


def build_render_context(stage: NormalizedStage) -> RenderContext:
    """Return a minimal RenderContext containing the given stage."""
    return RenderContext(
        stages=(stage,),
        routing_policy=RoutingPolicy(fast_path=None),
        merge_policy=MergePolicy(
            blocking_stage_ids=(stage.id,),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )
