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


def test_governance_route_publisher_authentication_rejects_forged_app() -> None:
    """Route-reading block verifies app.id matches STAGR_APP_ID before trusting classification."""
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode, StageResultSignalKind
    from stagr.core.models import (
        DiscussionPolicy,
        MergePolicy,
        RenderContext,
        RoutingPolicy,
        StageResultProvenance,
        StageResultSpec,
        TrustPolicy,
    )
    from stagr.platforms.github._governance import generate_governance_workflow_yaml

    fast_path = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=("lint",), normal=("review",)),
    )
    render_ctx = RenderContext(
        stages=(),
        merge_policy=MergePolicy(
            mode=MergeMode.AUTO,
            blocking_stage_ids=("lint", "review"),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        routing_policy=RoutingPolicy(fast_path=fast_path),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )
    result_specs = (
        StageResultSpec(
            stage_id="lint",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/lint",
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
    )
    yaml_content = generate_governance_workflow_yaml(
        publisher_app_id="42",
        publisher_private_key_secret="STAGR_KEY",
        result_specs=result_specs,
        render_context=render_ctx,
    )
    assert "route_app_id" in yaml_content, (
        "Route-reading block must extract the Check Run's app.id to verify publisher identity"
    )
    assert "STAGR_APP_ID" in yaml_content, (
        "Route-reading block must compare app.id against STAGR_APP_ID before trusting the title"
    )
    assert "Rejecting classification" in yaml_content, (
        "Route-reading block must emit an error and exit when publisher identity does not match"
    )


def test_non_blocking_stage_call_has_or_true_suffix() -> None:
    """Non-blocking stage evaluation calls include '|| true' to survive set -euo pipefail."""
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode, StageResultSignalKind
    from stagr.core.models import (
        DiscussionPolicy,
        MergePolicy,
        RenderContext,
        RoutingPolicy,
        StageResultProvenance,
        StageResultSpec,
        TrustPolicy,
    )
    from stagr.platforms.github._governance import generate_governance_workflow_yaml

    render_ctx = RenderContext(
        stages=(),
        merge_policy=MergePolicy(
            mode=MergeMode.AUTO,
            blocking_stage_ids=(),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        routing_policy=RoutingPolicy(fast_path=None),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )
    result_specs = (
        StageResultSpec(
            stage_id="advisory",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/advisory",
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
    )
    yaml_content = generate_governance_workflow_yaml(
        publisher_app_id="42",
        publisher_private_key_secret="STAGR_KEY",
        result_specs=result_specs,
        render_context=render_ctx,
    )
    assert "|| true" in yaml_content, (
        "Non-blocking stage evaluation call must end with '|| true' so that "
        "set -euo pipefail does not kill the governance job on a non-zero return"
    )


def test_unrouted_stage_absent_from_generated_script() -> None:
    """A stage absent from both stages.fast and stages.normal is not evaluated."""
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode, StageResultSignalKind
    from stagr.core.models import (
        DiscussionPolicy,
        MergePolicy,
        RenderContext,
        RoutingPolicy,
        StageResultProvenance,
        StageResultSpec,
        TrustPolicy,
    )
    from stagr.platforms.github._governance import generate_governance_workflow_yaml

    fast_path = FastPathPolicy(
        match=PathMatchSpec(paths=("docs/*",)),
        stages=RouteStageMap(fast=("lint",), normal=("review",)),
    )
    render_ctx = RenderContext(
        stages=(),
        merge_policy=MergePolicy(
            mode=MergeMode.AUTO,
            blocking_stage_ids=("lint", "review", "orphan"),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        routing_policy=RoutingPolicy(fast_path=fast_path),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )
    # "orphan" stage is blocking but absent from both routes.fast and routes.normal
    orphan_selector = "stagr/orphan"
    result_specs = (
        StageResultSpec(
            stage_id="lint",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/lint",
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
        StageResultSpec(
            stage_id="review",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/review",
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
        StageResultSpec(
            stage_id="orphan",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector=orphan_selector,
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
    )
    yaml_content = generate_governance_workflow_yaml(
        publisher_app_id="42",
        publisher_private_key_secret="STAGR_KEY",
        result_specs=result_specs,
        render_context=render_ctx,
    )
    assert orphan_selector not in yaml_content, (
        "Stage absent from both routes.fast and routes.normal must be omitted from the "
        "generated governance script; it must not be evaluated unconditionally"
    )


def test_stage_check_run_query_uses_filter_all() -> None:
    """Stage signal check-run query includes filter=all to detect duplicates across suites."""
    from stagr.core.enums import AuthorRole, ForkPolicy, MergeMode, StageResultSignalKind
    from stagr.core.models import (
        DiscussionPolicy,
        MergePolicy,
        RenderContext,
        RoutingPolicy,
        StageResultProvenance,
        StageResultSpec,
        TrustPolicy,
    )
    from stagr.platforms.github._governance import generate_governance_workflow_yaml

    render_ctx = RenderContext(
        stages=(),
        merge_policy=MergePolicy(
            mode=MergeMode.AUTO,
            blocking_stage_ids=("lint",),
            require_head_bound=True,
            discussion_policy=DiscussionPolicy(require_resolved=False),
        ),
        routing_policy=RoutingPolicy(fast_path=None),
        trust_policy=TrustPolicy(
            trusted_roles=(AuthorRole.OWNER,),
            fork_policy=ForkPolicy.DENY,
            human_merge_label="human-merge",
        ),
        platform="github",
        config_version="2",
    )
    result_specs = (
        StageResultSpec(
            stage_id="lint",
            signal_kind=StageResultSignalKind.CHECK_RUN,
            signal_selector="stagr/lint",
            provenance=StageResultProvenance(publisher_identity="42"),
        ),
    )
    yaml_content = generate_governance_workflow_yaml(
        publisher_app_id="42",
        publisher_private_key_secret="STAGR_KEY",
        result_specs=result_specs,
        render_context=render_ctx,
    )
    assert "filter=all" in yaml_content, (
        "Stage check-run query must include filter=all; GitHub's default filter=latest "
        "returns only the most recent run per suite, defeating duplicate detection"
    )
