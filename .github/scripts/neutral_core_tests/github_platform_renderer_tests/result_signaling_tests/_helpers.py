"""Shared helpers for result-signaling test submodules."""
from __future__ import annotations

import tempfile
from pathlib import Path

from stagr.core.enums import (
    AuthorRole,
    EvidenceKind,
    EvidenceSuccessCondition,
    ForkPolicy,
    GateDispositionKind,
    InvocationKind,
    MergeMode,
)
from stagr.core.models import (
    CorrelationSpec,
    DiscussionPolicy,
    EvidenceSpec,
    ExecutionPlan,
    FindingScopeSpec,
    GateDispositionSpec,
    Invocation,
    MergePolicy,
    NormalizedStage,
    RenderContext,
    RoutingPolicy,
    TrustPolicy,
)
from neutral_core_tests.github_platform_renderer_tests.helpers import (
    build_renderer,
    build_stage,
)


def build_always_pass_plan(stage_id: str = "review") -> ExecutionPlan:
    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.PR_COMMENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        ),
    )


def build_no_open_threads_plan(stage_id: str = "review") -> ExecutionPlan:
    scope = FindingScopeSpec(created_by="codex-bot", head_sha=True)
    evidence = EvidenceSpec(
        kind=EvidenceKind.COMMENT_MATCH,
        selector="codex-review:v1 status=completed",
        correlation=CorrelationSpec(head_sha=True, sha_field="headSha"),
        success_condition=EvidenceSuccessCondition.MATCH_FOUND,
        github_app_id=12345,
    )
    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.PR_COMMENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.NO_OPEN_THREADS,
            selector="codex-review",
            scope=scope,
        ),
        evidence=(evidence,),
    )


def build_render_context(
    stage: NormalizedStage,
    trusted_roles: tuple[AuthorRole, ...] = (AuthorRole.OWNER,),
    fork_policy: ForkPolicy = ForkPolicy.DENY,
) -> RenderContext:
    return RenderContext(
        stages=(stage,),
        routing_policy=RoutingPolicy(fast_path=None),
        merge_policy=MergePolicy(
            mode=MergeMode.AUTO,
            blocking_stage_ids=(stage.id,),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        trust_policy=TrustPolicy(
            trusted_roles=trusted_roles,
            fork_policy=fork_policy,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )


def render_stage_yaml(
    plan: ExecutionPlan,
    stage: NormalizedStage | None = None,
    render_context: RenderContext | None = None,
) -> str:
    if stage is None:
        stage = build_stage(stage_id=plan.stage_id)
    if render_context is None:
        render_context = build_render_context(stage)
    with tempfile.TemporaryDirectory() as temp_dir:
        renderer = build_renderer(output_dir=Path(temp_dir))
        renderer.render_stage(plan, stage, render_context)
        workflow_path = (
            Path(temp_dir) / ".github" / "workflows" / f"stage-{plan.stage_id}.yml"
        )
        return workflow_path.read_text(encoding="utf-8")
