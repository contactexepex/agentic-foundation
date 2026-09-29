"""Route applicability (issue #207): the stage runs only on the routes it is listed for.

The RouteClassification Check Run is trusted like a stage signal: written by the Stagr App,
exactly one for the head, bound to the head, and titled ``RouteClassification=FAST|NORMAL``.
Anything else fails closed. The classification may lag behind the stage workflow, so only the
eligibility step waits for it.
"""
from __future__ import annotations

import json
from typing import Any

from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    FOREIGN_APP_ID,
    ROUTE_CHECK_RUN_NAME,
    build_route_check_run,
    build_routing_document,
    build_stage_signal_check_run,
    downstream_config_document,
)
from neutral_core_tests.stage_signal_tests.fake_github import PUBLISHER_APP_ID, REPOSITORY, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    build_config_document,
    build_world,
)
from neutral_core_tests.stage_signal_tests.job_simulation import run_execute_job
from stagr.platforms.github.runtime import stage_signal_runtime as runtime


def _review_document(**routing_arguments: Any) -> dict[str, Any]:
    """``review`` with no dependencies, routed by the given (or the default) stage lists."""
    return build_config_document(routing=build_routing_document(**routing_arguments))


def _security_document(**routing_arguments: Any) -> dict[str, Any]:
    """``security`` (default: NORMAL route only) with no dependencies."""
    return downstream_config_document(
        dependencies=[], routing=build_routing_document(**routing_arguments))


def _world_with(*check_runs: dict[str, Any]) -> FakeGitHubApi:
    fake = build_world()
    fake.check_runs.extend(check_runs)
    return fake


def _route_reader(fake: FakeGitHubApi) -> runtime.RouteClassificationReader:
    return runtime.RouteClassificationReader(
        runtime.RouteRule(ROUTE_CHECK_RUN_NAME, frozenset(), frozenset()),
        runtime.StagrCheckRunReader(fake, REPOSITORY, PUBLISHER_APP_ID))


def test_stage_listed_for_the_current_route_starts() -> None:
    for route in ("FAST", "NORMAL"):
        fake = _world_with(build_route_check_run(route))
        outcome = run_execute_job(fake, _review_document())
        assert outcome.proceed is True, (route, outcome.transcripts)
        assert len(fake.comments_posted_by_writes()) == 1


def test_stage_not_applicable_to_the_route_gets_no_invocation_and_no_signal() -> None:
    fake = _world_with(build_route_check_run("FAST"))
    outcome = run_execute_job(fake, _security_document())
    assert outcome.proceed is False and "invoke" not in outcome.exit_codes
    assert fake.comments_posted_by_writes() == []
    assert [run["name"] for run in fake.check_runs] == [ROUTE_CHECK_RUN_NAME]
    assert "does not apply to the FAST route" in outcome.transcripts["eligibility"]


def test_stage_only_listed_for_fast_is_skipped_on_the_normal_route() -> None:
    fake = _world_with(build_route_check_run("NORMAL"))
    outcome = run_execute_job(fake, _review_document(fast=("review",), normal=("security",)))
    assert outcome.proceed is False and fake.write_calls == []


def test_stage_listed_for_neither_route_never_runs() -> None:
    for route in ("FAST", "NORMAL"):
        fake = _world_with(build_route_check_run(route))
        assert run_execute_job(fake, _review_document(fast=(), normal=())).proceed is False


def test_stage_without_a_route_rule_ignores_the_classification() -> None:
    fake = _world_with(build_route_check_run("FAST"))
    assert run_execute_job(fake, build_config_document()).proceed is True


def test_classification_published_by_another_app_is_ignored_and_the_stage_fails_closed() -> None:
    fake = _world_with(build_route_check_run("NORMAL", app_id=FOREIGN_APP_ID))
    outcome = run_execute_job(fake, _review_document())
    assert outcome.proceed is False and fake.comments_posted_by_writes() == []
    assert [run["name"] for run in fake.check_runs] == [ROUTE_CHECK_RUN_NAME]


def test_forged_classification_next_to_the_real_one_does_not_change_the_route() -> None:
    forged = build_route_check_run("NORMAL", app_id=FOREIGN_APP_ID, check_run_id=999)
    fake = _world_with(forged, build_route_check_run("FAST"))
    outcome = run_execute_job(fake, _security_document())
    assert outcome.proceed is False, "the real FAST classification decides, not the forged NORMAL"


def test_duplicate_classifications_fail_closed_with_an_error_and_no_invocation() -> None:
    fake = _world_with(build_route_check_run("NORMAL"), build_route_check_run("NORMAL", check_run_id=401))
    outcome = run_execute_job(fake, _review_document())
    assert outcome.exit_codes["eligibility"] == 1 and "::error::" in outcome.transcripts["eligibility"]
    assert "invoke" not in outcome.exit_codes and fake.comments_posted_by_writes() == []
    assert outcome.exit_codes["publish"] == 1, "the result step fails closed too"
    assert len(fake.check_runs) == 2, "and writes no signal"


def test_classification_that_is_not_fast_or_normal_is_refused_without_waiting() -> None:
    for title in ("RouteClassification=FASTER", "RouteClassification=", "fast",
                  "RouteClassification=fast", "Route=FAST", " "):
        fake = _world_with(build_route_check_run(title=title))
        sleeps: list[float] = []
        outcome = run_execute_job(fake, _review_document(), sleep=sleeps.append)
        assert outcome.proceed is False and sleeps == [], (title, sleeps)
        assert fake.comments_posted_by_writes() == []


def test_classification_bound_to_another_head_is_refused_and_not_waited_for() -> None:
    class ReaderReturningARunOfAnotherHead:
        def find_single(self, check_run_name: str, head_sha: str) -> runtime.ExistingSignalRun:
            return runtime.ExistingSignalRun(
                1, "completed", "success", None,
                title="RouteClassification=NORMAL", head_sha=OLD_HEAD_SHA)

    reader = runtime.RouteClassificationReader(
        runtime.RouteRule(ROUTE_CHECK_RUN_NAME, frozenset(), frozenset()),
        ReaderReturningARunOfAnotherHead())
    reading = reader.read(HEAD_SHA)
    assert reading.route is None and reading.is_missing is False
    assert "not bound to this head" in reading.reason


def test_classification_of_an_older_head_does_not_apply_to_the_new_head() -> None:
    fake = _world_with(build_route_check_run("NORMAL", head_sha=OLD_HEAD_SHA))
    outcome = run_execute_job(fake, _review_document())
    assert outcome.proceed is False and fake.comments_posted_by_writes() == []


def test_missing_classification_is_waited_for_then_the_stage_fails_closed() -> None:
    fake = _world_with()
    sleeps: list[float] = []
    outcome = run_execute_job(fake, _review_document(), sleep=sleeps.append)
    assert len(sleeps) == runtime.ROUTE_WAIT_ATTEMPTS - 1
    assert set(sleeps) == {runtime.ROUTE_WAIT_SECONDS}
    assert outcome.proceed is False and fake.write_calls == []
    assert "has not been published yet" in outcome.transcripts["eligibility"]


def test_classification_that_appears_while_waiting_lets_the_stage_start() -> None:
    fake = _world_with()
    sleeps: list[float] = []

    def publish_after_third_wait(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) == 3:
            fake.check_runs.append(build_route_check_run("NORMAL"))

    outcome = run_execute_job(fake, _review_document(), sleep=publish_after_third_wait)
    assert outcome.proceed is True and len(sleeps) == 3
    assert len(fake.comments_posted_by_writes()) == 1


def test_classification_that_is_still_running_is_waited_for() -> None:
    fake = _world_with(build_route_check_run("NORMAL", status="in_progress"))

    def finish_route(seconds: float) -> None:
        fake.check_runs[0].update(status="completed", conclusion="success")

    assert run_execute_job(fake, _review_document(), sleep=finish_route).proceed is True


def test_route_reading_tells_a_missing_classification_from_a_final_refusal() -> None:
    cases = (
        ([], True),
        ([build_route_check_run("FAST", status="queued")], True),
        ([build_route_check_run(title="RouteClassification=SLOW")], False),
    )
    for route_runs, expected_to_be_missing in cases:
        reading = _route_reader(_world_with(*route_runs)).read(HEAD_SHA)
        assert reading.route is None and reading.is_missing is expected_to_be_missing, reading


def test_publish_reconcile_and_sweep_read_the_classification_once_and_never_wait() -> None:
    fake = _world_with()
    listings: list[str] = []
    original_get_items = fake.get_items
    fake.get_items = lambda path, items_key=None: (
        listings.append(path), original_get_items(path, items_key))[1]
    reconciler = runtime.StageReconciler(
        runtime.StageRuntimeConfig.from_json_text(json.dumps(_review_document())), fake, REPOSITORY, None)
    for mode in (runtime.MODE_PUBLISH, runtime.MODE_RECONCILE, runtime.MODE_SWEEP):
        listings.clear()
        result = reconciler.reconcile_pull_request(runtime.ReconcileRequest(mode, 7))
        assert result.action == runtime.ACTION_SKIPPED, (mode, result)
        assert len([path for path in listings if "route-classification" in path]) == 1, mode
    assert fake.write_calls == []


def test_the_sweep_does_not_touch_a_stage_that_does_not_apply_to_the_route() -> None:
    fake = _world_with(
        build_route_check_run("FAST"),
        build_stage_signal_check_run("security", "running", "unknown", check_run_id=77))
    reconciler = runtime.StageReconciler(
        runtime.StageRuntimeConfig.from_json_text(json.dumps(_security_document())),
        fake, REPOSITORY, None)
    result = reconciler.reconcile_pull_request(runtime.ReconcileRequest(runtime.MODE_SWEEP, 7))
    assert result.action == runtime.ACTION_SKIPPED and "FAST route" in result.reason
    assert fake.write_calls == []
