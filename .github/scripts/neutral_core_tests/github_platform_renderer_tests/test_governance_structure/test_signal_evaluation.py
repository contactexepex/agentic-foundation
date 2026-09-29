"""Tests for governance workflow signal evaluation logic (issue #196)."""
from __future__ import annotations

from neutral_core_tests.github_platform_renderer_tests.test_governance_structure.helpers import (
    _render_governance_to_string,
)


def test_governance_workflow_has_blocked_conclusion_findings_message() -> None:
    """Governance workflow contains 'findings must be resolved' for BLOCKED conclusion."""
    yaml_content = _render_governance_to_string()
    assert "findings must be resolved" in yaml_content, (
        "Governance workflow must contain 'findings must be resolved' message "
        "for the BLOCKED StageResultConclusion so reviewers know what action to take"
    )


def test_governance_workflow_has_failed_conclusion_did_not_complete_message() -> None:
    """Governance workflow contains 'stage did not complete' for FAILED conclusion."""
    yaml_content = _render_governance_to_string()
    assert "stage did not complete" in yaml_content or "did not complete" in yaml_content, (
        "Governance workflow must contain 'did not complete' message for the FAILED "
        "StageResultConclusion so operators know this is an infrastructure failure"
    )


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
    assert '"1"' in yaml_content or "'1'" in yaml_content, (
        "Governance workflow must compare schemaVersion against '1' (the current "
        "StageResultSignal schema version)"
    )


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


def test_governance_workflow_has_merge_eligible_message() -> None:
    """Governance workflow contains a 'merge is eligible' success message."""
    yaml_content = _render_governance_to_string()
    assert "eligible" in yaml_content.lower(), (
        "Governance workflow must contain a message indicating merge eligibility "
        "when all blocking stage signals pass"
    )


def test_governance_workflow_handles_missing_check_run() -> None:
    """Governance workflow handles the case where no Check Run is found."""
    yaml_content = _render_governance_to_string()
    assert "No Check Run found" in yaml_content or "no check run" in yaml_content.lower(), (
        "Governance workflow must handle the case where no Check Run is found for a stage"
    )
