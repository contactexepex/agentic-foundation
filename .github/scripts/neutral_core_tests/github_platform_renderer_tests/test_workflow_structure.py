"""Tests for GitHubPlatformRenderer workflow YAML structure (issue #194).

Covers: trigger mapping, concurrency block, token isolation, App token step,
backend invocation step, and security invariant for privileged stages.
"""
from __future__ import annotations

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    TEST_PUBLISHER_APP_ID,
    TEST_PUBLISHER_PRIVATE_KEY_SECRET,
    build_execution_plan,
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import StageTrigger
from stagr.core.models import SecretRef


def _render_to_string(
    stage_id: str = "review",
    triggers: tuple[StageTrigger, ...] = (StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
    required_secrets: tuple[SecretRef, ...] = (),
) -> str:
    """Render a stage and return the generated workflow YAML."""
    stage = build_stage(stage_id=stage_id, triggers=triggers)
    plan = build_execution_plan(stage_id=stage_id, required_secrets=required_secrets)
    context = build_render_context(stage)
    return build_renderer().render_stage(plan, stage, context).artifact.content


# ------------------------------------------------------------------
# Trigger mapping tests
# ------------------------------------------------------------------

def test_privileged_stage_produces_pull_request_target() -> None:
    """A privileged stage (non-empty required_secrets) produces pull_request_target."""
    privileged_secrets = (SecretRef(alias="PROVIDER_API_KEY", env_name="OPENAI_API_KEY"),)
    yaml_content = _render_to_string(
        triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
        required_secrets=privileged_secrets,
    )
    assert "pull_request_target" in yaml_content, (
        "Privileged stage must use pull_request_target in generated workflow"
    )
    # pull_request as a standalone on-section key must never appear for privileged stages.
    # We check that there is no bare 'pull_request:' line (not pull_request_target).
    lines = yaml_content.splitlines()
    for line in lines:
        stripped = line.strip()
        assert not (stripped == "pull_request:" or stripped.startswith("pull_request:")), (
            f"Privileged stage must never emit bare pull_request trigger; found: {line!r}"
        )


def test_non_privileged_stage_renders_successfully() -> None:
    """A non-privileged stage (no required_secrets) renders without error."""
    yaml_content = _render_to_string(
        triggers=(StageTrigger.PR_OPENED, StageTrigger.PR_UPDATED),
        required_secrets=(),
    )
    assert yaml_content, "Non-privileged stage must produce non-empty workflow YAML"
    assert "pull_request_target" in yaml_content, (
        "Non-privileged PR stage uses pull_request_target per design-doc 08 mapping"
    )


def test_pr_opened_trigger_maps_to_pull_request_target_opened_events() -> None:
    """PR_OPENED maps to pull_request_target with opened, reopened, ready_for_review."""
    yaml_content = _render_to_string(triggers=(StageTrigger.PR_OPENED,))
    assert "pull_request_target" in yaml_content
    assert "opened" in yaml_content
    assert "reopened" in yaml_content
    assert "ready_for_review" in yaml_content


def test_pr_updated_trigger_maps_to_pull_request_target_synchronize() -> None:
    """PR_UPDATED maps to pull_request_target with synchronize event."""
    yaml_content = _render_to_string(triggers=(StageTrigger.PR_UPDATED,))
    assert "pull_request_target" in yaml_content
    assert "synchronize" in yaml_content


def test_manual_trigger_maps_to_workflow_dispatch() -> None:
    """MANUAL trigger maps to workflow_dispatch."""
    yaml_content = _render_to_string(triggers=(StageTrigger.MANUAL,))
    assert "workflow_dispatch" in yaml_content
    assert "pull_request_target" not in yaml_content


def test_issue_labeled_trigger_maps_to_issues_labeled() -> None:
    """ISSUE_LABELED trigger maps to issues with labeled event."""
    yaml_content = _render_to_string(triggers=(StageTrigger.ISSUE_LABELED,))
    assert "issues:" in yaml_content
    assert "labeled" in yaml_content


# ------------------------------------------------------------------
# Concurrency block tests
# ------------------------------------------------------------------

def test_workflow_contains_concurrency_block() -> None:
    """Generated workflow contains a concurrency: block."""
    yaml_content = _render_to_string()
    assert "concurrency:" in yaml_content, (
        "Generated workflow must contain a concurrency: block"
    )


def test_concurrency_cancel_in_progress_is_false() -> None:
    """Concurrency block has cancel-in-progress: false."""
    yaml_content = _render_to_string()
    assert "cancel-in-progress: false" in yaml_content, (
        "concurrency block must have cancel-in-progress: false to prevent "
        "a reconciliation event from cancelling an in-progress invocation"
    )


def test_concurrency_key_includes_stage_id() -> None:
    """Concurrency group key includes the stage id."""
    stage_id = "my-review-stage"
    yaml_content = _render_to_string(stage_id=stage_id)
    assert f"stagr-{stage_id}-" in yaml_content, (
        f"Concurrency group key must include stage id '{stage_id}'"
    )


def test_concurrency_key_includes_pr_number_expression() -> None:
    """Concurrency group key includes the PR number GitHub expression."""
    yaml_content = _render_to_string()
    assert "github.event.pull_request.number" in yaml_content, (
        "Concurrency group key must include github.event.pull_request.number"
    )


def test_concurrency_key_includes_issue_number_fallback() -> None:
    """Concurrency group key includes the issue number fallback expression."""
    yaml_content = _render_to_string()
    assert "github.event.issue.number" in yaml_content, (
        "Concurrency group key must include github.event.issue.number as fallback"
    )


# ------------------------------------------------------------------
# App token acquisition step
# ------------------------------------------------------------------

def test_first_step_references_private_key_secret() -> None:
    """First step references the configured private_key_secret for App token acquisition."""
    yaml_content = _render_to_string()
    assert TEST_PUBLISHER_PRIVATE_KEY_SECRET in yaml_content, (
        f"Generated workflow must reference private_key_secret "
        f"'{TEST_PUBLISHER_PRIVATE_KEY_SECRET}' for App token acquisition"
    )
    assert f"secrets.{TEST_PUBLISHER_PRIVATE_KEY_SECRET}" in yaml_content, (
        "private_key_secret must appear inside a secrets.* expression"
    )


def test_first_step_references_publisher_app_id() -> None:
    """First step embeds the publisher App ID as a literal."""
    yaml_content = _render_to_string()
    assert TEST_PUBLISHER_APP_ID in yaml_content, (
        f"Generated workflow must embed publisher_app_id '{TEST_PUBLISHER_APP_ID}'"
    )


def test_app_token_step_has_id_app_token() -> None:
    """App token acquisition step has id: app-token so later steps can reference it."""
    yaml_content = _render_to_string()
    assert "id: app-token" in yaml_content, (
        "App token step must have 'id: app-token' so later steps can reference "
        "steps.app-token.outputs.token"
    )


# ------------------------------------------------------------------
# Token isolation tests
# ------------------------------------------------------------------

def test_backend_invocation_step_uses_trusted_commenter_token() -> None:
    """Backend invocation step exposes TRUSTED_COMMENTER_TOKEN when declared in the plan."""
    trusted_commenter_secret = (
        SecretRef(alias="TRUSTED_COMMENTER_TOKEN", env_name="REMEDIATION_TOKEN"),
    )
    yaml_content = _render_to_string(required_secrets=trusted_commenter_secret)
    assert "TRUSTED_COMMENTER_TOKEN" in yaml_content, (
        "Backend invocation step must expose TRUSTED_COMMENTER_TOKEN when plan declares it"
    )


def test_backend_invocation_step_does_not_use_app_token() -> None:
    """Backend invocation step must NOT reference the App token.

    The App token is for Stagr-owned platform signals (Check Run create/update).
    It must never be exposed to the backend invocation step.
    """
    yaml_content = _render_to_string()
    # The backend invocation step is step 4 (Invoke backend stub).
    # Find that step block and verify it doesn't contain app-token output reference.
    invoke_backend_index = yaml_content.find("Invoke backend")
    assert invoke_backend_index != -1, "Must have 'Invoke backend' step"

    # Find the next step after backend invocation to scope the check.
    publish_result_index = yaml_content.find("Publish result", invoke_backend_index)
    assert publish_result_index != -1, "Must have 'Publish result' step after backend step"

    backend_step_block = yaml_content[invoke_backend_index:publish_result_index]
    assert "steps.app-token.outputs.token" not in backend_step_block, (
        "Backend invocation step must not reference the App token "
        "(steps.app-token.outputs.token); that token is only for Check Run signals"
    )


def test_result_signaling_step_uses_app_token() -> None:
    """Result signaling step (step 5) references the App token for Check Run publishing."""
    yaml_content = _render_to_string()
    publish_result_index = yaml_content.find("Publish result")
    assert publish_result_index != -1, "Must have 'Publish result' step"
    publish_step_block = yaml_content[publish_result_index:]
    assert "steps.app-token.outputs.token" in publish_step_block, (
        "Result signaling step must reference steps.app-token.outputs.token "
        "for Check Run creation (App token, not TRUSTED_COMMENTER_TOKEN)"
    )


# ------------------------------------------------------------------
# Workflow file naming
# ------------------------------------------------------------------

def test_stage_artifact_has_correct_path() -> None:
    """The stage artifact path is .github/workflows/stage-<id>.yml."""
    stage_id = "security"
    stage = build_stage(stage_id=stage_id)
    plan = build_execution_plan(stage_id=stage_id)
    stage_render = build_renderer().render_stage(plan, stage, build_render_context(stage))
    assert stage_render.artifact.path == f".github/workflows/stage-{stage_id}.yml", (
        f"unexpected stage artifact path {stage_render.artifact.path!r}"
    )


def test_backend_invocation_step_env_is_plan_driven() -> None:
    """Backend invocation step env reflects exactly the plan's required_secrets."""
    secrets = (
        SecretRef(alias="PROVIDER_API_KEY", env_name="OPENAI_API_KEY"),
        SecretRef(alias="TRUSTED_COMMENTER_TOKEN", env_name="REMEDIATION_TOKEN"),
    )
    yaml_content = _render_to_string(required_secrets=secrets)

    invoke_backend_index = yaml_content.find("Invoke backend")
    assert invoke_backend_index != -1, "Must have 'Invoke backend' step"
    publish_result_index = yaml_content.find("Publish result", invoke_backend_index)
    assert publish_result_index != -1, "Must have 'Publish result' step after backend step"
    backend_step_block = yaml_content[invoke_backend_index:publish_result_index]

    assert "PROVIDER_API_KEY" in backend_step_block, (
        "Backend step must expose PROVIDER_API_KEY alias from plan"
    )
    assert "OPENAI_API_KEY" in backend_step_block, (
        "Backend step must map PROVIDER_API_KEY to its resolved env_name OPENAI_API_KEY"
    )
    assert "TRUSTED_COMMENTER_TOKEN" in backend_step_block, (
        "Backend step must expose TRUSTED_COMMENTER_TOKEN alias from plan"
    )
    assert "REMEDIATION_TOKEN" in backend_step_block, (
        "Backend step must map TRUSTED_COMMENTER_TOKEN to its resolved env_name REMEDIATION_TOKEN"
    )
    assert "steps.app-token.outputs.token" not in backend_step_block, (
        "Backend invocation step must not reference the App token"
    )


def test_backend_invocation_step_has_no_env_when_plan_has_no_secrets() -> None:
    """Backend invocation step has no env block when the plan declares no secrets."""
    yaml_content = _render_to_string(required_secrets=())

    invoke_backend_index = yaml_content.find("Invoke backend")
    assert invoke_backend_index != -1, "Must have 'Invoke backend' step"
    publish_result_index = yaml_content.find("Publish result", invoke_backend_index)
    assert publish_result_index != -1, "Must have 'Publish result' step after backend step"
    backend_step_block = yaml_content[invoke_backend_index:publish_result_index]

    # There should be no env: key in the backend step block when no secrets are declared.
    assert "env:" not in backend_step_block, (
        "Backend step must not emit an env block when the plan has no required_secrets"
    )


def test_app_token_action_uses_pinned_sha() -> None:
    """App token acquisition step uses the pinned commit SHA, not a mutable tag."""
    yaml_content = _render_to_string()
    assert "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e" in yaml_content, (
        "App token action must use the pinned commit SHA per supply-chain integrity rules; "
        "mutable tags like @v1 are not permitted"
    )
