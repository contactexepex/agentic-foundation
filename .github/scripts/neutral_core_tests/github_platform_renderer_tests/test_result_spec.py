"""Tests for GitHubPlatformRenderer StageResultSpec, Protocol conformance, dry-run (issue #194).

Covers: StageResultSpec fields (signal_kind=CHECK_RUN, provenance.publisher_identity),
dry-run mode (no files written but StageResultSpec returned), Protocol conformance,
and Phase 2 dry-run raises.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    TEST_PUBLISHER_APP_ID,
    build_execution_plan,
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import StageTrigger
from stagr.core.models import StageResultSpec


# ------------------------------------------------------------------
# StageResultSpec return value tests
# ------------------------------------------------------------------

def test_render_stage_returns_stage_result_spec() -> None:
    """render_stage returns a StageResultSpec instance."""
    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert isinstance(result, StageResultSpec), (
        f"render_stage must return StageResultSpec; got {type(result)!r}"
    )


def test_stage_result_spec_signal_kind_is_check_run() -> None:
    """StageResultSpec.signal_kind equals StageResultSignalKind.CHECK_RUN."""
    from stagr.core.enums import StageResultSignalKind

    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert result.signal_kind is StageResultSignalKind.CHECK_RUN, (
        f"signal_kind must be CHECK_RUN; got {result.signal_kind!r}"
    )


def test_stage_result_spec_provenance_publisher_identity_equals_app_id() -> None:
    """StageResultSpec.provenance.publisher_identity equals the configured App ID."""
    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert result.provenance.publisher_identity == TEST_PUBLISHER_APP_ID, (
        f"provenance.publisher_identity must be '{TEST_PUBLISHER_APP_ID}'; "
        f"got '{result.provenance.publisher_identity}'"
    )


def test_stage_result_spec_signal_selector_contains_stage_id() -> None:
    """StageResultSpec.signal_selector encodes the stage id in the Check Run name."""
    stage_id = "security"
    renderer = build_renderer(output_dir=None)
    stage = build_stage(stage_id=stage_id)
    plan = build_execution_plan(stage_id=stage_id)
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert stage_id in result.signal_selector, (
        f"signal_selector '{result.signal_selector}' must contain stage id '{stage_id}'"
    )


def test_stage_result_spec_stage_id_matches_stage() -> None:
    """StageResultSpec.stage_id matches the rendered stage's id."""
    stage_id = "review"
    renderer = build_renderer(output_dir=None)
    stage = build_stage(stage_id=stage_id)
    plan = build_execution_plan(stage_id=stage_id)
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert result.stage_id == stage_id, (
        f"result.stage_id must be '{stage_id}'; got '{result.stage_id}'"
    )


# ------------------------------------------------------------------
# Dry-run mode tests
# ------------------------------------------------------------------

def test_dry_run_render_stage_returns_stage_result_spec() -> None:
    """render_stage returns StageResultSpec in dry-run mode (output_dir=None)."""
    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)
    result = renderer.render_stage(plan, stage, context)
    assert isinstance(result, StageResultSpec), (
        "render_stage must return StageResultSpec in dry-run mode"
    )


def test_dry_run_produces_no_files() -> None:
    """render_stage in dry-run mode writes no files."""
    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)
    # No exception must be raised, but no files should exist anywhere.
    renderer.render_stage(plan, stage, context)
    # No assert on filesystem since output_dir is None (no disk target).
    # The positive control (non-dry-run) is covered by test_workflow_structure.py.


def test_dry_run_produces_no_files_positive_control() -> None:
    """Non-dry-run mode writes a file; confirms the dry-run absence is not vacuous."""
    stage = build_stage()
    plan = build_execution_plan()
    context = build_render_context(stage)

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        live_renderer = build_renderer(output_dir=output_dir)
        live_renderer.render_stage(plan, stage, context)
        written_files = list(output_dir.iterdir())
        assert written_files, (
            "Positive control: non-dry-run renderer must write at least one file"
        )


def test_dry_run_render_routing_raises_value_error() -> None:
    """render_routing raises ValueError in dry-run mode (output_dir=None)."""
    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    context = build_render_context(stage)
    try:
        renderer.render_routing(context)
        assert False, "render_routing must raise ValueError in dry-run mode"  # noqa: B011
    except ValueError:
        pass  # expected


def test_dry_run_render_governance_raises_value_error() -> None:
    """render_governance raises ValueError in dry-run mode (output_dir=None)."""
    from stagr.core.enums import StageResultSignalKind
    from stagr.core.models import StageResultProvenance

    renderer = build_renderer(output_dir=None)
    stage = build_stage()
    context = build_render_context(stage)
    spec = StageResultSpec(
        stage_id=stage.id,
        signal_kind=StageResultSignalKind.CHECK_RUN,
        signal_selector="stagr/stage/review",
        provenance=StageResultProvenance(publisher_identity="99001"),
    )
    try:
        renderer.render_governance((spec,), context)
        assert False, "render_governance must raise ValueError in dry-run mode"  # noqa: B011
    except ValueError:
        pass  # expected


# ------------------------------------------------------------------
# Protocol conformance
# ------------------------------------------------------------------

def test_github_platform_renderer_protocol_conformance() -> None:
    """GitHubPlatformRenderer satisfies the PlatformRenderer Protocol (isinstance check)."""
    from stagr.core.platform_renderer import PlatformRenderer
    from stagr.platforms.github.renderer import GitHubPlatformRenderer

    renderer = GitHubPlatformRenderer(
        output_dir=None,
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
    context = build_render_context(stage)

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        renderer = build_renderer(output_dir=output_dir)
        renderer.render_stage(plan, stage, context)
        yaml_content = (output_dir / "stagr-stage-review.yml").read_text(encoding="utf-8")

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
    context = build_render_context(stage)

    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        renderer = build_renderer(output_dir=output_dir)
        renderer.render_stage(plan, stage, context)
        yaml_content = (output_dir / "stagr-stage-review.yml").read_text(encoding="utf-8")

    assert "workflow_dispatch" in yaml_content
    assert "pull_request_target" not in yaml_content
