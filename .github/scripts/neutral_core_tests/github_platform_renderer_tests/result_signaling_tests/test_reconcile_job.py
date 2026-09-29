"""Tests for the reconcile job (issue_comment / check_suite events)."""
from __future__ import annotations

from neutral_core_tests.github_platform_renderer_tests.result_signaling_tests._helpers import (
    build_always_pass_plan,
    render_stage_yaml,
)


def test_reconcile_job_exists_in_generated_workflow() -> None:
    """Generated workflow includes a 'reconcile' job."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    assert "reconcile:" in yaml_content, (
        "Generated workflow must include a reconcile: job for reconciliation wakeups"
    )


def test_reconcile_job_runs_on_issue_comment_and_check_suite() -> None:
    """Reconcile job has condition for issue_comment and check_suite events."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    assert "issue_comment" in reconcile_block, (
        "Reconcile job must run on issue_comment events"
    )
    assert "check_suite" in reconcile_block, (
        "Reconcile job must run on check_suite events"
    )


def test_reconcile_job_exits_when_evidence_absent() -> None:
    """Reconcile job has a guard that exits without updating the Check Run when evidence is absent."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    assert "exit 0" in reconcile_block or "exit" in reconcile_block, (
        "Reconcile job must exit early (no-op) when evidence is absent"
    )


def test_reconcile_job_fetches_head_sha_from_pr_api() -> None:
    """Reconcile job fetches the current head SHA from the PR API (not from event payload)."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    assert "pulls/" in reconcile_block or "/pulls" in reconcile_block, (
        "Reconcile job must fetch head SHA from PR API, not trust event payload"
    )
    assert "head.sha" in reconcile_block, (
        "Reconcile job must extract head.sha from the PR API response"
    )


def test_reconcile_job_verifies_evidence_app_identity() -> None:
    """Reconcile job authenticates evidence by checking performed_via_github_app.id."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    reconcile_index = yaml_content.find("reconcile:")
    assert reconcile_index != -1, "Must have reconcile: job"
    reconcile_block = yaml_content[reconcile_index:]
    assert "performed_via_github_app" in reconcile_block, (
        "Reconcile job must verify evidence comment identity via performed_via_github_app.id"
    )
    assert "STAGR_APP_ID" in reconcile_block, (
        "Reconcile job must compare App id against STAGR_APP_ID to authenticate evidence"
    )
