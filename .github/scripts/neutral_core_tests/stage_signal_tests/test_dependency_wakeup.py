"""Dependency wake-up path (issue #207): an upstream signal changes, no new push happens.

A ``check_run`` / ``check_suite`` wake-up runs the same execute job as a pull request event, with
the pull request and head taken from the event payload. It differs in one respect only: a stage
whose own signal is already final (``pass`` or ``failed``) is left alone, so unrelated Check Run
chatter can never turn a failed backend into a retry loop (only a re-run of the execute job retries).
"""
from __future__ import annotations

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    build_dependency_world,
    build_stage_signal_check_run,
    build_upstream_check_run,
    check_runs_named,
    downstream_config_document,
    downstream_signal,
)
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    build_issue_comment,
    build_summary_body,
)
from neutral_core_tests.stage_signal_tests.job_simulation import run_execute_job

WAKEUP_EVENTS = ("check_run", "check_suite")


def _run(fake, event_name: str = "check_run", **arguments):
    return run_execute_job(fake, downstream_config_document(), event_name=event_name, **arguments)


def test_upstream_pass_arriving_via_a_check_run_event_starts_the_downstream_stage() -> None:
    fake = build_dependency_world()
    opened = run_execute_job(fake, downstream_config_document())
    assert opened.proceed is False and fake.write_calls == [], "the stage waits for the upstream"

    fake.check_runs.append(build_upstream_check_run("completed", "pass"))
    woken = _run(fake, "check_run")

    assert woken.proceed is True and set(woken.exit_codes.values()) == {0}, woken.transcripts
    (comment,) = fake.comments_posted_by_writes()
    assert comment["body"].startswith("@codex security review\n")
    assert downstream_signal(fake)["state"] == "running"


def test_upstream_pass_arriving_via_a_check_suite_event_starts_the_downstream_stage() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    woken = _run(fake, "check_suite")
    assert woken.proceed is True and len(fake.comments_posted_by_writes()) == 1
    assert downstream_signal(fake)["state"] == "running"


def test_wakeup_about_a_superseded_head_starts_nothing() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    for event_name in WAKEUP_EVENTS:
        woken = _run(fake, event_name, event_head_sha=OLD_HEAD_SHA)
        assert woken.proceed is False and "stale" in woken.transcripts["eligibility"]
    assert fake.write_calls == []


def test_wakeup_does_not_start_the_stage_while_the_upstream_has_not_passed() -> None:
    for event_name in WAKEUP_EVENTS:
        fake = build_dependency_world([build_upstream_check_run("completed", "blocked")])
        woken = _run(fake, event_name)
        assert woken.proceed is False and fake.write_calls == []


def test_wakeup_for_an_event_without_a_pull_request_does_nothing() -> None:
    """A fork pull request's Check Run event names no pull request, so it cannot be serialized."""
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    woken = _run(fake, "check_run", pull_number="")
    assert woken.proceed is False and fake.write_calls == []


def test_repeated_wakeups_neither_invoke_again_nor_write_again() -> None:
    """The self-trigger loop guard: the stage's own Check Run events wake it, and it goes quiet."""
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    _run(fake, "check_run")
    writes_after_start = len(fake.write_calls)
    for event_name in WAKEUP_EVENTS * 3:
        woken = _run(fake, event_name)
        assert set(woken.exit_codes.values()) == {0}
    assert len(fake.write_calls) == writes_after_start, "no comment and no Check Run write"
    assert len(fake.comments_posted_by_writes()) == 1
    assert len(check_runs_named(fake, "stagr/stage/security")) == 1


def test_wakeup_leaves_a_failed_stage_alone_but_a_pull_request_event_retries_it() -> None:
    failed = build_stage_signal_check_run("security", "failed", "failed", check_run_id=80)
    fake = build_dependency_world([build_upstream_check_run("completed", "pass"), failed])
    for event_name in WAKEUP_EVENTS:
        woken = _run(fake, event_name)
        assert woken.proceed is False and "already final" in woken.transcripts["eligibility"]
    assert fake.write_calls == [], "no retry, no invocation, no rewrite"

    retried = run_execute_job(fake, downstream_config_document(), event_name="pull_request_target")
    assert retried.proceed is True and len(fake.comments_posted_by_writes()) == 1
    assert downstream_signal(fake)["state"] == "running"
    assert len(check_runs_named(fake, "stagr/stage/security")) == 1, "replaced in place"


def test_wakeup_leaves_a_passed_stage_alone() -> None:
    passed = build_stage_signal_check_run("security", "completed", "pass", check_run_id=80)
    fake = build_dependency_world([build_upstream_check_run("completed", "pass"), passed])
    for event_name in WAKEUP_EVENTS:
        assert _run(fake, event_name).proceed is False
    assert fake.write_calls == []


def test_wakeup_still_completes_a_stage_that_is_running_when_its_evidence_has_arrived() -> None:
    running = build_stage_signal_check_run("security", "running", "unknown", check_run_id=80)
    fake = build_dependency_world(
        [build_upstream_check_run("completed", "pass"), running],
        comments=[build_issue_comment(build_summary_body())])
    woken = _run(fake, "check_suite")
    assert woken.exit_codes["publish"] == 0
    assert downstream_signal(fake)["state"] == "completed"
    assert fake.comments_posted_by_writes() == [], "completion evidence exists: nothing to invoke"


def test_wakeup_propagates_a_dependency_failure_as_the_creator_without_invoking() -> None:
    fake = build_dependency_world([build_upstream_check_run("failed", "failed")])
    woken = _run(fake, "check_run")
    assert woken.proceed is False and fake.comments_posted_by_writes() == []
    assert downstream_signal(fake)["state"] == "failed"
    write_count = len(fake.write_calls)
    _run(fake, "check_suite")
    assert len(fake.write_calls) == write_count, "failed is terminal for later wake-ups"


def test_upstream_recovering_does_not_restart_a_downstream_stage_that_already_failed() -> None:
    fake = build_dependency_world([build_upstream_check_run("failed", "failed")])
    _run(fake, "check_run")
    fake.check_runs[0] = build_upstream_check_run("completed", "pass")
    woken = _run(fake, "check_run")
    assert woken.proceed is False and downstream_signal(fake)["state"] == "failed"
    assert fake.comments_posted_by_writes() == []
    retried = run_execute_job(fake, downstream_config_document())
    assert retried.proceed is True and downstream_signal(fake)["state"] == "running"


def test_wakeup_never_lets_an_untrusted_pull_request_start_the_stage() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "pass")])
    fake.pull_requests[7]["author_association"] = "NONE"
    assert _run(fake, "check_run").proceed is False and fake.write_calls == []


def test_signal_for_the_new_head_is_independent_of_the_previous_heads_outcome() -> None:
    previous = build_stage_signal_check_run(
        "security", "completed", "pass", head_sha=OLD_HEAD_SHA, check_run_id=90)
    upstream_old = build_upstream_check_run("completed", "pass", head_sha=OLD_HEAD_SHA, check_run_id=91)
    fake = build_dependency_world([previous, upstream_old])
    assert _run(fake, "check_run").proceed is False, "the new head has no upstream signal yet"
    fake.check_runs.append(build_upstream_check_run("completed", "pass", check_run_id=92))
    assert _run(fake, "check_run").proceed is True
    assert {run["head_sha"] for run in check_runs_named(fake, "stagr/stage/security")} == {
        OLD_HEAD_SHA, HEAD_SHA}
