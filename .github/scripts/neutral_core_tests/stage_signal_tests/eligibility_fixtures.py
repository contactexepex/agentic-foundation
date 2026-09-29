"""Builders for the eligibility tests (issue #207): a downstream stage, its upstream signals, routes.

The downstream stage is ``security`` and it depends on ``review``. Upstream signals and route
classifications are built in the shape the Checks API returns them, including the app that wrote
them, so tests can forge them from another app.
"""
from __future__ import annotations

import json
from typing import Any

from neutral_core_tests.stage_signal_tests.fake_github import PUBLISHER_APP_ID, FakeGitHubApi
from neutral_core_tests.stage_signal_tests.fixtures import (
    HEAD_SHA,
    build_config_document,
    build_world,
    no_open_threads_gate,
    security_evidence_rule,
)
from stagr.platforms.github.runtime import stage_signal_runtime as runtime

UPSTREAM_STAGE_ID = "review"
UPSTREAM_CHECK_RUN_NAME = "stagr/stage/review"
DOWNSTREAM_STAGE_ID = "security"
DOWNSTREAM_CHECK_RUN_NAME = "stagr/stage/security"
ROUTE_CHECK_RUN_NAME = "stagr/route-classification"
FOREIGN_APP_ID = "15368"
UPSTREAM_CHECK_RUN_ID = 300
ROUTE_CHECK_RUN_ID = 400


def build_dependency_documents(*stage_ids: str) -> list[dict[str, str]]:
    return [{"stageId": stage_id, "checkRunName": f"stagr/stage/{stage_id}"}
            for stage_id in (stage_ids or (UPSTREAM_STAGE_ID,))]


def build_routing_document(
    fast: tuple[str, ...] = (UPSTREAM_STAGE_ID,),
    normal: tuple[str, ...] = (UPSTREAM_STAGE_ID, DOWNSTREAM_STAGE_ID),
) -> dict[str, Any]:
    return {"checkRunName": ROUTE_CHECK_RUN_NAME, "fastStageIds": list(fast),
            "normalStageIds": list(normal)}


def downstream_config_document(**overrides: Any) -> dict[str, Any]:
    """The runtime configuration of ``security``, which depends on ``review``."""
    document = build_config_document(
        stageId=DOWNSTREAM_STAGE_ID,
        checkRunName=DOWNSTREAM_CHECK_RUN_NAME,
        evidence=[security_evidence_rule()],
        gate=no_open_threads_gate(),
        invocation={"kind": "pr_comment", "body": "@codex security review", "leaseMinutes": 30},
        dependencies=build_dependency_documents(),
    )
    document.update(overrides)
    return document


def build_downstream_config(**overrides: Any) -> runtime.StageRuntimeConfig:
    return runtime.StageRuntimeConfig.from_json_text(
        json.dumps(downstream_config_document(**overrides)))


def build_stage_signal_check_run(
    stage_id: str,
    state: str,
    conclusion: str,
    head_sha: str = HEAD_SHA,
    check_run_id: int = UPSTREAM_CHECK_RUN_ID,
    app_id: str = PUBLISHER_APP_ID,
    payload_overrides: dict[str, Any] | None = None,
    native_conclusion: str | None = None,
    listed_head_sha: str | None = None,
) -> dict[str, Any]:
    """A stage signal Check Run whose payload is bound to ``head_sha``.

    ``listed_head_sha`` is the commit the Checks API lists it under (default: the same head);
    ``native_conclusion`` overrides the native field to show the payload wins.
    """
    signal = runtime.StageSignal(state, conclusion)
    payload = json.loads(runtime.serialize_signal_payload(stage_id, head_sha, signal))
    payload.update(payload_overrides or {})
    check_run: dict[str, Any] = {
        "id": check_run_id,
        "app": {"id": int(app_id)},
        "name": f"stagr/stage/{stage_id}",
        "head_sha": listed_head_sha or head_sha,
        "status": signal.native_status,
        "output": {"title": "upstream", "summary": json.dumps(payload)},
    }
    conclusion_to_send = native_conclusion or signal.native_conclusion
    if conclusion_to_send is not None:
        check_run["conclusion"] = conclusion_to_send
    return check_run


def build_upstream_check_run(state: str, conclusion: str, **overrides: Any) -> dict[str, Any]:
    return build_stage_signal_check_run(UPSTREAM_STAGE_ID, state, conclusion, **overrides)


def build_route_check_run(
    route: str = "NORMAL",
    head_sha: str = HEAD_SHA,
    app_id: str = PUBLISHER_APP_ID,
    status: str = "completed",
    title: str | None = None,
    check_run_id: int = ROUTE_CHECK_RUN_ID,
) -> dict[str, Any]:
    """The Check Run the routing workflow publishes: the title carries the classification."""
    return {
        "id": check_run_id,
        "app": {"id": int(app_id)},
        "name": ROUTE_CHECK_RUN_NAME,
        "head_sha": head_sha,
        "status": status,
        "conclusion": "success" if status == "completed" else None,
        "output": {"title": title or f"RouteClassification={route}",
                   "summary": f"PR classified as {route} route."},
    }


def build_dependency_world(
    upstream_runs: list[dict[str, Any]] | None = None, **world_arguments: Any
) -> FakeGitHubApi:
    """A repository with one trusted open pull request and the given Check Runs."""
    fake = build_world(**world_arguments)
    fake.check_runs.extend(upstream_runs or [])
    return fake


def check_runs_named(fake: FakeGitHubApi, name: str) -> list[dict[str, Any]]:
    return [run for run in fake.check_runs if run["name"] == name]


def downstream_signal(fake: FakeGitHubApi) -> dict[str, Any] | None:
    """The parsed payload of the downstream stage's single Check Run, or ``None`` when absent."""
    runs = check_runs_named(fake, DOWNSTREAM_CHECK_RUN_NAME)
    assert len(runs) <= 1, runs
    return json.loads(runs[0]["output"]["summary"]) if runs else None
