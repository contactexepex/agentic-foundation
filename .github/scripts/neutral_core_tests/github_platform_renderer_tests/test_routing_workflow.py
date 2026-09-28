"""Tests for routing workflow generation (issue #195).

Covers: fast_path=null emits NORMAL immediately without path analysis;
classify_route_from_changed_files classifies all-match as FAST and any-mismatch as NORMAL;
generated workflow's first step references the configured private_key_secret name.
"""
from __future__ import annotations

from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap
from stagr.platforms.github.routing_workflow import (
    ROUTE_CLASSIFICATION_CHECK_RUN_NAME,
    classify_route_from_changed_files,
    generate_routing_workflow_yaml,
)


# ------------------------------------------------------------------
# fast_path=None: minimal NORMAL-only workflow
# ------------------------------------------------------------------

def test_fast_path_null_produces_normal_immediately() -> None:
    """When fast_path is None the routing workflow emits NORMAL with no path analysis steps."""
    routing_workflow_yaml = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    # No changed-files retrieval step must be present.
    assert "Get changed file paths" not in routing_workflow_yaml, (
        "fast_path=null workflow must not contain a changed-files retrieval step"
    )
    # No classification step must be present.
    assert "Classify route" not in routing_workflow_yaml, (
        "fast_path=null workflow must not contain a route classification step"
    )
    # The workflow must still publish the RouteClassification Check Run.
    assert ROUTE_CLASSIFICATION_CHECK_RUN_NAME in routing_workflow_yaml, (
        "fast_path=null workflow must publish the RouteClassification Check Run"
    )
    # The published classification must be NORMAL.
    assert "NORMAL" in routing_workflow_yaml, (
        "fast_path=null workflow must emit NORMAL classification"
    )


# ------------------------------------------------------------------
# classify_route_from_changed_files — behavioral tests
# ------------------------------------------------------------------

def test_all_paths_match_classifies_as_fast() -> None:
    """classify_route_from_changed_files returns FAST when all changed paths match a pattern."""
    changed_file_paths = [
        "docs/index.md",
        "docs/api/reference.md",
        "docs/guide/getting-started.md",
    ]
    fast_path_patterns = ["docs/*", "docs/**"]
    classification = classify_route_from_changed_files(
        changed_file_paths=changed_file_paths,
        fast_path_patterns=fast_path_patterns,
    )
    assert classification == "FAST", (
        f"All paths match 'docs/*' or 'docs/**'; expected FAST but got {classification!r}"
    )


def test_any_path_mismatch_classifies_as_normal() -> None:
    """classify_route_from_changed_files returns NORMAL when any changed path does not match."""
    changed_file_paths = [
        "docs/index.md",
        "stagr/core/models.py",  # does not match docs/* patterns
    ]
    fast_path_patterns = ["docs/*", "docs/**"]
    classification = classify_route_from_changed_files(
        changed_file_paths=changed_file_paths,
        fast_path_patterns=fast_path_patterns,
    )
    assert classification == "NORMAL", (
        f"'stagr/core/models.py' does not match docs/* patterns; "
        f"expected NORMAL but got {classification!r}"
    )


# ------------------------------------------------------------------
# Routing workflow structural tests
# ------------------------------------------------------------------

def test_routing_workflow_first_step_references_private_key_secret() -> None:
    """The first step of the routing workflow references the configured private_key_secret."""
    configured_secret_name = "STAGR_PUBLISHER_PRIVATE_KEY"
    routing_workflow_yaml = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id="99001",
        publisher_private_key_secret=configured_secret_name,
    )
    assert configured_secret_name in routing_workflow_yaml, (
        f"Routing workflow must reference the private_key_secret name "
        f"'{configured_secret_name}' in the token acquisition step"
    )
    # The secret must appear as a secrets expression, not as a literal value.
    expected_secret_expression = f"secrets.{configured_secret_name}"
    assert expected_secret_expression in routing_workflow_yaml, (
        f"Private key secret must be referenced as "
        f"'secrets.{configured_secret_name}' in the token acquisition step"
    )


def test_fast_path_configured_workflow_embeds_patterns_as_json_constant() -> None:
    """When fast_path is configured the routing workflow embeds patterns as a JSON literal."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*", "*.md")),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    routing_workflow_yaml = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    # Both patterns must appear as embedded JSON constants.
    assert '"docs/*"' in routing_workflow_yaml, (
        "fast_path configured workflow must embed 'docs/*' pattern as a JSON constant"
    )
    assert '"*.md"' in routing_workflow_yaml, (
        "fast_path configured workflow must embed '*.md' pattern as a JSON constant"
    )
    # Changed-files retrieval and classification steps must be present.
    assert "Get changed file paths" in routing_workflow_yaml, (
        "fast_path configured workflow must include a changed-files retrieval step"
    )
    assert "Classify route" in routing_workflow_yaml, (
        "fast_path configured workflow must include a route classification step"
    )
