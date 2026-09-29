"""Tests for GitHubPlatformRenderer returned artifacts, StageResultSpec and Protocol conformance (issue #194).

Covers: StageResultSpec fields (signal_kind=CHECK_RUN, provenance.publisher_identity),
the artifacts every render method returns (path and content), that the renderer writes no
files, and Protocol conformance.
"""
from __future__ import annotations

import os
import tempfile

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    TEST_PUBLISHER_APP_ID,
    build_execution_plan,
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import StageResultSignalKind, StageTrigger
from stagr.core.models import (
    RenderedArtifact,
    StageRender,
    StageResultProvenance,
    StageResultSpec,
)


def _render_stage(stage_id: str = "review"):
    stage = build_stage(stage_id=stage_id)
    plan = build_execution_plan(stage_id=stage_id)
    return build_renderer().render_stage(plan, stage, build_render_context(stage))


def _build_result_spec(stage_id: str) -> StageResultSpec:
    return StageResultSpec(
        stage_id=stage_id,
        signal_kind=StageResultSignalKind.CHECK_RUN,
        signal_selector=f"stagr/stage/{stage_id}",
        provenance=StageResultProvenance(publisher_identity=TEST_PUBLISHER_APP_ID),
    )


# ------------------------------------------------------------------
# Stage render (StageResultSpec + artifact)
# ------------------------------------------------------------------

def test_render_stage_returns_stage_render() -> None:
    """render_stage returns a StageRender holding a StageResultSpec and a RenderedArtifact."""
    stage_render = _render_stage()
    assert isinstance(stage_render, StageRender), (
        f"render_stage must return StageRender; got {type(stage_render)!r}"
    )
    assert isinstance(stage_render.result_spec, StageResultSpec)
    assert isinstance(stage_render.artifact, RenderedArtifact)
    assert stage_render.artifact.content.strip(), "stage artifact must have content"


def test_stage_result_spec_signal_kind_is_check_run() -> None:
    """StageResultSpec.signal_kind equals StageResultSignalKind.CHECK_RUN."""
    result = _render_stage().result_spec
    assert result.signal_kind is StageResultSignalKind.CHECK_RUN, (
        f"signal_kind must be CHECK_RUN; got {result.signal_kind!r}"
    )


def test_stage_result_spec_provenance_publisher_identity_equals_app_id() -> None:
    """StageResultSpec.provenance.publisher_identity equals the configured App ID."""
    result = _render_stage().result_spec
    assert result.provenance.publisher_identity == TEST_PUBLISHER_APP_ID, (
        f"provenance.publisher_identity must be '{TEST_PUBLISHER_APP_ID}'; "
        f"got '{result.provenance.publisher_identity}'"
    )


def test_stage_result_spec_signal_selector_contains_stage_id() -> None:
    """StageResultSpec.signal_selector encodes the stage id in the Check Run name."""
    result = _render_stage(stage_id="security").result_spec
    assert "security" in result.signal_selector, (
        f"signal_selector '{result.signal_selector}' must contain stage id 'security'"
    )


def test_stage_result_spec_stage_id_matches_stage() -> None:
    """StageResultSpec.stage_id matches the rendered stage's id."""
    result = _render_stage(stage_id="review").result_spec
    assert result.stage_id == "review", f"result.stage_id must be 'review'; got '{result.stage_id}'"


# ------------------------------------------------------------------
# Phase 2 artifacts
# ------------------------------------------------------------------

def test_render_routing_returns_routing_artifact() -> None:
    """render_routing returns the routing workflow at .github/workflows/routing.yml."""
    stage = build_stage()
    routing_artifact = build_renderer().render_routing(build_render_context(stage))
    assert isinstance(routing_artifact, RenderedArtifact), f"got {type(routing_artifact)!r}"
    assert routing_artifact.path == ".github/workflows/routing.yml", routing_artifact.path
    assert routing_artifact.content.strip(), "routing artifact must have content"


def test_render_governance_returns_governance_artifact() -> None:
    """render_governance returns a non-empty artifact (path is asserted in the publisher tests)."""
    stage = build_stage()
    governance_artifact = build_renderer().render_governance(
        (_build_result_spec(stage.id),), build_render_context(stage)
    )
    assert isinstance(governance_artifact, RenderedArtifact), f"got {type(governance_artifact)!r}"
    assert governance_artifact.content.strip(), "governance artifact must have content"


def test_renderer_methods_write_no_files() -> None:
    """All three render methods leave the working directory empty; artifacts are only returned."""
    stage = build_stage()
    context = build_render_context(stage)
    renderer = build_renderer()
    original_directory = os.getcwd()
    with tempfile.TemporaryDirectory() as empty_directory:
        os.chdir(empty_directory)
        try:
            stage_render = renderer.render_stage(build_execution_plan(), stage, context)
            routing_artifact = renderer.render_routing(context)
            governance_artifact = renderer.render_governance((stage_render.result_spec,), context)
            written_entries = os.listdir(empty_directory)
        finally:
            os.chdir(original_directory)
    assert stage_render.artifact.content and routing_artifact.content and governance_artifact.content, (
        "positive control: every method must have returned content"
    )
    assert written_entries == [], f"renderer wrote to the working directory: {written_entries}"


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------

def test_github_platform_renderer_protocol_conformance() -> None:
    """GitHubPlatformRenderer satisfies the PlatformRenderer Protocol (isinstance check)."""
    from stagr.core.platform_renderer import PlatformRenderer
    from stagr.platforms.github.renderer import GitHubPlatformRenderer

    renderer = GitHubPlatformRenderer(
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert isinstance(renderer, PlatformRenderer), (
        "GitHubPlatformRenderer must satisfy PlatformRenderer Protocol "
        "(isinstance check must pass)"
    )


# ------------------------------------------------------------------
# Multiple trigger combinations
# ------------------------------------------------------------------

def test_pr_opened_and_pr_updated_combine_into_single_pull_request_target_block() -> None:
    """PR_OPENED + PR_UPDATED produce one pull_request_target block with all events."""
    stage = build_stage(triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED))
    plan = build_execution_plan()
    yaml_content = build_renderer().render_stage(plan, stage, build_render_context(stage)).artifact.content

    # Should appear exactly once, not twice.
    assert yaml_content.count("pull_request_target:") == 1, (
        "PR_OPENED + PR_UPDATED must produce exactly one pull_request_target: block"
    )
    assert "synchronize" in yaml_content
    assert "opened" in yaml_content


def test_manual_trigger_produces_workflow_dispatch_only() -> None:
    """MANUAL trigger produces workflow_dispatch without pull_request_target."""
    stage = build_stage(triggers=(StageTrigger.MANUAL,))
    plan = build_execution_plan()
    yaml_content = build_renderer().render_stage(plan, stage, build_render_context(stage)).artifact.content

    assert "workflow_dispatch" in yaml_content
    assert "pull_request_target" not in yaml_content
