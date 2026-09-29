"""Tests for V-S09: Route dependency-closure.

V-S09 verifies that when fast_path is enabled, each route's stage set is
dependency-closed (every dependency of a route stage is also in that route).
"""
from __future__ import annotations

from neutral_core_tests.static_validator_tests.helpers import (
    make_normalized_stage,
    make_routing_policy_disabled,
    make_routing_policy_with_fast_path,
)


def test_v_s09_skips_when_fast_path_disabled() -> None:
    """V-S09 raises no error when fast_path is disabled (routing_policy.fast_path is None)."""
    from stagr.core.static_validator import validate_route_dependency_closure

    routing_policy = make_routing_policy_disabled()
    # Stage with unsatisfied dependency — would fail if check ran.
    stage_with_unmet_dep = make_normalized_stage("integration-test", dependencies=("build",))

    validate_route_dependency_closure(routing_policy, (stage_with_unmet_dep,))
    # No exception means V-S09 was correctly skipped.


def test_v_s09_passes_when_route_is_dependency_closed() -> None:
    """V-S09 raises no error when all stage dependencies are present in the route set."""
    from stagr.core.static_validator import validate_route_dependency_closure

    build_stage = make_normalized_stage("build", dependencies=())
    integration_test_stage = make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    routing_policy = make_routing_policy_with_fast_path(
        fast_stage_ids=("build", "integration-test"),
        normal_stage_ids=("build", "integration-test"),
    )

    validate_route_dependency_closure(routing_policy, (build_stage, integration_test_stage))


def test_v_s09_raises_when_fast_route_missing_dependency() -> None:
    """V-S09 raises StaticValidationError naming the stage and missing dependency.

    This is the explicit acceptance-criteria test: a fast route contains
    'integration-test' (which depends on 'build') but not 'build'.
    """
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_route_dependency_closure

    build_stage = make_normalized_stage("build", dependencies=())
    integration_test_stage = make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    # Fast route omits 'build' even though 'integration-test' depends on it.
    routing_policy = make_routing_policy_with_fast_path(
        fast_stage_ids=("integration-test",),
        normal_stage_ids=("build", "integration-test"),
    )

    try:
        validate_route_dependency_closure(
            routing_policy, (build_stage, integration_test_stage)
        )
        assert False, "Expected StaticValidationError but no exception was raised"  # noqa: B011
    except StaticValidationError as error:
        error_message = str(error)
        assert "V-S09" in error_message, (
            f"Error message must contain 'V-S09'; got: {error_message!r}"
        )
        assert "integration-test" in error_message, (
            f"Error message must name the stage 'integration-test'; got: {error_message!r}"
        )
        assert "build" in error_message, (
            f"Error message must name the missing dependency 'build'; got: {error_message!r}"
        )


def test_v_s09_raises_when_normal_route_missing_dependency() -> None:
    """V-S09 also checks the normal route, not only the fast route."""
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_route_dependency_closure

    build_stage = make_normalized_stage("build", dependencies=())
    integration_test_stage = make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    # Normal route omits 'build'.
    routing_policy = make_routing_policy_with_fast_path(
        fast_stage_ids=("build", "integration-test"),
        normal_stage_ids=("integration-test",),
    )

    try:
        validate_route_dependency_closure(
            routing_policy, (build_stage, integration_test_stage)
        )
        assert False, "Expected StaticValidationError"  # noqa: B011
    except StaticValidationError as error:
        assert "V-S09" in str(error), (
            f"Error must contain 'V-S09'; got: {str(error)!r}"
        )
        assert "normal" in str(error), (
            f"Error must name the 'normal' route; got: {str(error)!r}"
        )


def test_v_s09_passes_for_stage_with_no_dependencies() -> None:
    """V-S09 raises no error when all route stages have empty dependency lists."""
    from stagr.core.static_validator import validate_route_dependency_closure

    review_stage = make_normalized_stage("review", dependencies=())
    security_stage = make_normalized_stage("security", dependencies=())
    routing_policy = make_routing_policy_with_fast_path(
        fast_stage_ids=("review",),
        normal_stage_ids=("review", "security"),
    )

    validate_route_dependency_closure(routing_policy, (review_stage, security_stage))


def test_v_s09_ignores_unknown_stage_id_in_route() -> None:
    """V-S09 skips route stage ids not present in normalized_stages (V-S05 covers those)."""
    from stagr.core.static_validator import validate_route_dependency_closure

    routing_policy = make_routing_policy_with_fast_path(
        fast_stage_ids=("ghost-stage",),
        normal_stage_ids=("ghost-stage",),
    )

    validate_route_dependency_closure(routing_policy, ())
    # No exception: unknown stage ids are out of V-S09's scope.
