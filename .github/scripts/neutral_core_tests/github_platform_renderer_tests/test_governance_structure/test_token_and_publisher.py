"""Tests for governance workflow App token acquisition and publisher identity (issue #196)."""
from __future__ import annotations

import tempfile
from pathlib import Path

from neutral_core_tests.github_platform_renderer_tests.helpers import (
    TEST_PUBLISHER_APP_ID,
    TEST_PUBLISHER_PRIVATE_KEY_SECRET,
    build_render_context,
    build_renderer,
    build_stage,
)
from stagr.core.enums import StageResultSignalKind
from stagr.core.models import StageResultProvenance, StageResultSpec

from neutral_core_tests.github_platform_renderer_tests.test_governance_structure.helpers import (
    _render_governance_to_string,
)


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
