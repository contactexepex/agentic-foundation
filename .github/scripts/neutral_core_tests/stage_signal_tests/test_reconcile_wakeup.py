"""Reconcile mode (issue_comment wakeup): observes backend completion, updates in place only."""
from __future__ import annotations

import json

from neutral_core_tests.stage_signal_tests.fixtures import (
    OLD_HEAD_SHA,
    always_pass_gate,
    build_existing_check_run,
    build_issue_comment,
    build_reconciler,
    build_review_thread,
    build_summary_body,
    build_world,
    completed_review_comments,
    request,
)

RECONCILE = "reconcile"


def _payload(check_run: dict) -> dict:
    return json.loads(check_run["output"]["summary"])


def _world_with_running_check_run(**world_arguments):
    fake = build_world(**world_arguments)
    fake.check_runs.append(build_existing_check_run("running", "unknown"))
    return fake


def test_evidence_absent_on_wakeup_updates_no_check_run() -> None:
    fake = _world_with_running_check_run()
    result = build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert result.action == "skipped" and not fake.write_calls


def test_evidence_present_with_always_pass_updates_the_check_run_to_pass() -> None:
    fake = _world_with_running_check_run(comments=completed_review_comments())
    build_reconciler(fake, gate=always_pass_gate()).reconcile_pull_request(request(RECONCILE))
    (check_run,) = fake.check_runs
    assert (check_run["status"], check_run["conclusion"]) == ("completed", "success")
    assert _payload(check_run)["conclusion"] == "pass"


def test_evidence_present_with_open_threads_updates_the_check_run_to_blocked() -> None:
    fake = _world_with_running_check_run(
        comments=completed_review_comments(), threads=[build_review_thread()]
    )
    build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    (check_run,) = fake.check_runs
    assert check_run["conclusion"] == "action_required"
    assert _payload(check_run)["conclusion"] == "blocked"


def test_blocked_becomes_pass_in_place_once_threads_are_resolved_without_a_new_push() -> None:
    fake = _world_with_running_check_run(
        comments=completed_review_comments(), threads=[build_review_thread()]
    )
    reconciler = build_reconciler(fake)
    reconciler.reconcile_pull_request(request(RECONCILE))
    assert _payload(fake.check_runs[0])["conclusion"] == "blocked"
    fake.review_threads[7] = [build_review_thread(is_resolved=True)]
    result = reconciler.reconcile_pull_request(request(RECONCILE))
    assert result.action == "updated" and len(fake.check_runs) == 1
    assert _payload(fake.check_runs[0])["conclusion"] == "pass"
    assert [call[0] for call in fake.write_calls] == ["PATCH", "PATCH"]


def test_pass_is_terminal_and_not_reevaluated() -> None:
    fake = build_world(threads=[build_review_thread()])
    fake.check_runs.append(build_existing_check_run("completed", "pass"))
    fake.failing_path_fragments.add("graphql")  # would raise if the threads were queried
    result = build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert result.action == "skipped" and not fake.write_calls


def test_unchanged_conclusion_causes_no_write() -> None:
    fake = _world_with_running_check_run(
        comments=completed_review_comments(), threads=[build_review_thread()]
    )
    reconciler = build_reconciler(fake)
    reconciler.reconcile_pull_request(request(RECONCILE))
    second = reconciler.reconcile_pull_request(request(RECONCILE))
    assert second.action == "unchanged" and len(fake.write_calls) == 1


def test_wakeup_never_creates_a_check_run() -> None:
    fake = build_world(comments=completed_review_comments())
    result = build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert result.action == "skipped" and not fake.check_runs and not fake.write_calls


def test_evidence_that_disappears_does_not_regress_a_blocked_signal() -> None:
    fake = build_world(threads=[build_review_thread()])
    fake.check_runs.append(build_existing_check_run("completed", "blocked"))
    result = build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert result.action == "skipped" and not fake.write_calls


def test_failed_signal_recovers_when_evidence_arrives() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.check_runs.append(build_existing_check_run("failed", "failed"))
    build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert _payload(fake.check_runs[0])["conclusion"] == "pass"


def test_failed_signal_stays_failed_while_evidence_is_absent() -> None:
    fake = build_world()
    fake.check_runs.append(build_existing_check_run("failed", "failed"))
    build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert not fake.write_calls


def test_evidence_for_an_older_head_does_not_complete_the_current_head() -> None:
    stale = build_issue_comment(build_summary_body(code_review_sha=OLD_HEAD_SHA[:7]))
    fake = _world_with_running_check_run(comments=[stale])
    build_reconciler(fake).reconcile_pull_request(request(RECONCILE))
    assert not fake.write_calls


def test_forged_evidence_from_a_human_cannot_complete_the_stage() -> None:
    forged = build_issue_comment(build_summary_body(), login="attacker", user_type="User")
    fake = _world_with_running_check_run(comments=[forged])
    build_reconciler(fake, gate=always_pass_gate()).reconcile_pull_request(request(RECONCILE))
    assert not fake.write_calls


def test_stale_wakeup_for_a_superseded_head_is_ignored() -> None:
    fake = _world_with_running_check_run(comments=completed_review_comments())
    result = build_reconciler(fake, gate=always_pass_gate()).reconcile_pull_request(
        request(RECONCILE, event_head_sha=OLD_HEAD_SHA)
    )
    assert result.action == "skipped" and not fake.write_calls


def test_untrusted_author_is_not_reconciled() -> None:
    from neutral_core_tests.stage_signal_tests.fixtures import build_pull_request

    fake = _world_with_running_check_run(
        comments=completed_review_comments(),
        pull_request=build_pull_request(author_association="NONE"),
    )
    build_reconciler(fake, gate=always_pass_gate()).reconcile_pull_request(request(RECONCILE))
    assert not fake.write_calls


def test_wakeup_for_a_head_without_a_signal_does_not_touch_other_heads() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.check_runs.append(build_existing_check_run("running", "unknown", head_sha=OLD_HEAD_SHA))
    build_reconciler(fake, gate=always_pass_gate()).reconcile_pull_request(request(RECONCILE))
    assert not fake.write_calls
