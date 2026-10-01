"""Rendered stage workflow structure for the reconciliation and result signaling (issue #206)."""
from __future__ import annotations

import dataclasses

from neutral_core_tests.github_platform_renderer_tests.helpers import build_render_context
from neutral_core_tests.stage_signal_tests.render_helpers import (
    build_codex_plan,
    parse_workflow,
    render_codex_workflow,
    render_workflow_text,
)
from stagr.core.enums import StageKind, StageTrigger
from stagr.platforms.github import stage_workflow
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def test_stage_workflow_renders_execute_reconcile_and_sweep_jobs() -> None:
    _, document = render_codex_workflow()
    assert list(document["jobs"]) == ["execute", "reconcile", "sweep"]


def test_stage_workflow_adds_only_the_comment_and_schedule_wakeups() -> None:
    _, document = render_codex_workflow()
    triggers = document["on"]
    assert triggers["issue_comment"] == {"types": ["created", "edited"]}
    assert triggers["schedule"] == [{"cron": stage_workflow.SWEEP_CRON_SCHEDULE}]
    assert "check_suite" not in triggers, "V1 supports comment-based evidence only"
    assert set(triggers["pull_request_target"]["types"]) >= {"opened", "synchronize"}


def test_synchronizing_a_new_head_is_an_invocation_trigger_not_a_wakeup() -> None:
    """`synchronize` starts a new head execution; only comments and the schedule reconcile."""
    _, document = render_codex_workflow()
    assert "synchronize" in document["on"]["pull_request_target"]["types"]
    assert "pull_request_target" not in document["jobs"]["reconcile"]["if"]
    assert "pull_request_target" not in document["jobs"]["sweep"]["if"]


def test_execute_job_runs_only_for_the_stages_declared_trigger_events() -> None:
    cases = {
        (StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED): ["pull_request_target"],
        (StageTrigger.MANUAL,): ["workflow_dispatch"],
        (StageTrigger.ISSUE_LABELED,): ["issues"],
        (StageTrigger.MANUAL, StageTrigger.ISSUE_LABELED): ["workflow_dispatch", "issues"],
    }
    for triggers, expected_events in cases.items():
        _, document = render_codex_workflow(triggers=triggers)
        condition = document["jobs"]["execute"]["if"]
        assert all(f"github.event_name == '{name}'" in condition for name in expected_events), condition
        assert "issue_comment" not in condition and "schedule" not in condition, condition
        assert condition.count("github.event_name ==") == len(expected_events), condition


def test_reconcile_job_requires_a_pull_request_comment_by_the_declared_producer() -> None:
    _, document = render_codex_workflow()
    condition = document["jobs"]["reconcile"]["if"]
    assert "github.event_name == 'issue_comment'" in condition
    assert "github.event.issue.pull_request" in condition
    assert "github.event.comment.user.login == 'chatgpt-codex-connector[bot]'" in condition


def test_sweep_job_runs_only_on_schedule() -> None:
    _, document = render_codex_workflow()
    assert document["jobs"]["sweep"]["if"] == "${{ github.event_name == 'schedule' }}"


def test_concurrency_serializes_per_pull_request_and_gives_the_sweep_its_own_key() -> None:
    workflow_text, document = render_codex_workflow()
    group = document["concurrency"]["group"]
    assert group.startswith("stagr-review-") and "'sweep'" in group
    assert "github.event.pull_request.number" in group and "github.event.issue.number" in group
    assert document["concurrency"]["cancel-in-progress"] is False
    assert workflow_text.count("cancel-in-progress: false") == 1


def test_wakeup_and_sweep_jobs_hold_no_github_token_permissions() -> None:
    _, document = render_codex_workflow()
    assert document["jobs"]["reconcile"]["permissions"] == {}
    assert document["jobs"]["sweep"]["permissions"] == {}
    assert document["jobs"]["execute"]["permissions"] == {"pull-requests": "read", "contents": "read"}


def test_publish_step_runs_after_the_backend_step_and_reports_job_status() -> None:
    _, document = render_codex_workflow()
    steps = document["jobs"]["execute"]["steps"]
    names = [step["name"] for step in steps]
    assert names.index("Publish result signal") > names.index("Invoke backend (idempotent)")
    publish = steps[names.index("Publish result signal")]
    assert publish["if"] == "${{ !cancelled() }}"
    assert publish["env"]["STAGR_MODE"] == "publish"
    assert publish["env"]["STAGR_JOB_STATUS"] == "${{ job.status }}"
    assert publish["env"]["STAGR_EVENT_HEAD_SHA"] == "${{ github.event.pull_request.head.sha }}"
    assert publish["env"]["GH_TOKEN"] == "${{ steps.app-token.outputs.token }}"


def test_app_token_reaches_only_the_signal_steps_never_the_backend_step() -> None:
    _, document = render_codex_workflow()
    for job_name, job in document["jobs"].items():
        for step in job["steps"]:
            has_app_token = "steps.app-token.outputs.token" in str(step.get("env", {}))
            is_signal_step = step["name"] in (
                "Check eligibility", "Publish result signal", "Reconcile result signal",
                "Sweep open pull requests")
            assert has_app_token == is_signal_step, (job_name, step["name"])
    backend = next(step for step in document["jobs"]["execute"]["steps"] if step["name"].startswith("Invoke backend"))
    assert backend["env"]["TRUSTED_COMMENTER_TOKEN"] == "${{ secrets.REMEDIATION_TOKEN }}"
    assert "steps.app-token.outputs.token" not in str(backend)


def test_no_run_script_interpolates_any_expression() -> None:
    """Untrusted event data may only travel through env; run: is a fixed command."""
    _, document = render_codex_workflow()
    for job in document["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step["name"]


def test_embedded_runtime_is_the_shipped_script_and_contains_no_expression_opener() -> None:
    workflow_text, document = render_codex_workflow()
    embedded = document["env"]["STAGR_RUNTIME_SCRIPT"]
    shipped = stage_workflow.RUNTIME_SCRIPT_PATH.read_text(encoding="utf-8")
    assert embedded == shipped and "${{" not in embedded
    assert workflow_text.count("class StageReconciler") == 1, "the runtime is embedded exactly once"


def test_embedded_configuration_is_accepted_by_the_runtime() -> None:
    _, document = render_codex_workflow(StageKind.SECURITY)
    config = runtime.StageRuntimeConfig.from_json_text(document["env"]["STAGR_STAGE_CONFIG"])
    assert config.check_run_name == "stagr/stage/security" and config.publisher_app_id == "99001"
    assert config.evidence_rules[0].selector == "codex-security-review:v1 status=completed"
    assert config.gate_rule.created_by == "chatgpt-codex-connector[bot]" and config.gate_rule.head_sha_bound


def test_stage_id_is_not_spliced_into_any_script() -> None:
    plan, stage = build_codex_plan()
    stage = dataclasses.replace(stage, id="review-two")
    plan = dataclasses.replace(plan, stage_id="review-two")
    document = parse_workflow(render_workflow_text(plan, stage, build_render_context(stage)))
    assert "review-two" in document["env"]["STAGR_STAGE_CONFIG"]
    assert "review-two" not in document["env"]["STAGR_RUNTIME_SCRIPT"]
