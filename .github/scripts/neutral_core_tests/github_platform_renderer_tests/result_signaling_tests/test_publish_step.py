"""Tests for the Publish result step: ALWAYS_PASS, NO_OPEN_THREADS, and upsert pattern."""
from __future__ import annotations

from neutral_core_tests.github_platform_renderer_tests.result_signaling_tests._helpers import (
    build_always_pass_plan,
    build_no_open_threads_plan,
    render_stage_yaml,
)


def test_always_pass_result_step_emits_success_conclusion() -> None:
    """ALWAYS_PASS disposition: result step has Check Run conclusion=success."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "conclusion=success" in publish_block or 'conclusion": "success"' in publish_block, (
        "ALWAYS_PASS step must emit Check Run conclusion=success"
    )


def test_always_pass_result_payload_has_conclusion_pass() -> None:
    """ALWAYS_PASS disposition: JSON payload contains conclusion: 'pass'."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "conclusion" in publish_block, (
        "ALWAYS_PASS result step must set conclusion in payload"
    )
    assert "pass" in publish_block, (
        "ALWAYS_PASS result payload must carry conclusion='pass'"
    )


def test_result_payload_has_schema_version_one() -> None:
    """Result signaling step embeds schemaVersion=1 in the JSON payload."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "schemaVersion" in publish_block, (
        "Result payload must include schemaVersion field"
    )
    assert "1" in publish_block, "schemaVersion must be 1"


def test_result_payload_embeds_stage_id() -> None:
    """Result signaling step embeds the stage id in the JSON payload."""
    stage_id = "security-scan"
    yaml_content = render_stage_yaml(build_always_pass_plan(stage_id=stage_id))
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert stage_id in publish_block, (
        f"Result payload must include stageId='{stage_id}'"
    )


def test_result_payload_includes_head_sha_reference() -> None:
    """Result signaling step includes a HEAD_SHA reference in the payload."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "HEAD_SHA" in publish_block or "head.sha" in publish_block, (
        "Result payload must reference the head SHA"
    )


def test_result_step_patches_existing_check_run() -> None:
    """Result signaling step PATCHes an existing Check Run when one exists."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "PATCH" in publish_block, (
        "Result step must use PATCH to update an existing Check Run"
    )


def test_result_step_posts_new_check_run_when_absent() -> None:
    """Result signaling step POSTs a new Check Run when none exists."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "POST" in publish_block, (
        "Result step must use POST to create a new Check Run when none exists"
    )


def test_result_step_uses_filter_all_to_find_existing_check_run() -> None:
    """Result signaling step queries check-runs with filter=all."""
    yaml_content = render_stage_yaml(build_always_pass_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "filter=all" in publish_block, (
        "Result step must use filter=all to find existing Check Runs regardless of status"
    )


def test_no_open_threads_step_emits_action_required_for_blocked() -> None:
    """NO_OPEN_THREADS: step emits action_required when open threads exist."""
    yaml_content = render_stage_yaml(build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "action_required" in publish_block, (
        "NO_OPEN_THREADS step must contain action_required conclusion path for blocked"
    )


def test_no_open_threads_step_emits_blocked_in_payload() -> None:
    """NO_OPEN_THREADS: JSON payload has conclusion='blocked' when threads are open."""
    yaml_content = render_stage_yaml(build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "blocked" in publish_block, (
        "NO_OPEN_THREADS step must contain 'blocked' conclusion payload"
    )


def test_no_open_threads_step_emits_success_for_zero_threads() -> None:
    """NO_OPEN_THREADS: step emits success when no open threads."""
    yaml_content = render_stage_yaml(build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "success" in publish_block, (
        "NO_OPEN_THREADS step must contain success conclusion path for zero threads"
    )


def test_no_open_threads_step_queries_graphql_review_threads() -> None:
    """NO_OPEN_THREADS: step queries GitHub GraphQL API for unresolved review threads."""
    yaml_content = render_stage_yaml(build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "graphql" in publish_block, (
        "NO_OPEN_THREADS step must query GraphQL API for review threads"
    )
    assert "reviewThreads" in publish_block or "review_threads" in publish_block.lower(), (
        "NO_OPEN_THREADS step must query reviewThreads in GraphQL"
    )
    assert "isResolved" in publish_block, (
        "NO_OPEN_THREADS step must check isResolved field to count open threads"
    )


def test_no_open_threads_step_filters_by_findings_author() -> None:
    """NO_OPEN_THREADS: thread count is filtered by FindingScopeSpec.created_by."""
    yaml_content = render_stage_yaml(build_no_open_threads_plan())
    publish_index = yaml_content.find("Publish result")
    assert publish_index != -1, "Must have 'Publish result' step"
    publish_block = yaml_content[publish_index:]
    assert "codex-bot" in publish_block, (
        "NO_OPEN_THREADS step must embed FINDINGS_AUTHOR from FindingScopeSpec.created_by"
    )
    assert "author" in publish_block.lower(), (
        "NO_OPEN_THREADS step must filter review threads by author to enforce FindingScopeSpec"
    )
