"""Publish mode (execute job): the only mode that creates the stage's Check Run."""
from __future__ import annotations

import json

from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    PULL_NUMBER,
    always_pass_gate,
    build_existing_check_run,
    build_pull_request,
    build_reconciler,
    build_review_thread,
    build_world,
    completed_review_comments,
    request,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

PUBLISH = runtime.MODE_PUBLISH


def _payload(check_run: dict) -> dict:
    return json.loads(check_run["output"]["summary"])


def test_publish_without_evidence_creates_a_running_check_run() -> None:
    fake = build_world()
    result = build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert result.action == "created"
    (check_run,) = fake.check_runs
    assert _payload(check_run)["state"] == "running" and check_run["status"] == "in_progress"


def test_publish_with_clean_completed_evidence_creates_a_pass() -> None:
    fake = build_world(comments=completed_review_comments())
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    (check_run,) = fake.check_runs
    assert (_payload(check_run)["state"], _payload(check_run)["conclusion"]) == ("completed", "pass")


def test_publish_is_idempotent_and_never_writes_twice_for_the_same_state() -> None:
    fake = build_world()
    reconciler = build_reconciler(fake)
    reconciler.reconcile_pull_request(request(PUBLISH))
    second = reconciler.reconcile_pull_request(request(PUBLISH))
    assert second.action == "unchanged" and len(fake.write_calls) == 1


def test_publish_never_overwrites_a_terminal_pass() -> None:
    fake = build_world()
    fake.check_runs.append(build_existing_check_run("completed", "pass"))
    result = build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert result.action == "skipped" and not fake.write_calls


def test_failed_job_publishes_failed_signal() -> None:
    fake = build_world()
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH, job_status="failure"))
    (check_run,) = fake.check_runs
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "failure")
    assert _payload(check_run)["state"] == "failed"


def test_retry_after_failure_returns_the_same_check_run_to_running() -> None:
    fake = build_world()
    fake.check_runs.append(build_existing_check_run("failed", "failed"))
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    (check_run,) = fake.check_runs
    assert _payload(check_run)["state"] == "running"


def test_plan_without_evidence_completes_from_the_invocation_outcome() -> None:
    fake = build_world()
    reconciler = build_reconciler(fake, evidence=[], gate=always_pass_gate(), trustedRoles=["OWNER"])
    reconciler.reconcile_pull_request(request(PUBLISH, job_status="success"))
    (check_run,) = fake.check_runs
    assert (_payload(check_run)["state"], _payload(check_run)["conclusion"]) == ("completed", "pass")


def test_plan_without_evidence_reports_failure_when_the_job_failed() -> None:
    fake = build_world()
    reconciler = build_reconciler(fake, evidence=[], gate=always_pass_gate())
    reconciler.reconcile_pull_request(request(PUBLISH, job_status="failure"))
    assert _payload(fake.check_runs[0])["state"] == "failed"


def test_stale_event_head_publishes_nothing() -> None:
    fake = build_world()
    result = build_reconciler(fake).reconcile_pull_request(
        request(PUBLISH, event_head_sha=OLD_HEAD_SHA)
    )
    assert result.action == "skipped" and not fake.check_runs


def test_untrusted_author_publishes_nothing() -> None:
    fake = build_world(pull_request=build_pull_request(author_association="CONTRIBUTOR"))
    assert build_reconciler(fake).reconcile_pull_request(request(PUBLISH)).action == "skipped"
    assert not fake.check_runs


def test_fork_pull_request_is_refused_when_forks_are_denied() -> None:
    fake = build_world(pull_request=build_pull_request(is_fork=True))
    assert build_reconciler(fake).reconcile_pull_request(request(PUBLISH)).action == "skipped"


def test_fork_pull_request_is_refused_for_a_privileged_stage_even_when_forks_are_allowed() -> None:
    fake = build_world(pull_request=build_pull_request(is_fork=True))
    reconciler = build_reconciler(fake, denyForks=False, privilegedStage=True)
    assert reconciler.reconcile_pull_request(request(PUBLISH)).action == "skipped"


def test_fork_pull_request_may_drive_an_unprivileged_stage_when_forks_are_allowed() -> None:
    fake = build_world(pull_request=build_pull_request(is_fork=True))
    reconciler = build_reconciler(fake, denyForks=False, privilegedStage=False)
    assert reconciler.reconcile_pull_request(request(PUBLISH)).action == "created"


def test_deleted_fork_repository_is_treated_as_a_fork() -> None:
    pull = build_pull_request()
    pull["head"]["repo"] = None
    fake = build_world(pull_request=pull)
    assert build_reconciler(fake).reconcile_pull_request(request(PUBLISH)).action == "skipped"


def test_closed_pull_request_publishes_nothing() -> None:
    fake = build_world(pull_request=build_pull_request(state="closed"))
    assert build_reconciler(fake).reconcile_pull_request(request(PUBLISH)).action == "skipped"


def test_infrastructure_error_while_reading_evidence_publishes_failed() -> None:
    fake = build_world()
    fake.failing_path_fragments.add(f"issues/{PULL_NUMBER}/comments")
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    (check_run,) = fake.check_runs
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "failure")


def test_infrastructure_error_while_counting_threads_publishes_failed() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.failing_path_fragments.add("graphql")
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert _payload(fake.check_runs[0])["state"] == "failed"


def test_duplicate_check_runs_refuse_to_write() -> None:
    fake = build_world()
    fake.check_runs += [build_existing_check_run("running", "unknown", check_run_id=1),
                        build_existing_check_run("running", "unknown", check_run_id=2)]
    try:
        build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    except runtime.AmbiguousSignalError:
        assert not fake.write_calls
        return
    raise AssertionError("duplicate Check Runs must raise AmbiguousSignalError")


def test_check_run_of_another_app_is_ignored_and_never_updated() -> None:
    fake = build_world()
    fake.check_runs.append(build_existing_check_run("running", "unknown", app_id="12345"))
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert len(fake.check_runs) == 2 and fake.check_runs[0]["status"] == "in_progress"
    assert fake.write_calls[0][0] == "POST"


def test_check_run_for_an_older_head_is_not_reused() -> None:
    fake = build_world()
    fake.check_runs.append(build_existing_check_run("completed", "pass", head_sha=OLD_HEAD_SHA))
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert {run["head_sha"] for run in fake.check_runs} == {OLD_HEAD_SHA, HEAD_SHA}


def test_failure_to_list_check_runs_propagates_and_writes_nothing() -> None:
    fake = build_world()
    fake.failing_path_fragments.add("check-runs")
    try:
        build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    except runtime.GitHubApiError:
        assert not fake.write_calls
        return
    raise AssertionError("a failed Check Run listing must not be papered over")


def test_open_thread_from_the_current_review_blocks_a_completed_review() -> None:
    fake = build_world(comments=completed_review_comments(), threads=[build_review_thread()])
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    assert _payload(fake.check_runs[0])["conclusion"] == "blocked"


def test_graphql_response_missing_the_pull_request_publishes_failed_instead_of_crashing() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.run_graphql = lambda query, variables: {"data": {"repository": {"pullRequest": None}}}
    build_reconciler(fake).reconcile_pull_request(request(PUBLISH))
    (check_run,) = fake.check_runs
    assert _payload(check_run)["state"] == "failed"
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "failure")
