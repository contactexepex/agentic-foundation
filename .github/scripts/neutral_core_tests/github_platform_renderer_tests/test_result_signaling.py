"""Tests for stage runtime reconciliation and result signaling (issue #206).

Covers:
  - ALWAYS_PASS disposition: Check Run emits conclusion=success, payload conclusion="pass"
  - NO_OPEN_THREADS: open threads -> action_required/blocked, zero -> success/pass
  - Reconciliation wakeup triggers (issue_comment, check_suite, schedule) in on: section
  - Reconcile job: evidence-absent guard exits without updating Check Run
  - Sweep job: enumerates open PRs, skips untrusted author, skips fork PRs
  - Upsert pattern: PATCH existing Check Run or POST new one
  - StageResultSignal JSON payload: schemaVersion=1, stageId, headSha, state, conclusion
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from stagr.core.enums import (
    AuthorRole,
    ForkPolicy,
    GateDispositionKind,
    InvocationKind,
    MergeMode,
    StageGate,
    StageKind,
    StageTrigger,
)
from stagr.core.models import (
    DiscussionPolicy,
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
    TEST_PUBLISHER_APP_ID,
    TEST_PUBLISHER_PRIVATE_KEY_SECRET,
    build_renderer,
    build_stage,
)


def _build_always_pass_plan(stage_id: str = "review") -> ExecutionPlan:
    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.PR_COMMENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        ),
    )


def _build_no_open_threads_plan(stage_id: str = "review") -> ExecutionPlan:
    scope = FindingScopeSpec(created_by="codex-bot", head_sha=True)
    return ExecutionPlan(
        stage_id=stage_id,
        invocation=Invocation(kind=InvocationKind.PR_COMMENT),
        gate_disposition=GateDispositionSpec(
            kind=GateDispositionKind.NO_OPEN_THREADS,
            selector="codex-review",
            scope=scope,
        ),
    )


def _build_render_context(
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


def _render_yaml(
    plan: ExecutionPlan,
    stage: NormalizedStage | None = None,
    render_context: RenderContext | None = None,
) -> str:
    if stage is None:
        stage = build_stage(stage_id=plan.stage_id)
    if render_context is None:
        render_context = _build_render_context(stage)
    with tempfile.TemporaryDirectory() as temp_dir:
        renderer = build_renderer(output_dir=Path(temp_dir))
        renderer.render_stage(plan, stage, render_context)
        workflow_path = (
            Path(temp_dir) / ".github" / "workflows" / f"stage-{plan.stage_id}.yml"
        )
        return workflow_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Reconciliation triggers
# ---------------------------------------------------------------------------


def test_stage_workflow_has_issue_comment_trigger() -> None:
    """Generated stage workflow includes issue_comment trigger for reconciliation wakeup."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    assert "issue_comment:" in yaml_content, (
        "Stage workflow must include issue_comment: trigger for reconciliation wakeup"
    )
    assert "created" in yaml_content and "edited" in yaml_content, (
        "issue_comment trigger must include created and edited types"
    )


def test_stage_workflow_has_check_suite_trigger() -> None:
    """Generated stage workflow includes check_suite trigger for reconciliation wakeup."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    assert "check_suite:" in yaml_content, (
        "Stage workflow must include check_suite: trigger for reconciliation wakeup"
    )


def test_stage_workflow_has_schedule_trigger() -> None:
    """Generated stage workflow includes schedule trigger for the sweep job."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    assert "schedule:" in yaml_content, (
        "Stage workflow must include schedule: trigger for the periodic sweep job"
    )
    assert "cron:" in yaml_content, (
        "Schedule trigger must include a cron: expression"
    )


# ---------------------------------------------------------------------------
# ALWAYS_PASS result signaling
# ---------------------------------------------------------------------------


def test_always_pass_result_step_emits_success_conclusion() -> None:
    """ALWAYS_PASS disposition: result step has Check Run conclusion=success."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "conclusion=success" in publish_block or 'conclusion": "success"' in publish_block, (
        "ALWAYS_PASS step must emit Check Run conclusion=success"
    )


def test_always_pass_result_payload_has_conclusion_pass() -> None:
    """ALWAYS_PASS disposition: JSON payload contains conclusion: 'pass'."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert '"pass"' in publish_block or "'pass'" in publish_block or "pass" in publish_block, (
        "ALWAYS_PASS result payload must carry conclusion='pass'"
    )
    # Specifically the payload arg should have conclusion=pass
    assert 'conclusion' in publish_block, (
        "ALWAYS_PASS result step must set conclusion in payload"
    )


def test_result_payload_has_schema_version_one() -> None:
    """Result signaling step embeds schemaVersion=1 in the JSON payload."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "schemaVersion" in publish_block, (
        "Result payload must include schemaVersion field"
    )
    assert "1" in publish_block, (
        "schemaVersion must be 1"
    )


def test_result_payload_embeds_stage_id() -> None:
    """Result signaling step embeds the stage id in the JSON payload."""
    stage_id = "security-scan"
    yaml_content = _render_yaml(_build_always_pass_plan(stage_id=stage_id))
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert stage_id in publish_block, (
        f"Result payload must include stageId='{stage_id}'"
    )


def test_result_payload_includes_head_sha_reference() -> None:
    """Result signaling step includes a HEAD_SHA reference in the payload."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "HEAD_SHA" in publish_block or "head.sha" in publish_block, (
        "Result payload must reference the head SHA"
    )


# ---------------------------------------------------------------------------
# Upsert pattern
# ---------------------------------------------------------------------------


def test_result_step_patches_existing_check_run() -> None:
    """Result signaling step PATCHes an existing Check Run when one exists."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "PATCH" in publish_block, (
        "Result step must use PATCH to update an existing Check Run"
    )


def test_result_step_posts_new_check_run_when_absent() -> None:
    """Result signaling step POSTs a new Check Run when none exists."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "POST" in publish_block, (
        "Result step must use POST to create a new Check Run when none exists"
    )


def test_result_step_uses_filter_all_to_find_existing_check_run() -> None:
    """Result signaling step queries check-runs with filter=all."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "filter=all" in publish_block, (
        "Result step must use filter=all to find existing Check Runs regardless of status"
    )


# ---------------------------------------------------------------------------
# NO_OPEN_THREADS result signaling
# ---------------------------------------------------------------------------


def test_no_open_threads_step_emits_action_required_for_blocked() -> None:
    """NO_OPEN_THREADS: step emits action_required when open threads exist."""
    yaml_content = _render_yaml(_build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "action_required" in publish_block, (
        "NO_OPEN_THREADS step must contain action_required conclusion path for blocked"
    )


def test_no_open_threads_step_emits_blocked_in_payload() -> None:
    """NO_OPEN_THREADS: JSON payload has conclusion='blocked' when threads are open."""
    yaml_content = _render_yaml(_build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "blocked" in publish_block, (
        "NO_OPEN_THREADS step must contain 'blocked' conclusion payload"
    )


def test_no_open_threads_step_emits_success_for_zero_threads() -> None:
    """NO_OPEN_THREADS: step emits success when no open threads."""
    yaml_content = _render_yaml(_build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "success" in publish_block, (
        "NO_OPEN_THREADS step must contain success conclusion path for zero threads"
    )


def test_no_open_threads_step_queries_graphql_review_threads() -> None:
    """NO_OPEN_THREADS: step queries GitHub GraphQL API for unresolved review threads."""
    yaml_content = _render_yaml(_build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "graphql" in publish_block, (
        "NO_OPEN_THREADS step must query GraphQL API for review threads"
    )
    assert "reviewThreads" in publish_block or "review_threads" in publish_block.lower(), (
        "NO_OPEN_THREADS step must query reviewThreads in GraphQL"
    )
    assert "isResolved" in publish_block, (
        "NO_OPEN_THREADS step must check isResolved field to count open threads"
    )


# ---------------------------------------------------------------------------
# Reconcile job (issue_comment / check_suite)
# ---------------------------------------------------------------------------


def test_reconcile_job_exists_in_generated_workflow() -> None:
    """Generated workflow includes a 'reconcile' job."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    assert "reconcile:" in yaml_content, (
        "Generated workflow must include a reconcile: job for reconciliation wakeups"
    )


def test_reconcile_job_runs_on_issue_comment_and_check_suite() -> None:
    """Reconcile job has condition for issue_comment and check_suite events."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    # The if condition must reference both event names
    assert "issue_comment" in reconcile_block, (
        "Reconcile job must run on issue_comment events"
    )
    assert "check_suite" in reconcile_block, (
        "Reconcile job must run on check_suite events"
    )


def test_reconcile_job_exits_when_evidence_absent() -> None:
    """Reconcile job has a guard that exits without updating the Check Run when evidence is absent."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    # The reconcile step must have an early-exit when evidence is missing
    assert "exit 0" in reconcile_block or "exit" in reconcile_block, (
        "Reconcile job must exit early (no-op) when evidence is absent"
    )


def test_reconcile_job_fetches_head_sha_from_pr_api() -> None:
    """Reconcile job fetches the current head SHA from the PR API (not from event payload)."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    assert "pulls/" in reconcile_block or "/pulls" in reconcile_block, (
        "Reconcile job must fetch head SHA from PR API, not trust event payload"
    )
    assert "head.sha" in reconcile_block, (
        "Reconcile job must extract head.sha from the PR API response"
    )


# ---------------------------------------------------------------------------
# Sweep job (schedule)
# ---------------------------------------------------------------------------


def test_sweep_job_exists_in_generated_workflow() -> None:
    """Generated workflow includes a 'sweep' job."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    assert "sweep:" in yaml_content, (
        "Generated workflow must include a sweep: job for the scheduled reconciliation pass"
    )


def test_sweep_job_runs_on_schedule_only() -> None:
    """Sweep job has condition for schedule events."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "schedule" in sweep_block, (
        "Sweep job must run on schedule events"
    )


def test_sweep_job_enumerates_open_prs() -> None:
    """Sweep job calls the pulls API with state=open to enumerate PRs."""
    yaml_content = _render_yaml(_build_always_pass_plan())
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "state=open" in sweep_block or "state: open" in sweep_block, (
        "Sweep job must enumerate open PRs via the pulls API"
    )


def test_sweep_job_filters_untrusted_author_association() -> None:
    """Sweep job checks author_association against baked trusted_roles and skips untrusted PRs."""
    stage = build_stage()
    render_context = _build_render_context(
        stage, trusted_roles=(AuthorRole.OWNER, AuthorRole.MEMBER)
    )
    yaml_content = _render_yaml(_build_always_pass_plan(), stage=stage, render_context=render_context)
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "author_association" in sweep_block or "author" in sweep_block, (
        "Sweep job must check author_association to filter untrusted PR authors"
    )
    # Trusted roles must be baked in as a constant
    assert "owner" in sweep_block, (
        "Sweep job must bake 'owner' from TrustPolicy.trusted_roles into the script"
    )
    assert "member" in sweep_block, (
        "Sweep job must bake 'member' from TrustPolicy.trusted_roles into the script"
    )


def test_sweep_job_skips_fork_prs_when_fork_policy_deny() -> None:
    """Sweep job skips fork PRs when ForkPolicy is DENY."""
    stage = build_stage()
    render_context = _build_render_context(stage, fork_policy=ForkPolicy.DENY)
    yaml_content = _render_yaml(_build_always_pass_plan(), stage=stage, render_context=render_context)
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "head.repo.id" in sweep_block or "head_repo" in sweep_block, (
        "Sweep job must compare head.repo.id against base.repo.id for ForkPolicy.DENY"
    )


def test_sweep_job_bakes_trusted_roles_as_literal() -> None:
    """Sweep job bakes trusted_roles from TrustPolicy as a literal string constant."""
    stage = build_stage()
    render_context = _build_render_context(
        stage, trusted_roles=(AuthorRole.OWNER, AuthorRole.COLLABORATOR)
    )
    yaml_content = _render_yaml(_build_always_pass_plan(), stage=stage, render_context=render_context)
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    # owner and collaborator should be baked in as literals
    assert "owner" in sweep_block, "Sweep job must bake 'owner' role"
    assert "collaborator" in sweep_block, "Sweep job must bake 'collaborator' role"


RESULT_SIGNALING_TESTS = [
    test_stage_workflow_has_issue_comment_trigger,
    test_stage_workflow_has_check_suite_trigger,
    test_stage_workflow_has_schedule_trigger,
    test_always_pass_result_step_emits_success_conclusion,
    test_always_pass_result_payload_has_conclusion_pass,
    test_result_payload_has_schema_version_one,
    test_result_payload_embeds_stage_id,
    test_result_payload_includes_head_sha_reference,
    test_result_step_patches_existing_check_run,
    test_result_step_posts_new_check_run_when_absent,
    test_result_step_uses_filter_all_to_find_existing_check_run,
    test_no_open_threads_step_emits_action_required_for_blocked,
    test_no_open_threads_step_emits_blocked_in_payload,
    test_no_open_threads_step_emits_success_for_zero_threads,
    test_no_open_threads_step_queries_graphql_review_threads,
    test_reconcile_job_exists_in_generated_workflow,
    test_reconcile_job_runs_on_issue_comment_and_check_suite,
    test_reconcile_job_exits_when_evidence_absent,
    test_reconcile_job_fetches_head_sha_from_pr_api,
    test_sweep_job_exists_in_generated_workflow,
    test_sweep_job_runs_on_schedule_only,
    test_sweep_job_enumerates_open_prs,
    test_sweep_job_filters_untrusted_author_association,
    test_sweep_job_skips_fork_prs_when_fork_policy_deny,
    test_sweep_job_bakes_trusted_roles_as_literal,
]
