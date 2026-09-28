"""Tests for GitHubPlatformRenderer.render_governance workflow structure (issue #196).

Covers acceptance criteria:
  - Governance file written to .github/workflows/governance.yml
  - App token acquisition step (same pattern as render_stage)
  - Stagr App ID rendered as a literal constant for publisher-identity verification
  - PASS signal from correct Stagr App ID → merge eligible message present
  - PASS signal where check_run.app.id != Stagr App ID → rejection logic present
  - BLOCKED signal → "findings must be resolved" message present
  - FAILED signal → "stage did not complete" message present
  - Duplicate Check Runs → explicit named-error logic present (fail closed)
  - schemaVersion validation before deserialization
  - Signal fields read from output.summary, not native status/conclusion
  - Head SHA binding: stale-signal rejection logic present
  - signal_selector for each stage appears in the generated YAML
  - blocking vs non-blocking stage differentiation present
  - Private key secret referenced, not inlined
  - Pinned action SHA used for token acquisition
  - Governance file written to the correct path inside output_dir
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    TEST_PUBLISHER_APP_ID,
    TEST_PUBLISHER_PRIVATE_KEY_SECRET,
    build_execution_plan,
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import (
    AuthorRole,
    ForkPolicy,
    MergeMode,
    StageGate,
    StageResultSignalKind,
    StageTrigger,
)
from stagr.core.models import (
    DiscussionPolicy,
    MergePolicy,
    NormalizedStage,
    RenderContext,
    RoutingPolicy,
    StageResultProvenance,
    StageResultSpec,
    TrustPolicy,
)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _render_governance_to_string(
    stage_id: str = "review",
    gate: StageGate = StageGate.BLOCKING,
    extra_stage_id: str | None = None,
    extra_gate: StageGate = StageGate.NON_BLOCKING,
) -> str:
    """Render a governance workflow to a temp directory and return the YAML text."""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        renderer = build_renderer(output_dir=output_dir)

        primary_stage = build_stage(stage_id=stage_id, gate=gate)
        primary_spec = StageResultSpec(
            stage_id=stage_id,
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector=f"stagr/stage/{stage_id}",
            provenance=StageResultProvenance(publisher_identity=TEST_PUBLISHER_APP_ID),
        )

        stages = (primary_stage,)
        specs: tuple[StageResultSpec, ...] = (primary_spec,)

        if extra_stage_id is not None:
            extra_stage = build_stage(stage_id=extra_stage_id, gate=extra_gate)
            extra_spec = StageResultSpec(
                stage_id=extra_stage_id,
                signal_kind=StageResultSignalKind.CHECK_RUN,
                signal_selector=f"stagr/stage/{extra_stage_id}",
                provenance=StageResultProvenance(
                    publisher_identity=TEST_PUBLISHER_APP_ID
                ),
            )
            stages = (primary_stage, extra_stage)
            specs = (primary_spec, extra_spec)

        blocking_ids = tuple(
            stage.id for stage in stages if stage.gate is StageGate.BLOCKING
        )
        context = RenderContext(
            stages=stages,
            routing_policy=RoutingPolicy(fast_path=None),
            merge_policy=MergePolicy(
                mode=MergeMode.AUTO,
                blocking_stage_ids=blocking_ids,
                require_head_bound=True,
                discussion_policy=DiscussionPolicy(require_resolved=False),
            ),
            trust_policy=TrustPolicy(
                trusted_roles=(AuthorRole.OWNER,),
                fork_policy=ForkPolicy.DENY,
                human_merge_label="human-merge",
            ),
            platform="github",
            config_version="2",
        )
        renderer.render_governance(specs, context)
        governance_path = output_dir / ".github" / "workflows" / "governance.yml"
        return governance_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# File path tests
# ---------------------------------------------------------------------------


def test_governance_file_written_at_correct_path() -> None:
    """render_governance writes governance.yml at .github/workflows/governance.yml."""
    with tempfile.TemporaryDirectory() as temp_dir:
        output_dir = Path(temp_dir)
        renderer = build_renderer(output_dir=output_dir)
        stage = build_stage()
        context = build_render_context(stage)
        spec = StageResultSpec(
            stage_id=stage.id,
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/stage/review",
            provenance=StageResultProvenance(publisher_identity=TEST_PUBLISHER_APP_ID),
        )
        renderer.render_governance((spec,), context)
        expected_path = output_dir / ".github" / "workflows" / "governance.yml"
        assert expected_path.exists(), (
            f"Governance workflow must be written at {expected_path}"
        )


# ---------------------------------------------------------------------------
# App token acquisition tests
# ---------------------------------------------------------------------------


def test_governance_workflow_references_private_key_secret() -> None:
    """Governance workflow references the configured private_key_secret."""
    yaml_content = _render_governance_to_string()
    assert TEST_PUBLISHER_PRIVATE_KEY_SECRET in yaml_content, (
        f"Governance workflow must reference private_key_secret "
        f"'{TEST_PUBLISHER_PRIVATE_KEY_SECRET}'"
    )
    assert f"secrets.{TEST_PUBLISHER_PRIVATE_KEY_SECRET}" in yaml_content, (
        "Private key secret must appear inside a secrets.* expression"
    )


def test_governance_workflow_references_publisher_app_id_in_token_step() -> None:
    """Governance workflow embeds publisher App ID for token acquisition."""
    yaml_content = _render_governance_to_string()
    assert TEST_PUBLISHER_APP_ID in yaml_content, (
        f"Governance workflow must embed publisher_app_id '{TEST_PUBLISHER_APP_ID}' "
        "for App token acquisition"
    )


def test_governance_workflow_app_token_step_uses_pinned_sha() -> None:
    """App token acquisition step uses the pinned commit SHA."""
    yaml_content = _render_governance_to_string()
    assert "actions/create-github-app-token@a6de09a5e3e8eb40028eda38d7ad96aea41ac75e" in yaml_content, (
        "App token action must use the pinned commit SHA per supply-chain integrity rules"
    )


def test_governance_workflow_has_app_token_step_with_id() -> None:
    """Governance workflow has an App token acquisition step with id: app-token."""
    yaml_content = _render_governance_to_string()
    assert "id: app-token" in yaml_content, (
        "App token step must have 'id: app-token' so later steps can reference it"
    )


# ---------------------------------------------------------------------------
# Publisher identity verification tests
# ---------------------------------------------------------------------------


def test_governance_workflow_embeds_stagr_app_id_as_literal_for_verification() -> None:
    """Governance workflow embeds Stagr App ID as a literal constant for publisher verification.

    The STAGR_APP_ID variable must appear in the evaluate step's env section
    set to the rendered publisher_app_id literal so the shell script can
    compare check_run.app.id against it.
    """
    yaml_content = _render_governance_to_string()
    assert f'STAGR_APP_ID: "{TEST_PUBLISHER_APP_ID}"' in yaml_content, (
        f"Governance workflow must set STAGR_APP_ID env var to the literal "
        f"publisher_app_id '{TEST_PUBLISHER_APP_ID}' for publisher verification"
    )


def test_governance_workflow_has_publisher_identity_rejection_logic() -> None:
    """Governance workflow rejects Check Runs not from the trusted Stagr App.

    The generated script must compare the Check Run's app.id against STAGR_APP_ID
    and emit a rejection message when they do not match.
    """
    yaml_content = _render_governance_to_string()
    assert "publisher_app_id" in yaml_content or "STAGR_APP_ID" in yaml_content, (
        "Governance workflow must reference STAGR_APP_ID for publisher verification"
    )
    assert "Rejecting signal" in yaml_content or "publisher identity" in yaml_content.lower(), (
        "Governance workflow must contain a publisher identity rejection message"
    )


# ---------------------------------------------------------------------------
# BLOCKED conclusion tests (acceptance criteria: "findings must be resolved")
# ---------------------------------------------------------------------------


def test_governance_workflow_has_blocked_conclusion_findings_message() -> None:
    """Governance workflow contains 'findings must be resolved' for BLOCKED conclusion."""
    yaml_content = _render_governance_to_string()
    assert "findings must be resolved" in yaml_content, (
        "Governance workflow must contain 'findings must be resolved' message "
        "for the BLOCKED StageResultConclusion so reviewers know what action to take"
    )


# ---------------------------------------------------------------------------
# FAILED conclusion tests (acceptance criteria: "stage did not complete")
# ---------------------------------------------------------------------------


def test_governance_workflow_has_failed_conclusion_did_not_complete_message() -> None:
    """Governance workflow contains 'stage did not complete' for FAILED conclusion."""
    yaml_content = _render_governance_to_string()
    assert "stage did not complete" in yaml_content or "did not complete" in yaml_content, (
        "Governance workflow must contain 'did not complete' message for the FAILED "
        "StageResultConclusion so operators know this is an infrastructure failure"
    )


# ---------------------------------------------------------------------------
# Duplicate Check Run tests (acceptance criteria: fail closed on duplicates)
# ---------------------------------------------------------------------------


def test_governance_workflow_has_duplicate_check_run_detection() -> None:
    """Governance workflow has explicit duplicate Check Run detection logic.

    When more than one Check Run exists for a stage/head SHA pair, merge must
    be blocked with an error naming the stage — never silently resolved.
    """
    yaml_content = _render_governance_to_string()
    assert "Duplicate" in yaml_content or "duplicate" in yaml_content, (
        "Governance workflow must contain duplicate Check Run detection logic "
        "that fails closed and names the problematic stage"
    )


# ---------------------------------------------------------------------------
# schemaVersion validation tests
# ---------------------------------------------------------------------------


def test_governance_workflow_validates_schema_version() -> None:
    """Governance workflow validates schemaVersion before deserializing the signal."""
    yaml_content = _render_governance_to_string()
    assert "schemaVersion" in yaml_content, (
        "Governance workflow must validate schemaVersion in the Check Run payload "
        "before deserializing StageResultSignal fields"
    )


def test_governance_workflow_uses_schema_version_one() -> None:
    """Governance workflow expects schemaVersion '1' for StageResultSignal payloads."""
    yaml_content = _render_governance_to_string()
    # The script compares against "1" for the expected schema version.
    assert '"1"' in yaml_content or "'1'" in yaml_content, (
        "Governance workflow must compare schemaVersion against '1' (the current "
        "StageResultSignal schema version)"
    )


# ---------------------------------------------------------------------------
# Signal deserialization tests
# ---------------------------------------------------------------------------


def test_governance_workflow_reads_signal_from_output_summary() -> None:
    """Governance workflow reads StageResultSignal from output.summary, not native fields."""
    yaml_content = _render_governance_to_string()
    assert "output.summary" in yaml_content, (
        "Governance workflow must read the StageResultSignal JSON payload from "
        "output.summary, not from the native Check Run status/conclusion fields"
    )


def test_governance_workflow_reads_state_from_payload() -> None:
    """Governance workflow reads state from the JSON payload."""
    yaml_content = _render_governance_to_string()
    assert ".state" in yaml_content, (
        "Governance workflow must deserialize 'state' from the output.summary JSON payload"
    )


def test_governance_workflow_reads_conclusion_from_payload() -> None:
    """Governance workflow reads conclusion from the JSON payload."""
    yaml_content = _render_governance_to_string()
    assert ".conclusion" in yaml_content, (
        "Governance workflow must deserialize 'conclusion' from the output.summary JSON payload"
    )


# ---------------------------------------------------------------------------
# Head SHA binding tests
# ---------------------------------------------------------------------------


def test_governance_workflow_has_head_sha_binding_check() -> None:
    """Governance workflow rejects signals bound to a prior commit (stale signal check)."""
    yaml_content = _render_governance_to_string()
    assert "headSha" in yaml_content or "head_sha" in yaml_content, (
        "Governance workflow must check the headSha field of the StageResultSignal "
        "to reject stale signals bound to a prior commit"
    )
    assert "PR_HEAD_SHA" in yaml_content, (
        "Governance workflow must compare signal headSha against the current PR_HEAD_SHA"
    )


# ---------------------------------------------------------------------------
# Stage selector tests
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Blocking vs non-blocking differentiation tests
# ---------------------------------------------------------------------------


def test_governance_workflow_marks_blocking_stage_as_blocking() -> None:
    """Governance workflow passes 'blocking' argument for BLOCKING gate stages."""
    yaml_content = _render_governance_to_string(stage_id="review", gate=StageGate.BLOCKING)
    # The call should include the "blocking" argument for this stage.
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


# ---------------------------------------------------------------------------
# Merge eligibility message test (PASS scenario)
# ---------------------------------------------------------------------------


def test_governance_workflow_has_merge_eligible_message() -> None:
    """Governance workflow contains a 'merge is eligible' success message."""
    yaml_content = _render_governance_to_string()
    assert "eligible" in yaml_content.lower(), (
        "Governance workflow must contain a message indicating merge eligibility "
        "when all blocking stage signals pass"
    )


# ---------------------------------------------------------------------------
# No Check Run found test
# ---------------------------------------------------------------------------


def test_governance_workflow_handles_missing_check_run() -> None:
    """Governance workflow handles the case where no Check Run is found."""
    yaml_content = _render_governance_to_string()
    assert "No Check Run found" in yaml_content or "no check run" in yaml_content.lower(), (
        "Governance workflow must handle the case where no Check Run is found for a stage"
    )
