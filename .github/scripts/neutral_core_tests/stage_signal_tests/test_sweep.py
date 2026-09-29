"""Scheduled sweep: enumerate open pull requests, then run the same routine for each."""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from neutral_core_tests.stage_signal_tests.fake_github import REPOSITORY, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    always_pass_gate,
    build_existing_check_run,
    build_issue_comment,
    build_pull_request,
    build_reconciler,
    build_review_thread,
    build_summary_body,
    build_world,
    completed_review_comments,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

SECOND_HEAD_SHA = "9e8d7c6b5a49382716051423324150607f8e9d0c"


def _sweep(fake: FakeGitHubApi, **config_overrides) -> tuple[int, str]:
    reconciler = build_reconciler(fake, **config_overrides)
    output = io.StringIO()
    with redirect_stdout(output):
        failures = runtime.OpenPullRequestSweeper(fake, REPOSITORY, reconciler).sweep()
    return failures, output.getvalue()


def _two_pull_world() -> FakeGitHubApi:
    """PR 7 (trusted, review completed) and PR 8 (untrusted author, review completed)."""
    fake = build_world(comments=completed_review_comments())
    fake.add_pull_request(build_pull_request(number=8, head_sha=SECOND_HEAD_SHA, author_association="NONE"))
    fake.issue_comments[8] = [build_issue_comment(build_summary_body(
        code_review_sha=SECOND_HEAD_SHA[:7], security_sha=SECOND_HEAD_SHA))]
    fake.review_threads[8] = []
    fake.check_runs.append(build_existing_check_run("running", "unknown", check_run_id=1))
    fake.check_runs.append(build_existing_check_run(
        "running", "unknown", head_sha=SECOND_HEAD_SHA, check_run_id=2))
    return fake


def test_sweep_reconciles_the_trusted_pull_request_and_skips_the_untrusted_one() -> None:
    fake = _two_pull_world()
    failures, _ = _sweep(fake)
    assert failures == 0
    by_head = {run["head_sha"]: json.loads(run["output"]["summary"]) for run in fake.check_runs}
    assert by_head[HEAD_SHA]["conclusion"] == "pass"
    assert by_head[SECOND_HEAD_SHA]["state"] == "running"
    assert [call[1] for call in fake.write_calls] == [f"repos/{REPOSITORY}/check-runs/1"]


def test_sweep_skips_fork_pull_requests_when_forks_are_denied() -> None:
    fake = _two_pull_world()
    fake.pull_requests[8].update(build_pull_request(
        number=8, head_sha=SECOND_HEAD_SHA, is_fork=True))
    _sweep(fake)
    assert all(call[1].endswith("/1") for call in fake.write_calls)


def test_sweep_ignores_closed_pull_requests() -> None:
    fake = _two_pull_world()
    fake.pull_requests[7]["state"] = "closed"
    _sweep(fake)
    assert not fake.write_calls


def test_sweep_resolves_the_current_head_fresh_for_each_pull_request() -> None:
    """A run recorded for an old head is ignored; only the current head's run is reconciled."""
    fake = build_world(comments=completed_review_comments())
    fake.check_runs.append(build_existing_check_run("running", "unknown", head_sha=OLD_HEAD_SHA, check_run_id=5))
    fake.check_runs.append(build_existing_check_run("running", "unknown", check_run_id=6))
    _sweep(fake, gate=always_pass_gate())
    assert [call[1] for call in fake.write_calls] == [f"repos/{REPOSITORY}/check-runs/6"]


def test_sweep_never_creates_a_check_run() -> None:
    fake = build_world(comments=completed_review_comments())
    failures, _ = _sweep(fake, gate=always_pass_gate())
    assert failures == 0 and not fake.check_runs


def test_sweep_promotes_blocked_to_pass_after_threads_are_resolved_without_a_push() -> None:
    fake = build_world(comments=completed_review_comments(), threads=[build_review_thread()])
    fake.check_runs.append(build_existing_check_run("completed", "blocked"))
    _sweep(fake)
    assert json.loads(fake.check_runs[0]["output"]["summary"])["conclusion"] == "blocked"
    assert not fake.write_calls
    fake.review_threads[7] = [build_review_thread(is_resolved=True)]
    _sweep(fake)
    assert json.loads(fake.check_runs[0]["output"]["summary"])["conclusion"] == "pass"
    assert len(fake.check_runs) == 1


def test_sweep_isolates_a_failing_pull_request_and_reports_it() -> None:
    fake = _two_pull_world()
    fake.pull_requests[8]["author_association"] = "OWNER"
    fake.failing_path_fragments.add(f"commits/{SECOND_HEAD_SHA}/check-runs")
    failures, output = _sweep(fake)
    assert failures == 1 and "::error::Pull request #8" in output
    assert json.loads(fake.check_runs[0]["output"]["summary"])["conclusion"] == "pass"


def test_sweep_reports_duplicate_check_runs_as_a_failure_without_writing() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.check_runs += [build_existing_check_run("running", "unknown", check_run_id=1),
                        build_existing_check_run("running", "unknown", check_run_id=2)]
    failures, _ = _sweep(fake)
    assert failures == 1 and not fake.write_calls


def test_sweep_uses_the_pull_request_list_ordered_least_recently_updated_first() -> None:
    fake = build_world()
    requested_paths: list[str] = []
    original_get_items = fake.get_items
    fake.get_items = lambda path, items_key=None: (requested_paths.append(path), original_get_items(path, items_key))[1]
    _sweep(fake)
    assert "sort=updated&direction=asc" in requested_paths[0]


def test_sweep_ignores_draft_pull_requests() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.pull_requests[7]["draft"] = True
    fake.check_runs.append(build_existing_check_run("running", "unknown"))
    _sweep(fake, gate=always_pass_gate())
    assert not fake.write_calls
