"""End to end: two rendered stage workflows (review -> security) run as processes on the strict gh shim.

Each step extracts the runtime and the configuration from the RENDERED workflow and runs it as a
process exactly like the ``python3 -c`` step, with the environment the workflow gives that step. The
shim accepts only known tokens, so a step that used a credential it was not given fails like a 401,
and every token it sees is recorded: eligibility, publish and sweep may use only the App token, the
invoke step only the backend token.
"""
from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any

from neutral_core_tests.github_platform_renderer_tests.helpers import build_render_context
from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    FOREIGN_APP_ID,
    build_route_check_run,
    check_runs_named,
)
from neutral_core_tests.stage_signal_tests.fake_github import (
    COMMENTER_TOKEN,
    COMMENTER_USER,
    FakeGitHubApi,
)
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    PULL_NUMBER,
    build_issue_comment,
    build_review_thread,
    build_summary_body,
    build_world,
)
from neutral_core_tests.stage_signal_tests.process_runner import run_script_against_fake
from neutral_core_tests.stage_signal_tests.render_helpers import (
    build_codex_plan,
    parse_workflow,
    render_workflow_text,
)
from stagr.core.enums import StageKind
from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy

APP_TOKEN = "app-installation-token-value"
APP_USER = {"id": 8001, "login": "stagr-app[bot]", "type": "Bot"}
SECURITY_CHECK_RUN = "stagr/stage/security"
REVIEW_CHECK_RUN = "stagr/stage/review"


def _render_pair(fast_path: FastPathPolicy | None = None) -> tuple[dict, dict]:
    """The ``review`` and ``security`` workflows of one pipeline where security depends on review."""
    review_plan, review_stage = build_codex_plan(StageKind.REVIEW)
    security_plan, security_stage = build_codex_plan(StageKind.SECURITY)
    security_stage = dataclasses.replace(security_stage, dependencies=("review",))
    context = dataclasses.replace(
        build_render_context(review_stage), stages=(review_stage, security_stage),
        routing_policy=RoutingPolicy(fast_path=fast_path))
    return (
        parse_workflow(render_workflow_text(review_plan, review_stage, context)),
        parse_workflow(render_workflow_text(security_plan, security_stage, context)),
    )


def _world(comments: list[dict[str, Any]] | None = None, threads: list | None = None) -> FakeGitHubApi:
    fake = build_world(
        comments=comments if comments is not None else [
            build_issue_comment(build_summary_body(security_status="running"))],
        threads=threads)
    fake.token_accounts = {COMMENTER_TOKEN: COMMENTER_USER, APP_TOKEN: APP_USER}
    return fake


def _run(workflow: dict, fake: FakeGitHubApi, mode: str, **environment: str) -> tuple[Any, FakeGitHubApi]:
    fake.used_tokens = []
    return run_script_against_fake(
        fake, workflow["env"]["STAGR_RUNTIME_SCRIPT"],
        STAGR_STAGE_CONFIG=workflow["env"]["STAGR_STAGE_CONFIG"], STAGR_MODE=mode, **environment)


def _event_environment(event_name: str, head_sha: str = HEAD_SHA, pull_number: str = str(PULL_NUMBER)) -> dict:
    return {"STAGR_PULL_NUMBER": pull_number, "STAGR_EVENT_HEAD_SHA": head_sha, "STAGR_EVENT_NAME": event_name}


def _eligibility(workflow: dict, fake: FakeGitHubApi, event_name: str, **event: str) -> tuple[bool, FakeGitHubApi]:
    """The eligibility step: App token and event data; returns whether it wrote ``proceed=true``."""
    with tempfile.TemporaryDirectory() as directory:
        output_path = Path(directory) / "github_output"
        output_path.write_text("")
        completed, state = _run(
            workflow, fake, "eligibility", GH_TOKEN=APP_TOKEN, GITHUB_OUTPUT=str(output_path),
            **_event_environment(event_name, **event))
        assert completed.returncode == 0, completed.stdout + completed.stderr
        assert set(state.used_tokens) <= {APP_TOKEN}, state.used_tokens
        return "proceed=true" in output_path.read_text(), state


def _invoke(workflow: dict, fake: FakeGitHubApi, event_name: str) -> FakeGitHubApi:
    completed, state = _run(
        workflow, fake, "invoke", GH_TOKEN=APP_TOKEN, TRUSTED_COMMENTER_TOKEN=COMMENTER_TOKEN,
        **_event_environment(event_name))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert set(state.used_tokens) == {COMMENTER_TOKEN}, "the invoke step uses only the backend token"
    return state


def _publish(workflow: dict, fake: FakeGitHubApi, event_name: str, job_status: str = "success") -> FakeGitHubApi:
    completed, state = _run(
        workflow, fake, "publish", GH_TOKEN=APP_TOKEN, STAGR_JOB_STATUS=job_status,
        **_event_environment(event_name))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert set(state.used_tokens) <= {APP_TOKEN}, state.used_tokens
    return state


def _sweep(workflow: dict, fake: FakeGitHubApi) -> tuple[str, FakeGitHubApi]:
    """The sweep step: the App token only, exactly like the sweep job (no backend secret at all)."""
    completed, state = _run(workflow, fake, "sweep", GH_TOKEN=APP_TOKEN)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert set(state.used_tokens) == {APP_TOKEN}
    return completed.stdout, state


def _signal(fake: FakeGitHubApi, check_run_name: str) -> dict[str, Any]:
    (check_run,) = check_runs_named(fake, check_run_name)
    return {**json.loads(check_run["output"]["summary"]),
            "native": (check_run["status"], check_run.get("conclusion"))}


def _backend_comments(fake: FakeGitHubApi) -> list[dict[str, Any]]:
    return [comment for comment in fake.issue_comments[PULL_NUMBER] if comment["user"] == COMMENTER_USER]


def test_downstream_stage_waits_then_starts_when_the_upstream_signal_arrives() -> None:
    review, security = _render_pair()
    fake = _world()

    proceed, fake = _eligibility(security, fake, "pull_request_target")
    assert proceed is False, "no upstream signal yet"
    fake = _publish(security, fake, "pull_request_target")
    assert fake.write_calls == [] and fake.check_runs == []

    fake = _publish(review, fake, "pull_request_target")
    assert _signal(fake, REVIEW_CHECK_RUN)["conclusion"] == "pass"

    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is True
    fake = _invoke(security, fake, "check_run")
    (comment,) = _backend_comments(fake)
    assert comment["user"] == COMMENTER_USER and comment["body"].startswith("@codex security review\n")
    fake = _publish(security, fake, "check_run")
    assert _signal(fake, SECURITY_CHECK_RUN)["state"] == "running"


def test_a_second_wakeup_after_the_stage_started_writes_and_posts_nothing() -> None:
    review, security = _render_pair()
    fake = _publish(review, _world(), "pull_request_target")
    _, fake = _eligibility(security, fake, "check_run")
    fake = _publish(security, _invoke(security, fake, "check_run"), "check_run")
    writes_after_start = len(fake.write_calls)

    for event_name in ("check_suite", "check_run"):
        proceed, fake = _eligibility(security, fake, event_name)
        assert proceed is True, "a running stage is not final"
        fake = _invoke(security, fake, event_name)
        fake = _publish(security, fake, event_name)
    assert len(fake.write_calls) == writes_after_start and len(_backend_comments(fake)) == 1


def test_backend_answer_completes_the_started_stage_through_the_sweep_with_only_the_app_token() -> None:
    review, security = _render_pair()
    fake = _publish(review, _world(), "pull_request_target")
    _, fake = _eligibility(security, fake, "check_run")
    fake = _publish(security, _invoke(security, fake, "check_run"), "check_run")

    fake.issue_comments[PULL_NUMBER].append(build_issue_comment(build_summary_body(), comment_id=5000))
    _, fake = _sweep(security, fake)
    assert _signal(fake, SECURITY_CHECK_RUN)["native"] == ("completed", "success")
    assert len(_backend_comments(fake)) == 1


def test_failed_upstream_fails_the_downstream_stage_without_ever_asking_the_backend() -> None:
    review, security = _render_pair()
    fake = _publish(review, _world(), "pull_request_target", job_status="failure")
    assert _signal(fake, REVIEW_CHECK_RUN)["state"] == "failed"

    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is False
    fake = _publish(security, fake, "check_run")
    assert _signal(fake, SECURITY_CHECK_RUN)["native"] == ("completed", "failure")
    assert _backend_comments(fake) == [] and not fake.comments_posted_by_writes()


def test_blocked_to_pass_upstream_is_seen_by_the_downstream_sweep_which_cannot_start_the_stage() -> None:
    review, security = _render_pair()
    fake = _world(threads=[build_review_thread()])
    fake = _publish(review, fake, "pull_request_target")
    assert _signal(fake, REVIEW_CHECK_RUN)["conclusion"] == "blocked"
    _, fake = _sweep(security, fake)
    assert check_runs_named(fake, SECURITY_CHECK_RUN) == []

    fake.review_threads[PULL_NUMBER] = [build_review_thread(is_resolved=True)]
    _, fake = _sweep(review, fake)
    assert _signal(fake, REVIEW_CHECK_RUN)["conclusion"] == "pass"

    writes_before = len(fake.write_calls)
    output, fake = _sweep(security, fake)
    assert "dependencies have passed but the stage has not started" in output
    assert len(fake.write_calls) == writes_before and _backend_comments(fake) == []

    proceed, fake = _eligibility(security, fake, "check_suite")
    assert proceed is True, "the next execute run starts it"


def test_upstream_signal_forged_by_another_app_never_starts_the_stage() -> None:
    _, security = _render_pair()
    fake = _world()
    fake.check_runs.append({
        "id": 500, "app": {"id": int(FOREIGN_APP_ID)}, "name": REVIEW_CHECK_RUN, "head_sha": HEAD_SHA,
        "status": "completed", "conclusion": "success",
        "output": {"title": "x", "summary": json.dumps({
            "schemaVersion": 1, "stageId": "review", "headSha": HEAD_SHA,
            "state": "completed", "conclusion": "pass"})}})
    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is False and fake.write_calls == []


def test_stale_wakeup_for_a_superseded_head_starts_nothing() -> None:
    review, security = _render_pair()
    fake = _publish(review, _world(), "pull_request_target")
    proceed, fake = _eligibility(security, fake, "check_run", head_sha=OLD_HEAD_SHA)
    assert proceed is False


def test_route_that_excludes_the_stage_stops_it_before_any_invocation() -> None:
    fast_path = FastPathPolicy(match=PathMatchSpec(paths=("docs/**",)),
                               stages=RouteStageMap(fast=("review",), normal=("review", "security")))
    review, security = _render_pair(fast_path)
    fake = _world()
    fake.check_runs.append(build_route_check_run("FAST"))
    fake = _publish(review, fake, "pull_request_target")
    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is False and _backend_comments(fake) == []

    fake.check_runs[0] = build_route_check_run("NORMAL")
    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is True


def test_untrusted_author_is_stopped_by_the_eligibility_step_for_the_dependency_stage() -> None:
    review, security = _render_pair()
    fake = _publish(review, _world(), "pull_request_target")
    fake.pull_requests[PULL_NUMBER]["author_association"] = "NONE"
    writes_before = len(fake.write_calls)
    proceed, fake = _eligibility(security, fake, "check_run")
    assert proceed is False and len(fake.write_calls) == writes_before
