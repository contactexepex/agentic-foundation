"""Entry point and CLI plumbing: real processes against a strict ``gh`` shim."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from neutral_core_tests.stage_signal_tests.fake_github import REPOSITORY, FakeGitHubApi, StrictGhCliShim
from neutral_core_tests.stage_signal_tests.process_runner import run_script_against_fake
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    OLD_HEAD_SHA,
    PULL_NUMBER,
    always_pass_gate,
    build_config_document,
    build_existing_check_run,
    build_world,
    completed_review_comments,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

RUNTIME_SOURCE = Path(runtime.__file__).read_text(encoding="utf-8")


def _run_runtime_process(fake: FakeGitHubApi, **environment_overrides: str) -> tuple[Any, FakeGitHubApi]:
    environment = {"STAGR_STAGE_CONFIG": json.dumps(build_config_document(gate=always_pass_gate()))}
    environment.update(environment_overrides)
    return run_script_against_fake(fake, RUNTIME_SOURCE, **environment)


def test_publish_through_the_gh_cli_creates_the_check_run_with_a_details_url() -> None:
    completed, state = _run_runtime_process(
        build_world(comments=completed_review_comments()),
        STAGR_MODE="publish", STAGR_PULL_NUMBER=str(PULL_NUMBER),
        STAGR_EVENT_HEAD_SHA=HEAD_SHA, STAGR_JOB_STATUS="success",
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    (check_run,) = state.check_runs
    assert json.loads(check_run["output"]["summary"])["conclusion"] == "pass"
    assert check_run["details_url"] == f"https://github.com/{REPOSITORY}/actions/runs/4242"


def test_reconcile_through_the_gh_cli_updates_the_existing_check_run() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.check_runs.append(build_existing_check_run("running", "unknown"))
    completed, state = _run_runtime_process(
        fake, STAGR_MODE="reconcile", STAGR_PULL_NUMBER=str(PULL_NUMBER)
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert [call[0] for call in state.write_calls] == ["PATCH"] and len(state.check_runs) == 1


def test_sweep_through_the_gh_cli_reconciles_open_pull_requests() -> None:
    fake = build_world(comments=completed_review_comments())
    fake.check_runs.append(build_existing_check_run("running", "unknown"))
    completed, state = _run_runtime_process(fake, STAGR_MODE="sweep")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(state.check_runs[0]["output"]["summary"])["conclusion"] == "pass"


def test_graphql_thread_query_is_accepted_by_the_strict_gh_shim() -> None:
    fake = build_world(comments=completed_review_comments())
    completed, state = _run_runtime_process(
        fake, STAGR_MODE="publish", STAGR_PULL_NUMBER=str(PULL_NUMBER),
        STAGR_STAGE_CONFIG=json.dumps(build_config_document()),
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert json.loads(state.check_runs[0]["output"]["summary"])["conclusion"] == "pass"


def test_missing_pull_request_context_publishes_nothing_and_succeeds() -> None:
    completed, state = _run_runtime_process(build_world(), STAGR_MODE="publish", STAGR_PULL_NUMBER="")
    assert completed.returncode == 0 and not state.write_calls
    assert "no pull request context" in completed.stdout


def test_stale_execute_event_publishes_nothing() -> None:
    completed, state = _run_runtime_process(
        build_world(), STAGR_MODE="publish", STAGR_PULL_NUMBER=str(PULL_NUMBER),
        STAGR_EVENT_HEAD_SHA=OLD_HEAD_SHA,
    )
    assert completed.returncode == 0 and not state.write_calls


def test_unknown_mode_fails_the_job() -> None:
    completed, _ = _run_runtime_process(build_world(), STAGR_MODE="bogus", STAGR_PULL_NUMBER="7")
    assert completed.returncode == 1 and "::error::" in completed.stdout


def test_missing_configuration_fails_the_job() -> None:
    completed, _ = _run_runtime_process(build_world(), STAGR_MODE="publish", STAGR_STAGE_CONFIG="{}")
    assert completed.returncode == 1 and "::error::" in completed.stdout


def test_github_api_failure_fetching_the_pull_request_fails_the_job() -> None:
    fake = build_world()
    fake.failing_path_fragments.add(f"pulls/{PULL_NUMBER}")
    completed, _ = _run_runtime_process(fake, STAGR_MODE="publish", STAGR_PULL_NUMBER=str(PULL_NUMBER))
    assert completed.returncode == 1 and "::error::" in completed.stdout


def test_strict_shim_rejects_flags_the_runtime_is_not_documented_to_use() -> None:
    """Harness self-check: this is the class of bug (``gh api --arg``) the shim exists to catch."""
    shim = StrictGhCliShim(build_world())
    try:
        for arguments in (["api", "--jq", "x", "repos/octo/repo/pulls/7"],
                          ["api", "--arg", "a", "repos/octo/repo/pulls/7"],
                          ["api", "--slurp", "repos/octo/repo/pulls/7"]):
            completed = subprocess.run(["gh", *arguments], env=shim.environment_with_shim_on_path(),
                                       capture_output=True, text=True, check=False)
            assert completed.returncode == 2, (arguments, completed.stdout, completed.stderr)
    finally:
        shim.cleanup()


def _scripted_process(results: list[SimpleNamespace], calls: list[dict[str, Any]]):
    def run_process(command, **keyword_arguments):
        calls.append({"command": command, **keyword_arguments})
        return results[len(calls) - 1]
    return run_process


def _result(returncode: int = 0, stdout: str = "[]") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="boom")


def test_get_items_requests_all_pages_and_flattens_them() -> None:
    calls: list[dict[str, Any]] = []
    pages = json.dumps([{"check_runs": [{"id": 1}]}, {"check_runs": [{"id": 2}]}])
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout=pages)], calls))
    assert api.get_items("repos/o/r/commits/x/check-runs", "check_runs") == [{"id": 1}, {"id": 2}]
    assert calls[0]["command"] == ["gh", "api", "--paginate", "--slurp", "repos/o/r/commits/x/check-runs"]
    flat = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout="[[1],[2,3]]")], []))
    assert flat.get_items("repos/o/r/issues/1/comments") == [1, 2, 3]


def test_reads_are_retried_with_backoff_but_writes_are_not() -> None:
    sleeps: list[float] = []
    calls: list[dict[str, Any]] = []
    api = runtime.GitHubCliApi(
        run_process=_scripted_process([_result(1), _result(1), _result(0, "{}")], calls),
        sleep=sleeps.append, retry_delay_seconds=1.0,
    )
    assert api.get_object("repos/o/r/pulls/1") == {}
    assert len(calls) == 3 and sleeps == [1.0, 2.0]
    write_calls: list[dict[str, Any]] = []
    writer = runtime.GitHubCliApi(run_process=_scripted_process([_result(1)], write_calls))
    try:
        writer.send_json("POST", "repos/o/r/check-runs", {"a": 1})
    except runtime.GitHubApiError:
        assert len(write_calls) == 1 and write_calls[0]["input"] == '{"a": 1}'
        return
    raise AssertionError("a failed write must raise")


def test_graphql_errors_in_a_successful_response_raise() -> None:
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout='{"errors":[{"m":1}]}')], []))
    try:
        api.run_graphql("query", {"number": 1})
    except runtime.GitHubApiError:
        return
    raise AssertionError("GraphQL errors must not be treated as an empty result")


def test_graphql_variables_are_typed_and_null_variables_are_omitted() -> None:
    calls: list[dict[str, Any]] = []
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout='{"data": {"ok": 1}}')], calls))
    api.run_graphql("Q", {"owner": "o", "number": 7, "cursor": None, "flag": True})
    assert calls[0]["command"] == ["gh", "api", "graphql", "-f", "query=Q", "-f", "owner=o",
                                   "-F", "number=7", "-f", "flag=True"]


def _rejects(**overrides: Any) -> bool:
    try:
        runtime.StageRuntimeConfig.from_json_text(json.dumps(build_config_document(**overrides)))
    except runtime.RuntimeConfigError:
        return True
    return False


def test_runtime_refuses_rules_it_cannot_evaluate_exactly() -> None:
    (review_rule,) = build_config_document()["evidence"]
    assert _rejects(evidence=[{**review_rule, "kind": "check_result"}])
    assert _rejects(evidence=[{**review_rule, "producedBy": ""}])
    assert _rejects(evidence=[{**review_rule, "shaField": "something_else"}])
    assert _rejects(evidence=[{**review_rule, "successCondition": "success"}])
    assert _rejects(gate={"kind": "bogus", "selector": "", "createdBy": "", "headShaBound": True})
    assert _rejects(gate={"kind": "no_open_threads", "selector": "", "createdBy": "", "headShaBound": True})
    assert _rejects(evidence=[], gate={"kind": "explicit_pass_marker", "selector": "m",
                                       "createdBy": "", "headShaBound": False})
    assert not _rejects()


def test_run_url_is_built_only_when_all_parts_are_known() -> None:
    assert runtime.build_run_url({"GITHUB_SERVER_URL": "https://h", "GITHUB_RUN_ID": "1",
                                  "GITHUB_REPOSITORY": "o/r"}) == "https://h/o/r/actions/runs/1"
    assert runtime.build_run_url({"GITHUB_RUN_ID": "1"}) is None


def test_invalid_json_from_gh_is_reported_as_a_github_api_error() -> None:
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout="<html>")] * 3, []),
                               sleep=lambda seconds: None)
    for read in (lambda: api.get_object("p"), lambda: api.get_items("p")):
        try:
            read()
        except runtime.GitHubApiError:
            continue
        raise AssertionError("invalid JSON must surface as GitHubApiError")


def test_unexpected_paginated_shape_is_reported_as_a_github_api_error() -> None:
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout='[{"other": []}]')], []))
    try:
        api.get_items("repos/o/r/commits/x/check-runs", "check_runs")
    except runtime.GitHubApiError:
        return
    raise AssertionError("a page without the expected key must not raise KeyError")


def test_graphql_response_without_data_is_reported_as_a_github_api_error() -> None:
    api = runtime.GitHubCliApi(run_process=_scripted_process([_result(stdout='{"data": null}')], []))
    try:
        api.run_graphql("query", {"number": 1})
    except runtime.GitHubApiError:
        return
    raise AssertionError("GraphQL data: null must not be treated as zero threads")
