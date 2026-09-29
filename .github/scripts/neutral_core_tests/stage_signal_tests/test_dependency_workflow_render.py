"""Rendered workflow structure for eligibility and dependency wake-ups (issue #207).

Structure assertions only (parsed with PyYAML); the ``if:`` guards and concurrency keys are also
EVALUATED against realistic event payloads with a small Actions expression evaluator, so what the
guards let through is tested, not just how they read.
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    build_execution_plan,
    build_render_context,
    build_stage,
)
from neutral_core_tests.stage_signal_tests.render_helpers import (
    build_codex_plan,
    parse_workflow,
    render_codex_workflow,
    render_workflow_text,
)
from neutral_core_tests.stage_signal_tests.workflow_expressions import (
    build_github_context,
    check_run_event,
    check_suite_event,
    evaluate_expression,
    is_truthy,
    pull_request_event,
    render_template,
)
from stagr.core.enums import StageKind
from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

STAGR_APP_ID = 99001
OTHER_APP_ID = 15368
UPSTREAM_NAME = "stagr/stage/review"
PROCEED_CONDITION = "${{ steps.eligibility.outputs.proceed == 'true' }}"
LINUX_MAX_ENVIRONMENT_STRING_BYTES = 131072


def _render_security_after_review(fast_path: FastPathPolicy | None = None) -> tuple[str, dict[str, Any]]:
    plan, stage = build_codex_plan(StageKind.SECURITY)
    stage = dataclasses.replace(stage, dependencies=("review",))
    upstream = dataclasses.replace(stage, id="review", dependencies=())
    context = dataclasses.replace(
        build_render_context(stage), stages=(upstream, stage),
        routing_policy=RoutingPolicy(fast_path=fast_path))
    text = render_workflow_text(plan, stage, context)
    return text, parse_workflow(text)


def _steps(document: dict[str, Any], job_name: str = "execute") -> dict[str, dict[str, Any]]:
    return {step["name"]: step for step in document["jobs"][job_name]["steps"]}


def _execute_runs(document: dict[str, Any], event_name: str, event: dict[str, Any]) -> bool:
    condition = document["jobs"]["execute"]["if"]
    return is_truthy(evaluate_expression(condition, build_github_context(event_name, event)))


def _concurrency_group(document: dict[str, Any], event_name: str, event: dict[str, Any]) -> str:
    return render_template(document["concurrency"]["group"], build_github_context(event_name, event))


def test_stage_with_dependencies_also_listens_to_completed_check_runs_and_suites() -> None:
    _, document = _render_security_after_review()
    assert document["on"]["check_run"] == {"types": ["completed"]}
    assert document["on"]["check_suite"] == {"types": ["completed"]}
    assert "synchronize" in document["on"]["pull_request_target"]["types"]


def test_stage_without_dependencies_keeps_exactly_its_previous_triggers() -> None:
    _, document = render_codex_workflow(StageKind.SECURITY)
    assert set(document["on"]) == {"pull_request_target", "issue_comment", "schedule"}
    plain = parse_workflow(render_workflow_text(build_execution_plan(), build_stage()))
    assert set(plain["on"]) == {"pull_request_target"}


def test_stage_with_dependencies_but_no_asynchronous_evidence_still_wakes_on_upstream_signals() -> None:
    stage = dataclasses.replace(build_stage("lint"), dependencies=("review",))
    upstream = build_stage("review")
    context = dataclasses.replace(build_render_context(stage), stages=(upstream, stage))
    document = parse_workflow(render_workflow_text(build_execution_plan("lint"), stage, context))
    assert list(document["jobs"]) == ["execute"]
    assert {"check_run", "check_suite"} <= set(document["on"])
    assert "issue_comment" not in document["on"] and "schedule" not in document["on"]


def test_execute_job_runs_for_pull_request_events_and_relevant_upstream_signals() -> None:
    _, document = _render_security_after_review()
    assert _execute_runs(document, "pull_request_target", pull_request_event())
    assert _execute_runs(document, "check_run", check_run_event(UPSTREAM_NAME, STAGR_APP_ID))
    assert _execute_runs(document, "check_suite", check_suite_event(STAGR_APP_ID))


def test_wakeups_about_unrelated_checks_never_run_any_job() -> None:
    _, document = _render_security_after_review()
    unrelated = {
        "own Check Run (self-trigger)": check_run_event("stagr/stage/security", STAGR_APP_ID),
        "route classification": check_run_event("stagr/route-classification", STAGR_APP_ID),
        "another stage's signal": check_run_event("stagr/stage/lint", STAGR_APP_ID),
        "upstream name forged by another app": check_run_event(UPSTREAM_NAME, OTHER_APP_ID),
        "ordinary CI check": check_run_event("build (ubuntu)", OTHER_APP_ID),
        "upstream signal without a pull request (fork)": check_run_event(UPSTREAM_NAME, STAGR_APP_ID, ()),
    }
    for label, event in unrelated.items():
        assert not _execute_runs(document, "check_run", event), label
    for label, event in {
        "suite of another app": check_suite_event(OTHER_APP_ID),
        "suite without a pull request": check_suite_event(STAGR_APP_ID, ()),
    }.items():
        assert not _execute_runs(document, "check_suite", event), label
    for job_name in ("reconcile", "sweep"):
        for event_name, event in (("check_run", check_run_event(UPSTREAM_NAME, STAGR_APP_ID)),
                                  ("check_suite", check_suite_event(STAGR_APP_ID))):
            condition = document["jobs"][job_name]["if"]
            context = build_github_context(event_name, event)
            assert not is_truthy(evaluate_expression(condition, context)), (job_name, event_name)


def test_only_declared_pull_request_triggers_and_wakeups_run_execute_never_comments_or_schedule() -> None:
    _, document = _render_security_after_review()
    assert not _execute_runs(document, "issue_comment", {"issue": {"number": 7}, "comment": {}})
    assert not _execute_runs(document, "schedule", {})
    assert not _execute_runs(document, "workflow_dispatch", {})


def test_relevant_wakeups_share_the_concurrency_group_of_the_pull_requests_other_events() -> None:
    _, document = _render_security_after_review()
    pull_request_group = _concurrency_group(document, "pull_request_target", pull_request_event(7))
    assert pull_request_group == "stagr-security-7"
    assert _concurrency_group(
        document, "check_run", check_run_event(UPSTREAM_NAME, STAGR_APP_ID, (7,))) == pull_request_group
    assert _concurrency_group(document, "check_suite", check_suite_event(STAGR_APP_ID, (7,))) == pull_request_group
    comment_event = {"issue": {"number": 7}, "comment": {}}
    assert _concurrency_group(document, "issue_comment", comment_event) == pull_request_group
    assert _concurrency_group(document, "schedule", {}) == "stagr-security-sweep"
    assert _concurrency_group(document, "check_run", check_run_event(UPSTREAM_NAME, STAGR_APP_ID, (8,))) == (
        "stagr-security-8")


def test_irrelevant_check_events_get_a_group_of_their_own_so_they_cannot_displace_a_wakeup() -> None:
    _, document = _render_security_after_review()
    pull_request_group = _concurrency_group(document, "pull_request_target", pull_request_event(7))
    irrelevant_events = (
        ("check_run", check_run_event("build (ubuntu)", OTHER_APP_ID, (7,))),
        ("check_run", check_run_event("stagr/stage/security", STAGR_APP_ID, (7,))),
        ("check_run", check_run_event(UPSTREAM_NAME, STAGR_APP_ID, ())),
        ("check_suite", check_suite_event(OTHER_APP_ID, (7,))),
    )
    groups = set()
    for event_name, event in irrelevant_events:
        for run_id in (1, 2):
            context = build_github_context(event_name, event, run_id=run_id)
            group = render_template(document["concurrency"]["group"], context)
            assert group != pull_request_group and group.endswith(f"-{run_id}"), group
            groups.add(group)
    assert groups == {"stagr-security-1", "stagr-security-2"}


def test_concurrency_never_cancels_and_a_stage_without_dependencies_keeps_its_group_expression() -> None:
    _, document = _render_security_after_review()
    assert document["concurrency"]["cancel-in-progress"] is False
    _, plain = render_codex_workflow(StageKind.SECURITY)
    assert plain["concurrency"]["group"] == (
        "stagr-security-${{ github.event_name == 'schedule' && 'sweep'"
        " || github.event.pull_request.number || github.event.issue.number }}")


def test_eligibility_step_comes_second_and_holds_only_the_app_token_and_event_data() -> None:
    _, document = _render_security_after_review()
    names = list(_steps(document))
    assert names == ["Acquire Stagr App installation token", "Check eligibility",
                     "Invoke backend (idempotent)", "Publish result signal"]
    step = _steps(document)["Check eligibility"]
    assert step["id"] == "eligibility" and step["run"] == 'python3 -c "$STAGR_RUNTIME_SCRIPT"'
    assert step["env"] == {
        "GH_TOKEN": "${{ steps.app-token.outputs.token }}",
        "STAGR_MODE": "eligibility",
        "STAGR_PULL_NUMBER": ("${{ github.event.pull_request.number"
                              " || github.event.check_run.pull_requests[0].number"
                              " || github.event.check_suite.pull_requests[0].number }}"),
        "STAGR_EVENT_HEAD_SHA": ("${{ github.event.pull_request.head.sha"
                                 " || github.event.check_run.head_sha"
                                 " || github.event.check_suite.head_sha }}"),
        "STAGR_EVENT_NAME": "${{ github.event_name }}",
    }
    assert "if" not in step


def test_invoke_step_runs_only_after_a_proceed_and_reads_the_wakeup_pull_request() -> None:
    _, document = _render_security_after_review()
    invoke = _steps(document)["Invoke backend (idempotent)"]
    assert invoke["if"] == PROCEED_CONDITION
    assert invoke["env"]["STAGR_PULL_NUMBER"] == _steps(document)["Check eligibility"]["env"]["STAGR_PULL_NUMBER"]
    assert invoke["env"]["STAGR_EVENT_HEAD_SHA"] == _steps(document)["Check eligibility"]["env"]["STAGR_EVENT_HEAD_SHA"]
    assert "GH_TOKEN" not in invoke["env"] and "app-token" not in json.dumps(invoke)


def test_publish_step_still_runs_after_a_skipped_invocation_and_learns_the_event_name() -> None:
    _, document = _render_security_after_review()
    publish = _steps(document)["Publish result signal"]
    assert publish["if"] == "${{ !cancelled() }}"
    assert publish["env"]["STAGR_EVENT_NAME"] == "${{ github.event_name }}"
    assert publish["env"]["STAGR_PULL_NUMBER"] == _steps(document)["Check eligibility"]["env"]["STAGR_PULL_NUMBER"]


def test_placeholder_backend_steps_are_gated_on_eligibility_as_well() -> None:
    document = parse_workflow(render_workflow_text(build_execution_plan(), build_stage()))
    steps = _steps(document)
    assert steps["Check idempotency (stub)"]["if"] == PROCEED_CONDITION
    assert steps["Invoke backend (stub)"]["if"] == PROCEED_CONDITION
    assert steps["Check eligibility"]["env"]["STAGR_PULL_NUMBER"] == (
        "${{ github.event.pull_request.number }}"), "no wake-up data without dependencies"


def test_permissions_and_credentials_are_unchanged_by_the_wakeup_path() -> None:
    text, document = _render_security_after_review()
    assert document["jobs"]["execute"]["permissions"] == {"pull-requests": "read", "contents": "read"}
    for job_name in ("reconcile", "sweep"):
        job = document["jobs"][job_name]
        assert job["permissions"] == {} and "TRUSTED_COMMENTER" not in json.dumps(job)
        assert "invoke" not in json.dumps(job) and "eligibility" not in json.dumps(job)
    assert text.count("REMEDIATION_TOKEN") == 1, "only the invoke step holds the backend secret"
    assert "permissions" not in document, "no workflow-wide permissions widen the jobs"


def test_reconcile_and_sweep_jobs_are_identical_with_and_without_dependencies() -> None:
    _, with_dependencies = _render_security_after_review()
    _, without_dependencies = render_codex_workflow(StageKind.SECURITY)
    for job_name in ("reconcile", "sweep"):
        assert with_dependencies["jobs"][job_name] == without_dependencies["jobs"][job_name]


def test_no_run_script_interpolates_an_expression_and_the_event_data_travels_through_env() -> None:
    _, document = _render_security_after_review()
    for job in document["jobs"].values():
        for step in job["steps"]:
            assert "${{" not in step.get("run", ""), step["name"]


def test_route_and_dependency_data_reach_the_runtime_only_through_the_configuration_document() -> None:
    fast_path = FastPathPolicy(match=PathMatchSpec(paths=("docs/**",)),
                               stages=RouteStageMap(fast=("review",), normal=("review", "security")))
    text, document = _render_security_after_review(fast_path)
    configuration = json.loads(document["env"]["STAGR_STAGE_CONFIG"])
    assert configuration["dependencies"] == [{"stageId": "review", "checkRunName": UPSTREAM_NAME}]
    assert configuration["routing"] == {
        "checkRunName": "stagr/route-classification", "fastStageIds": ["review"],
        "normalStageIds": ["review", "security"]}
    script = document["env"]["STAGR_RUNTIME_SCRIPT"]
    assert UPSTREAM_NAME not in script and "stagr/route-classification" not in script
    assert text.count(UPSTREAM_NAME) == text.count(json.dumps(UPSTREAM_NAME)) + text.count(
        f"'{UPSTREAM_NAME}'"), "only the configuration document and the if/concurrency guards name it"
    runtime.StageRuntimeConfig.from_json_text(document["env"]["STAGR_STAGE_CONFIG"])


def test_embedded_runtime_fits_in_a_single_environment_string() -> None:
    _, document = _render_security_after_review()
    assert len(document["env"]["STAGR_RUNTIME_SCRIPT"].encode("utf-8")) < LINUX_MAX_ENVIRONMENT_STRING_BYTES // 2


def test_renderer_refuses_a_dependency_it_cannot_evaluate() -> None:
    plan, stage = build_codex_plan(StageKind.SECURITY)
    stage = dataclasses.replace(stage, dependencies=("missing-stage",))
    try:
        render_workflow_text(plan, stage, build_render_context(stage))
    except ValueError as error:
        assert "missing-stage" in str(error)
    else:
        raise AssertionError("rendering must fail closed for an unknown dependency")


def test_wakeup_guard_names_every_upstream_stage_and_only_the_upstream_stages() -> None:
    plan, stage = build_codex_plan(StageKind.SECURITY)
    stage = dataclasses.replace(stage, dependencies=("review", "lint"))
    others = tuple(dataclasses.replace(stage, id=name, dependencies=()) for name in ("review", "lint", "docs"))
    context = dataclasses.replace(build_render_context(stage), stages=(*others, stage))
    document = parse_workflow(render_workflow_text(plan, stage, context))
    for name, expected in (("review", True), ("lint", True), ("docs", False), ("security", False)):
        event = check_run_event(f"stagr/stage/{name}", STAGR_APP_ID)
        assert _execute_runs(document, "check_run", event) is expected, name
