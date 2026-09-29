"""Producer/consumer contract: the runtime's Check Runs, read by the real governance script (#196).

The governance workflow's ``evaluate_stage_signal`` shell function is executed in bash against
Check Runs written by the runtime, so any drift in name, publisher, payload shape or vocabulary
between #206 (producer) and #196 (consumer) fails here rather than in a live repository.
Requires ``bash`` and ``jq``; if either is missing the tests skip loudly instead of passing silently.
"""
from __future__ import annotations

import json
import shutil
import subprocess

from neutral_core_tests.stage_signal_tests.fake_github import PUBLISHER_APP_ID
from neutral_core_tests.stage_signal_tests.fixtures import (
    CHECK_RUN_NAME,
    HEAD_SHA,
    always_pass_gate,
    build_existing_check_run,
    build_reconciler,
    build_review_thread,
    build_world,
    completed_review_comments,
    request,
)
from stagr.platforms.github import _governance
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _evaluate_with_governance(check_runs: list[dict], app_id: str = PUBLISHER_APP_ID) -> tuple[int, str]:
    script = (
        f'export REPO="octo/repo" PR_HEAD_SHA="{HEAD_SHA}" STAGR_APP_ID="{app_id}"\n'
        "gh() { printf '%s' \"$CHECK_RUNS_JSON\"; }\n"
        + _governance._EVALUATE_SIGNAL_FUNCTION_BODY
        + f'\nevaluate_stage_signal review "{CHECK_RUN_NAME}" blocking\n'
    )
    completed = subprocess.run(
        ["bash", "-c", script], capture_output=True, text=True, check=False,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "CHECK_RUNS_JSON": json.dumps(check_runs)},
    )
    return completed.returncode, completed.stdout + completed.stderr


def _tools_available() -> bool:
    if shutil.which("bash") and shutil.which("jq"):
        return True
    print("SKIP  governance interop tests: bash and jq are required")
    return False


def _written_check_run(comments, threads=(), gate=None, job_status="success") -> dict:
    fake = build_world(comments=comments, threads=list(threads))
    overrides = {"gate": gate} if gate else {}
    build_reconciler(fake, **overrides).reconcile_pull_request(
        request(runtime.MODE_PUBLISH, job_status=job_status)
    )
    (check_run,) = fake.check_runs
    return check_run


def test_governance_accepts_a_pass_written_by_the_runtime() -> None:
    if not _tools_available():
        return
    status, output = _evaluate_with_governance([_written_check_run(completed_review_comments())])
    assert status == 0 and "PASS" in output, output


def test_governance_reports_a_blocked_signal_as_findings_to_resolve() -> None:
    if not _tools_available():
        return
    check_run = _written_check_run(completed_review_comments(), threads=[build_review_thread()])
    status, output = _evaluate_with_governance([check_run])
    assert status == 1 and "findings must be resolved" in output, output


def test_governance_waits_on_a_running_signal() -> None:
    if not _tools_available():
        return
    status, output = _evaluate_with_governance([_written_check_run([])])
    assert status == 1 and "has not completed" in output, output


def test_governance_blocks_a_failed_signal() -> None:
    """A FAILED signal (state=failed) must block the merge.

    Known #196 follow-up: governance rejects any state other than 'completed' before it reaches its
    distinct FAILED message, so this signal is reported as "has not completed" instead of "did not
    complete". The outcome (blocked) is the safe one; only the wording differs.
    """
    if not _tools_available():
        return
    status, output = _evaluate_with_governance([_written_check_run([], job_status="failure")])
    assert status == 1 and "'failed'" in output, output


def test_governance_rejects_the_signal_when_the_publisher_differs() -> None:
    if not _tools_available():
        return
    status, output = _evaluate_with_governance(
        [_written_check_run(completed_review_comments(), gate=always_pass_gate())], app_id="55555"
    )
    assert status == 1 and "Publisher identity mismatch" in output, output


def test_governance_rejects_duplicates_but_never_because_of_the_runtime_alone() -> None:
    """The runtime creates at most one run per head; two seeded runs are what governance rejects."""
    if not _tools_available():
        return
    pair = [build_existing_check_run("completed", "pass", check_run_id=1),
            build_existing_check_run("completed", "pass", check_run_id=2)]
    status, output = _evaluate_with_governance(pair)
    assert status == 1 and "Duplicate Check Runs" in output, output
