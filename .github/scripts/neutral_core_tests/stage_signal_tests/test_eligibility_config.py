"""Render-time handling of dependencies and routing (issue #207): data in the JSON, refusals early."""
from __future__ import annotations

import dataclasses
import json

from neutral_core_tests.github_platform_renderer_tests.helpers import build_render_context
from neutral_core_tests.stage_signal_tests.eligibility_fixtures import (
    build_dependency_documents,
    build_routing_document,
    downstream_config_document,
)
from neutral_core_tests.stage_signal_tests.render_helpers import build_codex_plan
from stagr.core.enums import StageKind
from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy
from stagr.platforms.github.runtime import stage_signal_runtime as runtime
from stagr.platforms.github.stage_signal_config import build_stage_signal_config


def _security_plan_and_stage(dependencies=("review",)):
    plan, stage = build_codex_plan(StageKind.SECURITY)
    return plan, dataclasses.replace(stage, dependencies=tuple(dependencies))


def _context(stage, other_stage_ids=("review",), fast_path=None):
    base = build_render_context(stage)
    other_stages = tuple(
        dataclasses.replace(stage, id=other_id, dependencies=()) for other_id in other_stage_ids)
    return dataclasses.replace(
        base, stages=(*other_stages, stage), routing_policy=RoutingPolicy(fast_path=fast_path))


def _build(stage, plan, context, app_id="99001"):
    return build_stage_signal_config(plan, stage, context, app_id, f"stagr/stage/{stage.id}")


def _expect_rejection(stage, plan, context, fragment: str, app_id="99001") -> None:
    try:
        _build(stage, plan, context, app_id)
    except ValueError as error:
        assert stage.id in str(error) and fragment in str(error), str(error)
        return
    raise AssertionError(f"expected ValueError containing {fragment!r}")


def test_dependencies_render_with_the_check_run_name_of_each_upstream_stage() -> None:
    plan, stage = _security_plan_and_stage(("review", "lint", "review"))
    config = _build(stage, plan, _context(stage, ("review", "lint")))
    assert config.document["dependencies"] == build_dependency_documents("review", "lint")
    assert config.has_dependencies
    assert config.upstream_check_run_names == ("stagr/stage/review", "stagr/stage/lint")


def test_a_stage_without_dependencies_renders_empty_eligibility_data() -> None:
    plan, stage = _security_plan_and_stage(())
    config = _build(stage, plan, _context(stage))
    assert config.document["dependencies"] == [] and config.document["routing"] is None
    assert not config.has_dependencies and config.upstream_check_run_names == ()


def test_fast_path_renders_the_applicable_stage_ids_of_both_routes() -> None:
    plan, stage = _security_plan_and_stage(())
    fast_path = FastPathPolicy(match=PathMatchSpec(paths=("docs/**",)),
                               stages=RouteStageMap(fast=("review", "review"), normal=("security", "review")))
    config = _build(stage, plan, _context(stage, fast_path=fast_path))
    assert config.document["routing"] == build_routing_document(
        fast=("review",), normal=("review", "security"))


def test_dependency_on_a_stage_that_is_not_active_is_refused() -> None:
    plan, stage = _security_plan_and_stage(("ghost",))
    _expect_rejection(stage, plan, _context(stage), "'ghost' is not another active stage")


def test_dependency_on_itself_is_refused() -> None:
    plan, stage = _security_plan_and_stage(("security",))
    _expect_rejection(stage, plan, _context(stage), "'security' is not another active stage")


def test_dependency_ids_that_could_escape_the_wakeup_expression_are_refused() -> None:
    for hostile in ("x' || true || 'y", "a b", "review/../x", "UPPER", "", "x'", "a\nb", "${{ x }}"):
        plan, stage = _security_plan_and_stage((hostile,))
        _expect_rejection(stage, plan, _context(stage, (hostile,)), "is not a valid stage id")


def test_publisher_app_id_must_be_numeric_when_the_wakeup_expression_embeds_it() -> None:
    plan, stage = _security_plan_and_stage()
    for hostile in ("99001 || true", "abc", "", "1" * 21, "-1", "9.9"):
        _expect_rejection(stage, plan, _context(stage), "publisher App id must be numeric", app_id=hostile)


def test_a_non_numeric_app_id_is_not_this_checks_business_without_dependencies() -> None:
    plan, stage = _security_plan_and_stage(())
    assert _build(stage, plan, _context(stage), app_id="not-numeric").document["publisherAppId"]


def test_document_never_contains_the_expression_opener_for_any_dependency_or_route() -> None:
    plan, stage = _security_plan_and_stage()
    fast_path = FastPathPolicy(match=PathMatchSpec(paths=("a",)),
                               stages=RouteStageMap(fast=("${{ x }}",), normal=("y",)))
    try:
        _build(stage, plan, _context(stage, fast_path=fast_path))
    except ValueError as error:
        assert "expression opener" in str(error)
    else:
        raise AssertionError("a stage id with the expression opener must be refused")


def test_runtime_parses_dependencies_and_routing_into_rules() -> None:
    document = downstream_config_document(routing=build_routing_document())
    config = runtime.StageRuntimeConfig.from_json_text(json.dumps(document))
    assert config.dependency_rules == (runtime.DependencyRule("review", "stagr/stage/review"),)
    assert config.route_rule.is_applicable("review", "FAST")
    assert not config.route_rule.is_applicable("security", "FAST")
    assert config.route_rule.is_applicable("security", "NORMAL")


def test_runtime_rejects_a_configuration_without_the_eligibility_keys() -> None:
    for missing_key in ("dependencies", "routing"):
        document = downstream_config_document()
        del document[missing_key]
        _expect_runtime_rejection(document)


def test_runtime_rejects_dependency_and_route_rules_it_cannot_evaluate() -> None:
    bad_documents = (
        downstream_config_document(dependencies=[{"stageId": "security", "checkRunName": "x"}]),
        downstream_config_document(dependencies=[{"stageId": "", "checkRunName": "x"}]),
        downstream_config_document(dependencies=[{"stageId": "a", "checkRunName": ""}]),
        downstream_config_document(dependencies=[{"stageId": "a"}]),
        downstream_config_document(dependencies=[{"stageId": 5, "checkRunName": "x"}]),
        downstream_config_document(routing={"checkRunName": "", "fastStageIds": [], "normalStageIds": []}),
        downstream_config_document(routing={"checkRunName": "x", "fastStageIds": [1], "normalStageIds": []}),
        downstream_config_document(routing={"checkRunName": "x"}),
    )
    for document in bad_documents:
        _expect_runtime_rejection(document)


def _expect_runtime_rejection(document) -> None:
    try:
        runtime.StageRuntimeConfig.from_json_text(json.dumps(document))
    except runtime.RuntimeConfigError:
        return
    raise AssertionError(f"expected the runtime to reject {document!r}")
