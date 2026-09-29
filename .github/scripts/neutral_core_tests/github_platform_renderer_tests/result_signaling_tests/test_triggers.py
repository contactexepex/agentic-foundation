"""Tests for reconciliation wakeup triggers and execute-job event guards."""
from __future__ import annotations

from stagr.core.enums import StageTrigger
from neutral_core_tests.github_platform_renderer_tests.helpers import build_stage
from neutral_core_tests.github_platform_renderer_tests.result_signaling_tests._helpers import (
    build_always_pass_plan,
    build_render_context,
    render_stage_yaml,
)


def test_stage_workflow_has_issue_comment_trigger() -> None:
    """Generated stage workflow includes issue_comment trigger for reconciliation wakeup."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    assert "issue_comment:" in yaml_content, (
        "Stage workflow must include issue_comment: trigger for reconciliation wakeup"
    )
    assert "created" in yaml_content and "edited" in yaml_content, (
        "issue_comment trigger must include created and edited types"
    )


def test_stage_workflow_has_check_suite_trigger() -> None:
    """Generated stage workflow includes check_suite trigger for reconciliation wakeup."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    assert "check_suite:" in yaml_content, (
        "Stage workflow must include check_suite: trigger for reconciliation wakeup"
    )


def test_stage_workflow_has_schedule_trigger() -> None:
    """Generated stage workflow includes schedule trigger for the sweep job."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    assert "schedule:" in yaml_content, (
        "Stage workflow must include schedule: trigger for the periodic sweep job"
    )
    assert "cron:" in yaml_content, (
        "Schedule trigger must include a cron: expression"
    )


def test_manual_trigger_execute_job_guarded_for_workflow_dispatch() -> None:
    """MANUAL-only stage: execute job has if-guard restricted to workflow_dispatch events."""
    stage = build_stage(triggers=(StageTrigger.MANUAL,))
    render_context = build_render_context(stage)
    yaml_content = render_stage_yaml(build_always_pass_plan(), stage=stage, render_context=render_context)
    execute_index = yaml_content.find("execute:")
    assert execute_index != -1, "Must have execute: job"
    execute_block = yaml_content[execute_index : execute_index + 300]
    assert "workflow_dispatch" in execute_block, (
        "MANUAL stage execute job must guard with github.event_name == 'workflow_dispatch'"
    )
    assert "issue_comment" not in execute_block, (
        "MANUAL stage execute job must not run on reconciliation issue_comment events"
    )


def test_issue_labeled_trigger_execute_job_guarded_for_issues() -> None:
    """ISSUE_LABELED-only stage: execute job has if-guard restricted to issues events."""
    stage = build_stage(triggers=(StageTrigger.ISSUE_LABELED,))
    render_context = build_render_context(stage)
    yaml_content = render_stage_yaml(build_always_pass_plan(), stage=stage, render_context=render_context)
    execute_index = yaml_content.find("execute:")
    assert execute_index != -1, "Must have execute: job"
    execute_block = yaml_content[execute_index : execute_index + 300]
    assert "github.event_name == 'issues'" in execute_block, (
        "ISSUE_LABELED stage execute job must guard with github.event_name == 'issues'"
    )
    assert "pull_request_target" not in execute_block, (
        "ISSUE_LABELED stage execute job must not reference pull_request_target"
    )
