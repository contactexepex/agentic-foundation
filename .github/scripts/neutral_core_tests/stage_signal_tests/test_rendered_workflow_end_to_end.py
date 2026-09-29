"""End to end: plan -> rendered workflow -> embedded runtime -> Check Runs, via the strict gh shim.

Each step extracts the script and configuration from the RENDERED workflow (not from the source
file) and runs it as a process exactly like the ``python3 -c`` step, so a drift between the
renderer's configuration and the runtime's expectations fails here.
"""
from __future__ import annotations

import json

from neutral_core_tests.stage_signal_tests.fake_github import FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    PULL_NUMBER,
    build_issue_comment,
    build_review_thread,
    build_summary_body,
    build_world,
)
from neutral_core_tests.stage_signal_tests.process_runner import run_script_against_fake
from neutral_core_tests.stage_signal_tests.render_helpers import render_codex_workflow
from stagr.core.enums import StageKind


def _run_stage(workflow: dict, fake: FakeGitHubApi, mode: str, **environment) -> FakeGitHubApi:
    completed, state = run_script_against_fake(
        fake, workflow["env"]["STAGR_RUNTIME_SCRIPT"],
        STAGR_STAGE_CONFIG=workflow["env"]["STAGR_STAGE_CONFIG"], STAGR_MODE=mode, **environment,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return state


def _publish(workflow: dict, fake: FakeGitHubApi) -> FakeGitHubApi:
    return _run_stage(workflow, fake, "publish", STAGR_PULL_NUMBER=str(PULL_NUMBER),
                      STAGR_EVENT_HEAD_SHA=HEAD_SHA, STAGR_JOB_STATUS="success")


def _reconcile(workflow: dict, fake: FakeGitHubApi) -> FakeGitHubApi:
    return _run_stage(workflow, fake, "reconcile", STAGR_PULL_NUMBER=str(PULL_NUMBER))


def _summary(fake: FakeGitHubApi) -> dict:
    (check_run,) = fake.stage_check_runs(HEAD_SHA)
    return {**json.loads(check_run["output"]["summary"]), "native": (check_run["status"], check_run.get("conclusion"))}


def _lifecycle(stage_kind: StageKind) -> None:
    _, workflow = render_codex_workflow(stage_kind)
    stage_id = stage_kind.value
    fake = _publish(workflow, build_world())
    assert _summary(fake)["state"] == "running" and _summary(fake)["stageId"] == stage_id

    fake.issue_comments[PULL_NUMBER] = [build_issue_comment(build_summary_body())]
    fake.review_threads[PULL_NUMBER] = [build_review_thread()]
    fake = _reconcile(workflow, fake)
    assert _summary(fake)["conclusion"] == "blocked"
    assert _summary(fake)["native"] == ("completed", "action_required")

    fake.review_threads[PULL_NUMBER] = [build_review_thread(is_resolved=True)]
    fake = _run_stage(workflow, fake, "sweep")
    assert _summary(fake)["conclusion"] == "pass"
    assert _summary(fake)["native"] == ("completed", "success")
    assert [call[0] for call in fake.write_calls] == ["POST", "PATCH", "PATCH"]


def test_rendered_review_workflow_runs_the_full_lifecycle() -> None:
    _lifecycle(StageKind.REVIEW)


def test_rendered_security_workflow_runs_the_full_lifecycle() -> None:
    _lifecycle(StageKind.SECURITY)


def test_rendered_workflow_ignores_evidence_forged_by_a_human_commenter() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    fake = _publish(workflow, build_world())
    fake.issue_comments[PULL_NUMBER] = [
        build_issue_comment(build_summary_body(), login="attacker", user_type="User")
    ]
    fake = _reconcile(workflow, fake)
    assert _summary(fake)["state"] == "running" and len(fake.write_calls) == 1


def test_rendered_workflow_publishes_failure_when_the_execute_job_failed() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    fake = _run_stage(workflow, build_world(), "publish", STAGR_PULL_NUMBER=str(PULL_NUMBER),
                      STAGR_EVENT_HEAD_SHA=HEAD_SHA, STAGR_JOB_STATUS="failure")
    assert _summary(fake)["state"] == "failed" and _summary(fake)["native"] == ("completed", "failure")


def test_rendered_workflow_publishes_nothing_for_events_without_a_pull_request() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    fake = _run_stage(workflow, build_world(), "publish", STAGR_PULL_NUMBER="", STAGR_JOB_STATUS="success")
    assert not fake.write_calls and not fake.check_runs
