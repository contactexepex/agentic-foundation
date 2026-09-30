"""Tests for policy models and RenderContext (issue #178)."""
from __future__ import annotations


def test_render_context_construction() -> None:
    """RenderContext constructs with all required fields; no StageResultSpec[] field."""
    from stagr.core.models import (
        DiscussionPolicy,
        FastPathPolicy,
        MergePolicy,
        NormalizedStage,
        PathMatchSpec,
        RenderContext,
        RouteStageMap,
        RoutingPolicy,
        TrustPolicy,
    )
    from stagr.core.enums import (
        AuthorRole,
        ForkPolicy,
        StageGate,
        StageKind,
        StageTrigger,
    )

    stage = NormalizedStage(
        id="review",
        kind=StageKind.REVIEW,
        provider="openai",
        backend="codex",
        skill="code-review",
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=(),
    )
    trust = TrustPolicy(
        trusted_roles=(AuthorRole.OWNER, AuthorRole.MEMBER, AuthorRole.COLLABORATOR),
        fork_policy=ForkPolicy.DENY,
        human_merge_label="human-merge",
    )
    routing = RoutingPolicy(fast_path=None)
    merge = MergePolicy(
        blocking_stage_ids=("review",),
        require_head_bound=True,
    )
    ctx = RenderContext(
        stages=(stage,),
        routing_policy=routing,
        merge_policy=merge,
        trust_policy=trust,
        platform="github",
        config_version="1",
    )
    assert ctx.platform == "github"
    assert len(ctx.stages) == 1

    # No StageResultSpec[] field in RenderContext
    assert not hasattr(ctx, "stage_result_specs")
    assert not hasattr(ctx, "result_specs")


def test_render_context_is_immutable() -> None:
    """RenderContext is frozen — mutation raises."""
    from stagr.core.models import MergePolicy, RenderContext, RoutingPolicy, TrustPolicy
    from stagr.core.enums import AuthorRole, ForkPolicy

    ctx = RenderContext(
        stages=(),
        routing_policy=RoutingPolicy(fast_path=None),
        merge_policy=MergePolicy(
            blocking_stage_ids=(),
            require_head_bound=True,
        ),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="1",
    )
    raised = False
    try:
        ctx.platform = "gitlab"  # type: ignore[misc]
    except Exception as exc:
        raised = True
        assert "frozen" in str(exc).lower() or "cannot" in str(exc).lower()
    assert raised, "ctx.platform assignment should have raised an exception"
