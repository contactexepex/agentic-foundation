"""Tests for the sweep job (schedule events)."""
from __future__ import annotations

from stagr.core.enums import AuthorRole, ForkPolicy
from neutral_core_tests.github_platform_renderer_tests.helpers import build_stage
from neutral_core_tests.github_platform_renderer_tests.result_signaling_tests._helpers import (
    build_always_pass_plan,
    build_no_open_threads_plan,
    build_render_context,
    render_stage_yaml,
)


def test_sweep_job_exists_in_generated_workflow() -> None:
    """Generated workflow includes a 'sweep' job."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    assert "sweep:" in yaml_content, (
        "Generated workflow must include a sweep: job for the scheduled reconciliation pass"
    )


def test_sweep_job_runs_on_schedule_only() -> None:
    """Sweep job has condition for schedule events."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "schedule" in sweep_block, "Sweep job must run on schedule events"


def test_sweep_job_enumerates_open_prs() -> None:
    """Sweep job calls the pulls API with state=open to enumerate PRs."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "state=open" in sweep_block or "state: open" in sweep_block, (
        "Sweep job must enumerate open PRs via the pulls API"
    )


def test_sweep_job_filters_untrusted_author_association() -> None:
    """Sweep job checks author_association against baked trusted_roles and skips untrusted PRs."""
    stage = build_stage()
    render_context = build_render_context(
        stage, trusted_roles=(AuthorRole.OWNER, AuthorRole.MEMBER)
    )
    yaml_content = render_stage_yaml(
        build_always_pass_plan(), stage=stage, render_context=render_context
    )
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "author_association" in sweep_block or "author" in sweep_block, (
        "Sweep job must check author_association to filter untrusted PR authors"
    )
    assert "owner" in sweep_block, (
        "Sweep job must bake 'owner' from TrustPolicy.trusted_roles into the script"
    )
    assert "member" in sweep_block, (
        "Sweep job must bake 'member' from TrustPolicy.trusted_roles into the script"
    )


def test_sweep_job_skips_fork_prs_when_fork_policy_deny() -> None:
    """Sweep job skips fork PRs when ForkPolicy is DENY."""
    stage = build_stage()
    render_context = build_render_context(stage, fork_policy=ForkPolicy.DENY)
    yaml_content = render_stage_yaml(
        build_always_pass_plan(), stage=stage, render_context=render_context
    )
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "head.repo.id" in sweep_block or "head_repo" in sweep_block, (
        "Sweep job must compare head.repo.id against base.repo.id for ForkPolicy.DENY"
    )


def test_sweep_job_checks_evidence_before_gate_eval() -> None:
    """Sweep job verifies declared evidence (selector-matched comment) before evaluating gate disposition."""
    stage = build_stage()
    render_context = build_render_context(stage)
    yaml_content = render_stage_yaml(build_no_open_threads_plan(), stage=stage, render_context=render_context)
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "codex-review:v1 status=completed" in sweep_block, (
        "Sweep job must use the full declared evidence selector (not just the prefix)"
    )
    assert "performed_via_github_app" in sweep_block, (
        "Sweep job must filter evidence comments by App ID when github_app_id is declared"
    )


def test_sweep_job_bakes_trusted_roles_as_literal() -> None:
    """Sweep job bakes trusted_roles from TrustPolicy as a literal string constant."""
    stage = build_stage()
    render_context = build_render_context(
        stage, trusted_roles=(AuthorRole.OWNER, AuthorRole.COLLABORATOR)
    )
    yaml_content = render_stage_yaml(
        build_always_pass_plan(), stage=stage, render_context=render_context
    )
    sweep_index = yaml_content.find("sweep:")
    assert sweep_index != -1, "Must have sweep: job"
    sweep_block = yaml_content[sweep_index:]
    assert "owner" in sweep_block, "Sweep job must bake 'owner' role"
    assert "collaborator" in sweep_block, "Sweep job must bake 'collaborator' role"
