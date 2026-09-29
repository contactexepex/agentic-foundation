"""Scheduled sweep and dependencies (issue #207).

The sweep re-reads the upstream signals of every open pull request, so a ``BLOCKED -> PASS`` flip of
an upstream stage (which may raise no ``check_run: completed`` event) is seen on the next tick. What
the sweep can DO with that is limited on purpose: it holds only the App token and never the backend
secret, and only the execute job creates a stage's Check Run. So the sweep

- updates an existing downstream signal (complete it when its evidence and dependencies allow it,
  fail it when an upstream failed, leave it when an upstream has not passed);
- never invokes the backend and never creates a Check Run; a downstream stage that has not started
  yet starts the next time its execute job runs (a wake-up event, a reopen, a re-run).
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    build_dependency_world,
    build_route_check_run,
    build_routing_document,
    build_stage_signal_check_run,
    build_upstream_check_run,
    check_runs_named,
    downstream_config_document,
    downstream_signal,
)
from neutral_core_tests.stage_signal_tests.fake_github import REPOSITORY, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    build_issue_comment,
    build_summary_body,
)
from neutral_core_tests.stage_signal_tests.job_simulation import run_execute_job
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _sweep(fake: FakeGitHubApi, **config_overrides) -> tuple[int, str]:
    config = runtime.StageRuntimeConfig.from_json_text(
        json.dumps(downstream_config_document(**config_overrides)))
    reconciler = runtime.StageReconciler(config, fake, REPOSITORY, None)
    output = io.StringIO()
    with redirect_stdout(output):
        failures = runtime.OpenPullRequestSweeper(fake, REPOSITORY, reconciler).sweep()
    return failures, output.getvalue()


def _downstream_running() -> dict:
    return build_stage_signal_check_run("security", "running", "unknown", check_run_id=80)


def _evidence() -> list[dict]:
    return [build_issue_comment(build_summary_body())]


def test_blocked_to_pass_upstream_is_seen_by_the_sweep_but_it_cannot_start_the_stage() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "blocked")])
    assert run_execute_job(fake, downstream_config_document()).proceed is False

    fake.check_runs[0] = build_upstream_check_run("completed", "pass")
    failures, output = _sweep(fake)

    assert failures == 0
    assert "dependencies have passed but the stage has not started" in output
    assert fake.write_calls == [], "the sweep neither creates the Check Run nor posts a comment"
    assert downstream_signal(fake) is None


def test_the_next_execute_run_after_the_sweep_starts_the_stage() -> None:
    fake = build_dependency_world([build_upstream_check_run("completed", "blocked")])
    fake.check_runs[0] = build_upstream_check_run("completed", "pass")
    _sweep(fake)
    woken = run_execute_job(fake, downstream_config_document(), event_name="check_suite")
    assert woken.proceed is True and len(fake.comments_posted_by_writes()) == 1
    assert downstream_signal(fake)["state"] == "running"


def test_the_sweep_completes_a_running_downstream_stage_once_its_dependencies_passed() -> None:
    fake = build_dependency_world(
        [build_upstream_check_run("completed", "pass"), _downstream_running()], comments=_evidence())
    failures, _ = _sweep(fake)
    assert failures == 0 and downstream_signal(fake)["state"] == "completed"
    assert len(check_runs_named(fake, "stagr/stage/security")) == 1
    assert [call[0] for call in fake.write_calls] == ["PATCH"]


def test_the_sweep_does_not_complete_a_downstream_stage_whose_dependency_has_not_passed() -> None:
    fake = build_dependency_world(
        [build_upstream_check_run("completed", "blocked"), _downstream_running()], comments=_evidence())
    _sweep(fake)
    assert downstream_signal(fake)["state"] == "running" and fake.write_calls == []


def test_the_sweep_fails_an_existing_downstream_signal_when_a_dependency_failed() -> None:
    fake = build_dependency_world(
        [build_upstream_check_run("failed", "failed"), _downstream_running()], comments=_evidence())
    _sweep(fake)
    assert downstream_signal(fake)["state"] == "failed"
    assert [call[0] for call in fake.write_calls] == ["PATCH"]
    assert fake.comments_posted_by_writes() == []


def test_the_sweep_never_creates_the_downstream_signal_even_for_a_failed_dependency() -> None:
    fake = build_dependency_world([build_upstream_check_run("failed", "failed")])
    failures, output = _sweep(fake)
    assert failures == 0 and fake.write_calls == [] and downstream_signal(fake) is None
    assert "the execute job publishes the failure" in output


def test_the_sweep_treats_a_failed_downstream_signal_as_terminal() -> None:
    failed = build_stage_signal_check_run("security", "failed", "failed", check_run_id=80)
    fake = build_dependency_world([build_upstream_check_run("completed", "pass"), failed],
                                  comments=_evidence())
    _sweep(fake)
    assert fake.write_calls == [] and downstream_signal(fake)["state"] == "failed"


def test_the_sweep_ignores_an_upstream_signal_forged_by_another_app() -> None:
    forged = build_upstream_check_run("completed", "pass", app_id="15368")
    fake = build_dependency_world([forged, _downstream_running()], comments=_evidence())
    _sweep(fake)
    assert downstream_signal(fake)["state"] == "running" and fake.write_calls == []


def test_the_sweep_reports_duplicate_upstream_signals_as_a_failure_without_writing() -> None:
    duplicates = [build_upstream_check_run("completed", "pass"),
                  build_upstream_check_run("completed", "pass", check_run_id=301)]
    fake = build_dependency_world(duplicates + [_downstream_running()], comments=_evidence())
    failures, output = _sweep(fake)
    assert failures == 1 and "::error::Pull request #7" in output and fake.write_calls == []


def test_the_sweep_skips_untrusted_pull_requests_and_route_mismatches_before_dependencies() -> None:
    untrusted = build_dependency_world(
        [build_upstream_check_run("failed", "failed"), _downstream_running()])
    untrusted.pull_requests[7]["author_association"] = "NONE"
    _sweep(untrusted)
    assert untrusted.write_calls == []

    off_route = build_dependency_world(
        [build_route_check_run("FAST"), build_upstream_check_run("failed", "failed"),
         _downstream_running()])
    _sweep(off_route, routing=build_routing_document())
    assert off_route.write_calls == []


def test_the_sweep_needs_no_backend_secret_and_posts_no_comment_in_any_case() -> None:
    fake = build_dependency_world(
        [build_upstream_check_run("completed", "pass"), _downstream_running()], comments=[])
    _sweep(fake)
    assert fake.comments_posted_by_writes() == []
    for method, path, _ in fake.write_calls:
        assert method == "PATCH" and "/check-runs/" in path, (method, path)
