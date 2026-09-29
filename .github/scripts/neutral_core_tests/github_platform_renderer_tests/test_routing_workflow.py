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


def test_fast_path_configured_workflow_embeds_patterns_as_base64_constant() -> None:
    """When fast_path is configured the routing workflow embeds patterns as a base64 constant."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*", "*.md")),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    # Patterns must be embedded as a base64 env var, not raw JSON.
    assert "FAST_PATH_PATTERNS_B64" in yaml, (
        "fast_path configured workflow must embed patterns as FAST_PATH_PATTERNS_B64"
    )
    # The inline script must decode from base64.
    assert "base64" in yaml, (
        "fast_path configured workflow classify step must reference base64 for decoding"
    )
    # Changed-files retrieval and classification steps must be present.
    assert "Get changed file paths" in yaml, (
        "fast_path configured workflow must include a changed-files retrieval step"
    )
    assert "Classify route" in yaml, (
        "fast_path configured workflow must include a route classification step"
    )


def test_routing_workflow_changed_files_step_aggregates_pages_safely() -> None:
    """Changed-files step uses --paginate --slurp piped to jq, not --paginate --jq."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "--paginate --slurp" in yaml_content, (
        "Changed-files step must use '--paginate --slurp' to aggregate all pages into "
        "one JSON value before extracting filenames; '--paginate --jq' runs jq per page "
        "and concatenates arrays, breaking json.loads"
    )
    assert "| jq" in yaml_content, (
        "Changed-files step must pipe slurped output to jq for filename extraction"
    )
    assert "--paginate --jq" not in yaml_content, (
        "Changed-files step must not use '--paginate --jq' which processes each page "
        "independently and produces concatenated JSON that is invalid for json.loads"
    )


def test_routing_workflow_classify_step_handles_apostrophe_in_glob_pattern() -> None:
    """Routing workflow generates safe YAML when a glob pattern contains an apostrophe."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/o'hare/**",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "FAST_PATH_PATTERNS_B64" in yaml_content, (
        "Classify step must embed patterns as FAST_PATH_PATTERNS_B64 (base64-encoded) "
        "to avoid YAML single-quoted-scalar breakage for apostrophe-containing globs"
    )
    assert "base64.b64decode" in yaml_content, (
        "Classify step Python script must decode patterns from base64"
    )
    assert "o'hare" not in yaml_content, (
        "The raw apostrophe-containing path must not appear unescaped in the YAML scalar; "
        "base64 encoding must transport the patterns safely"
    )


def test_edited_event_type_present_in_routing_workflow() -> None:
    """Routing workflow trigger includes 'edited' event type for base branch changes."""
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "edited" in yaml_content, (
        "Routing workflow must include 'edited' in pull_request_target event types "
        "so re-routing fires when the PR base branch changes"
    )
    assert "changes.base" in yaml_content, (
        "Routing workflow must guard the 'edited' trigger with a changes.base != null check "
        "to avoid re-routing on title/body-only edits"
    )


def test_rename_previous_filename_included_in_files_json() -> None:
    """Changed-files step extracts previous_filename alongside filename for renames."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "previous_filename" in yaml_content, (
        "Changed-files step must extract previous_filename so renames from outside "
        "the fast-path patterns are correctly classified as NORMAL"
    )


def test_truncated_file_list_forces_normal_route() -> None:
    """Classify step routes NORMAL when the fetched file list is shorter than changed_files count."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "CHANGED_FILES_COUNT" in yaml_content, (
        "Classify step must receive CHANGED_FILES_COUNT from the changed-files step "
        "to detect GitHub's 3000-file API cap and force NORMAL when truncated"
    )
    assert "changed_files_count" in yaml_content, (
        "Classify step Python script must compare fetched file count against "
        "changed_files_count to detect truncation"
    )


def test_metadata_edit_uses_distinct_concurrency_key() -> None:
    """Metadata-only edited events use a -noop concurrency key to avoid cancelling real classifications."""
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "-noop" in yaml_content, (
        "Concurrency group must include a '-noop' suffix for metadata-only edited events "
        "so they do not cancel in-progress synchronize/base-edit classifications"
    )
    assert "changes.base == ''" in yaml_content, (
        "Concurrency key expression and job if-condition must use == '' (empty string) "
        "to detect absent changes.base, not == null which is always false in GitHub Actions"
    )


def test_truncation_check_uses_raw_api_record_count() -> None:
    """Truncation check compares raw API record count, not expanded path count."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "api_record_count" in yaml_content, (
        "Changed-files step must emit api_record_count (raw API records before rename expansion) "
        "and classify step must compare it against changed_files_count to detect truncation; "
        "comparing len(files) which includes previous_filename entries can mask truncation"
    )
    assert "API_RECORD_COUNT" in yaml_content, (
        "Classify step must receive API_RECORD_COUNT from the changed-files step output"
    )


# ------------------------------------------------------------------
# Check Run upsert — prevents duplicate RouteClassification runs
# ------------------------------------------------------------------

def test_publication_step_uses_upsert_not_blind_post() -> None:
    """Publication step PATCHes an existing run when found, POSTs only when none exists."""
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "--method PATCH" in yaml_content, (
        "Publication step must include a PATCH path to update an existing "
        "RouteClassification Check Run for the head SHA; blind POST creates "
        "duplicates when routing re-fires after a base-branch edit"
    )
    assert "--method POST" in yaml_content, (
        "Publication step must also include a POST fallback to create a new "
        "Check Run when none exists for the head SHA"
    )
    assert "jq --arg app_id" in yaml_content, (
        "Publication step must filter existing Check Runs by app_id using "
        "'jq --arg app_id' so only the Stagr App's own run is reconciled"
    )


def test_publication_step_embeds_stagr_app_id_for_reconciliation() -> None:
    """Publication step env includes STAGR_APP_ID to filter existing runs by publisher."""
    configured_app_id = "77812"
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=None,
        publisher_app_id=configured_app_id,
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "STAGR_APP_ID" in yaml_content, (
        "Publication step env must include STAGR_APP_ID so the reconciliation "
        "query can filter candidate Check Runs by the Stagr App's identity"
    )
    assert configured_app_id in yaml_content, (
        f"STAGR_APP_ID must be set to the configured publisher_app_id literal "
        f"'{configured_app_id}'"
    )


def test_fast_path_publication_step_also_uses_upsert() -> None:
    """Fast-path-configured publication step also uses upsert, not blind POST."""
    fast_path_policy = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=(), normal=("review",)),
    )
    yaml_content = generate_routing_workflow_yaml(
        fast_path_policy=fast_path_policy,
        publisher_app_id="99001",
        publisher_private_key_secret="STAGR_APP_PRIVATE_KEY",
    )
    assert "--method PATCH" in yaml_content, (
        "Fast-path publication step must include PATCH to reconcile an existing "
        "RouteClassification Check Run for the head SHA"
    )
    assert "STAGR_APP_ID" in yaml_content, (
        "Fast-path publication step env must include STAGR_APP_ID for reconciliation filtering"
    )
