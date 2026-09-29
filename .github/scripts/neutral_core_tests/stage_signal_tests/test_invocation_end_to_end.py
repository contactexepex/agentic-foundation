"""End to end: plan -> rendered workflow -> embedded runtime in invoke mode, via the strict gh shim.

Each run extracts the script and configuration from the RENDERED workflow and executes them as a
process exactly like the ``python3 -c`` step. The shim only accepts the tokens in
``fake.token_accounts``, answers ``gh api user`` for the token it was called with, and records every
token it sees, so a wrong or leaked credential is caught the way GitHub would catch it.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from neutral_core_tests.stage_signal_tests.fake_github import (
    COMMENTER_TOKEN,
    COMMENTER_USER,
    FakeGitHubApi,
)
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    PULL_NUMBER,
    build_issue_comment,
    build_summary_body,
    build_world,
)
from neutral_core_tests.stage_signal_tests.invocation_fixtures import build_marker_comment
from neutral_core_tests.stage_signal_tests.process_runner import run_script_against_fake
from neutral_core_tests.stage_signal_tests.render_helpers import render_codex_workflow
from stagr.core.enums import StageKind
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

APP_TOKEN = "app-installation-token-value"
APP_USER = {"id": 8001, "login": "stagr-app[bot]", "type": "Bot"}
ATTACKER = {"id": 666, "login": "attacker", "type": "User"}
MARKER_PATTERN = re.compile(r"<!-- stagr:stage:review:([0-9a-f]{40}):expires:([0-9TZ:-]{20}) -->")


def _world(comments: list[dict[str, Any]] | None = None) -> FakeGitHubApi:
    fake = build_world(comments=comments)
    fake.token_accounts = {COMMENTER_TOKEN: COMMENTER_USER, APP_TOKEN: APP_USER}
    return fake


def _run(workflow: dict, fake: FakeGitHubApi, mode: str, **environment: str) -> tuple[Any, FakeGitHubApi]:
    fake.used_tokens = []
    return run_script_against_fake(
        fake, workflow["env"]["STAGR_RUNTIME_SCRIPT"],
        STAGR_STAGE_CONFIG=workflow["env"]["STAGR_STAGE_CONFIG"], STAGR_MODE=mode, **environment)


def _invoke(workflow: dict, fake: FakeGitHubApi, **overrides: str) -> tuple[Any, FakeGitHubApi]:
    """The invoke step's environment: event data, the backend secret, and (leaked) nothing else."""
    environment = {"STAGR_PULL_NUMBER": str(PULL_NUMBER), "STAGR_EVENT_HEAD_SHA": HEAD_SHA,
                   "TRUSTED_COMMENTER_TOKEN": COMMENTER_TOKEN, "GH_TOKEN": APP_TOKEN}
    environment.update(overrides)
    return _run(workflow, fake, "invoke", **environment)


def _publish(workflow: dict, fake: FakeGitHubApi, job_status: str = "success") -> FakeGitHubApi:
    completed, state = _run(workflow, fake, "publish", GH_TOKEN=APP_TOKEN, STAGR_PULL_NUMBER=str(PULL_NUMBER),
                            STAGR_EVENT_HEAD_SHA=HEAD_SHA, STAGR_JOB_STATUS=job_status)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return state


def _posted_comments(fake: FakeGitHubApi) -> list[dict[str, Any]]:
    return [comment for comment in fake.issue_comments[PULL_NUMBER] if comment["id"] > 1000]


def _signal_state(fake: FakeGitHubApi) -> str:
    (check_run,) = fake.stage_check_runs(HEAD_SHA)
    return re.search(r'"state":"(\w+)"', check_run["output"]["summary"]).group(1)


def test_fresh_head_posts_one_invocation_as_the_backend_account_with_a_live_lease() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    completed, state = _invoke(workflow, _world())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    (comment,) = _posted_comments(state)
    assert comment["user"] == COMMENTER_USER and comment["body"].startswith("@codex review\n")
    marker_head, marker_expiry = MARKER_PATTERN.search(comment["body"]).groups()
    assert marker_head == HEAD_SHA
    expires_at = datetime.strptime(marker_expiry, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    remaining = expires_at - datetime.now(timezone.utc)
    assert timedelta(minutes=28) < remaining <= timedelta(minutes=30), remaining
    assert "invoked" in completed.stdout


def test_invoke_step_uses_only_the_backend_token_even_if_an_app_token_is_in_the_environment() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    completed, state = _invoke(workflow, _world())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert state.used_tokens and set(state.used_tokens) == {COMMENTER_TOKEN}


def test_a_repeated_run_is_idempotent_while_the_lease_is_live() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    _, after_first = _invoke(workflow, _world())
    completed, after_second = _invoke(workflow, after_first)
    assert completed.returncode == 0 and len(_posted_comments(after_second)) == 1
    assert "still in flight" in completed.stdout


def test_an_expired_lease_is_replaced_by_a_fresh_invocation() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    expired = build_marker_comment(datetime.now(timezone.utc) - timedelta(minutes=5))
    completed, state = _invoke(workflow, _world([expired]))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    (fresh,) = _posted_comments(state)
    assert fresh["id"] != expired["id"] and fresh["body"] != expired["body"]


def test_a_far_future_marker_forged_by_someone_else_does_not_suppress_the_invocation() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    forged = build_marker_comment(
        datetime.now(timezone.utc) + timedelta(days=3650), author=ATTACKER, author_association="NONE")
    completed, state = _invoke(workflow, _world([forged]))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(_posted_comments(state)) == 1


def test_completion_evidence_skips_the_invocation_and_publish_still_reports_the_result() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    fake = _world([build_issue_comment(build_summary_body())])
    completed, state = _invoke(workflow, fake)
    assert completed.returncode == 0 and state.write_calls == []
    assert "completion evidence" in completed.stdout
    published = _publish(workflow, state)
    assert _signal_state(published) == "completed"


def test_a_guard_skipped_invocation_still_lets_publish_report_running() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    in_flight = build_marker_comment(datetime.now(timezone.utc) + timedelta(minutes=10))
    completed, state = _invoke(workflow, _world([in_flight]))
    assert completed.returncode == 0 and state.write_calls == []
    assert _signal_state(_publish(workflow, state)) == "running"


def test_full_lifecycle_invoke_publish_then_backend_answers() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    _, invoked = _invoke(workflow, _world())
    published = _publish(workflow, invoked)
    assert _signal_state(published) == "running"
    published.issue_comments[PULL_NUMBER].append(build_issue_comment(build_summary_body(), comment_id=2))
    completed, reconciled = _run(workflow, published, "reconcile", GH_TOKEN=APP_TOKEN,
                                 STAGR_PULL_NUMBER=str(PULL_NUMBER))
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _signal_state(reconciled) == "completed"
    assert len(_posted_comments(reconciled)) == 1, "the wakeup must not re-invoke the backend"


def test_a_failed_invoke_step_fails_the_job_and_publish_reports_failed() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    completed, state = _invoke(workflow, _world(), TRUSTED_COMMENTER_TOKEN="revoked-token")
    assert completed.returncode == 1 and state.write_calls == [] and "::error::" in completed.stdout
    assert _signal_state(_publish(workflow, state, job_status="failure")) == "failed"


def test_missing_backend_token_fails_closed_without_touching_github() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    fake = _world()
    completed, state = _invoke(workflow, fake, TRUSTED_COMMENTER_TOKEN="")
    assert completed.returncode == 1 and "TRUSTED_COMMENTER_TOKEN" in completed.stdout
    assert state.write_calls == [] and state.used_tokens == []


def test_events_without_a_pull_request_invoke_nothing() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    completed, state = _invoke(workflow, _world(), STAGR_PULL_NUMBER="", STAGR_EVENT_HEAD_SHA="")
    assert completed.returncode == 0 and state.write_calls == [] and state.used_tokens == []


def test_the_scheduled_sweep_never_posts_an_invocation_even_when_the_lease_expired() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    expired = build_marker_comment(datetime.now(timezone.utc) - timedelta(hours=2))
    published = _publish(workflow, _world([expired]))
    completed, swept = _run(workflow, published, "sweep", GH_TOKEN=APP_TOKEN)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert _posted_comments(swept) == []
    assert not any(path.endswith("/comments") for _, path, _ in swept.write_calls)
    assert set(swept.used_tokens) == {APP_TOKEN}


def test_next_execute_run_recovers_the_expired_lease_the_sweep_left_alone() -> None:
    _, workflow = render_codex_workflow(StageKind.REVIEW)
    expired = build_marker_comment(datetime.now(timezone.utc) - timedelta(hours=2))
    _, swept = _run(workflow, _publish(workflow, _world([expired])), "sweep", GH_TOKEN=APP_TOKEN)
    completed, recovered = _invoke(workflow, swept)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert len(_posted_comments(recovered)) == 1
    assert runtime.parse_lease_expiries(_posted_comments(recovered)[0]["body"], "review", HEAD_SHA)


def test_security_stage_posts_its_own_command_and_marker() -> None:
    _, workflow = render_codex_workflow(StageKind.SECURITY)
    completed, state = _invoke(workflow, _world())
    assert completed.returncode == 0, completed.stdout + completed.stderr
    (comment,) = _posted_comments(state)
    assert comment["body"].startswith("@codex security review\n")
    assert f"<!-- stagr:stage:security:{HEAD_SHA}:expires:" in comment["body"]
