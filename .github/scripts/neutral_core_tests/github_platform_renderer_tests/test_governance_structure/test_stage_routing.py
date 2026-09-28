"""Tests for governance workflow stage selector and routing logic (issue #196)."""
from __future__ import annotations

from stagr.core.enums import StageGate
from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap

from neutral_core_tests.github_platform_renderer_tests.test_governance_structure.helpers import (
    _render_governance_to_string,
)


def test_governance_workflow_contains_stage_signal_selector() -> None:
    """Governance workflow contains the signal_selector for each stage spec."""
    stage_id = "review"
    yaml_content = _render_governance_to_string(stage_id=stage_id)
    expected_selector = f"stagr/stage/{stage_id}"
    assert expected_selector in yaml_content, (
        f"Governance workflow must contain signal_selector '{expected_selector}' "
        f"for stage '{stage_id}'"
    )


def test_governance_workflow_contains_multiple_stage_selectors() -> None:
    """Governance workflow contains signal_selectors for all stages in result_specs."""
    yaml_content = _render_governance_to_string(
        stage_id="review",
        extra_stage_id="security",
    )
    assert "stagr/stage/review" in yaml_content, (
        "Governance workflow must contain selector for stage 'review'"
    )
    assert "stagr/stage/security" in yaml_content, (
        "Governance workflow must contain selector for stage 'security'"
    )


def test_governance_workflow_marks_blocking_stage_as_blocking() -> None:
    """Governance workflow passes 'blocking' argument for BLOCKING gate stages."""
    yaml_content = _render_governance_to_string(stage_id="review", gate=StageGate.BLOCKING)
    assert '"blocking"' in yaml_content, (
        "Governance workflow must pass 'blocking' as the gate argument for "
        "stages with StageGate.BLOCKING"
    )


def test_governance_workflow_marks_non_blocking_stage_as_non_blocking() -> None:
    """Governance workflow passes 'non_blocking' argument for NON_BLOCKING gate stages."""
    yaml_content = _render_governance_to_string(
        stage_id="review",
        gate=StageGate.BLOCKING,
        extra_stage_id="advisory",
        extra_gate=StageGate.NON_BLOCKING,
    )
    assert '"non_blocking"' in yaml_content, (
        "Governance workflow must pass 'non_blocking' as the gate argument for "
        "stages with StageGate.NON_BLOCKING"
    )


def test_governance_workflow_non_blocking_stage_missing_check_run_does_not_gate_merge() -> None:
    """A non-blocking (advisory) stage with no Check Run must not set overall_pass=false.

    When an advisory stage has not run, evaluate_stage_signal returns failure before
    reaching the non-blocking conclusion branch. The caller must never flip overall_pass
    for a non-blocking stage.
    """
    yaml_content = _render_governance_to_string(
        stage_id="review",
        gate=StageGate.BLOCKING,
        extra_stage_id="advisory",
        extra_gate=StageGate.NON_BLOCKING,
    )
    assert '"advisory"' in yaml_content, "Advisory stage must be referenced in governance YAML"
    # The non-blocking call line must not end with || overall_pass=false.
    for line in yaml_content.splitlines():
        if '"advisory"' in line and "evaluate_stage_signal" in line:
            assert "overall_pass=false" not in line, (
                f"Non-blocking stage 'advisory' must not set overall_pass=false on failure; "
                f"found: {line!r}"
            )


def test_governance_workflow_fast_path_only_evaluates_fast_route_stages() -> None:
    """When fast_path is configured, FAST-route stages are wrapped in a FAST conditional.

    A blocking stage that is only in fast_path.stages.fast must be skipped on NORMAL
    route PRs, so it must be wrapped in 'if [[ "${current_route}" == "FAST" ]]'.
    """
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=("docs-review",), normal=("review",)),
    )
    # docs-review is a FAST-only stage; review is NORMAL-only.
    yaml_content = _render_governance_to_string(
        stage_id="review",
        gate=StageGate.BLOCKING,
        extra_stage_id="docs-review",
        extra_gate=StageGate.BLOCKING,
        fast_path_policy=fast_path_policy,
    )
    # Route-reading block must be present when fast_path is configured.
    assert "stagr/route-classification" in yaml_content, (
        "Governance must read the RouteClassification Check Run when fast_path is configured"
    )
    assert "current_route" in yaml_content, (
        "Governance must determine the current route before evaluating stage signals"
    )
    # The FAST-only stage must be wrapped in a FAST conditional.
    assert '"FAST"' in yaml_content, (
        "Governance must wrap FAST-only stages in an if-FAST conditional"
    )
    # The NORMAL-only stage must be wrapped in a NORMAL conditional.
    assert '"NORMAL"' in yaml_content, (
        "Governance must wrap NORMAL-only stages in an if-NORMAL conditional"
    )
