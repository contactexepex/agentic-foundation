"""Tests for static validation V-S07, V-S08, and V-S09 (issue #199).

V-S07 — BackendRenderer availability: every (provider, backend) pair in the
config has a registered BackendRenderer.

V-S08 — Platform invocation compatibility: the platform supports every
InvocationKind produced by the configured backend renderers.

V-S09 — Route dependency-closure: when fast_path is enabled, each route's
stage set must be dependency-closed.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared builder helpers
# ---------------------------------------------------------------------------

def _make_normalized_stage(
    stage_id: str,
    provider: str = "stub-provider",
    backend: str = "stub-backend",
    dependencies: tuple[str, ...] = (),
):
    """Return a minimal NormalizedStage for testing."""
    from stagr.core.models import NormalizedStage
    from stagr.core.enums import StageKind, StageGate, StageTrigger

    return NormalizedStage(
        id=stage_id,
        kind=StageKind.REVIEW,
        provider=provider,
        backend=backend,
        skill=None,
        gate=StageGate.BLOCKING,
        triggers=(StageTrigger.PR_OPENED,),
        dependencies=dependencies,
    )


def _make_fresh_registry():
    """Return a new BackendRendererRegistry instance isolated from the shared singleton."""
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    return BackendRendererRegistry()


def _make_routing_policy_with_fast_path(
    fast_stage_ids: tuple[str, ...],
    normal_stage_ids: tuple[str, ...],
):
    """Return a RoutingPolicy with fast_path enabled and the given route stage sets."""
    from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy

    return RoutingPolicy(
        fast_path=FastPathPolicy(
            match=PathMatchSpec(paths=("docs/**",)),
            stages=RouteStageMap(fast=fast_stage_ids, normal=normal_stage_ids),
        )
    )


def _make_routing_policy_disabled():
    """Return a RoutingPolicy with fast_path disabled (fast_path=None)."""
    from stagr.core.models import RoutingPolicy
    return RoutingPolicy(fast_path=None)


# ---------------------------------------------------------------------------
# Stub backend renderers for testing
# ---------------------------------------------------------------------------

class _StubBackendRendererPrComment:
    """Stub BackendRenderer that produces a PR_COMMENT ExecutionPlan."""

    provider: str = "stub-provider"
    backend: str = "stub-backend"

    def render(self, stage):
        from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation
        from stagr.core.enums import GateDispositionKind, InvocationKind

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=Invocation(kind=InvocationKind.PR_COMMENT),
            gate_disposition=GateDispositionSpec(
                kind=GateDispositionKind.ALWAYS_PASS,
                selector="always",
            ),
        )


class _StubBackendRendererCiComponent:
    """Stub BackendRenderer that produces a CI_COMPONENT ExecutionPlan."""

    provider: str = "stub-provider"
    backend: str = "ci-component-backend"

    def render(self, stage):
        from stagr.core.models import ExecutionPlan, GateDispositionSpec, Invocation
        from stagr.core.enums import GateDispositionKind, InvocationKind

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=Invocation(kind=InvocationKind.CI_COMPONENT),
            gate_disposition=GateDispositionSpec(
                kind=GateDispositionKind.ALWAYS_PASS,
                selector="always",
            ),
        )


# ---------------------------------------------------------------------------
# V-S07 tests
# ---------------------------------------------------------------------------

def test_v_s07_passes_when_all_backends_registered() -> None:
    """V-S07 raises no error when every (provider, backend) pair is registered."""
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = _make_fresh_registry()
    registry.register(_StubBackendRendererPrComment())
    stage = _make_normalized_stage("review-stage")

    validate_backend_renderer_availability((stage,), registry)
    # No exception means the check passed.


def test_v_s07_raises_for_unregistered_backend() -> None:
    """V-S07 raises StaticValidationError naming the provider and backend."""
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = _make_fresh_registry()
    stage = _make_normalized_stage(
        "review-stage",
        provider="unknown-provider",
        backend="unknown-backend",
    )

    try:
        validate_backend_renderer_availability((stage,), registry)
        assert False, "Expected StaticValidationError but no exception was raised"  # noqa: B011
    except StaticValidationError as error:
        error_message = str(error)
        assert "V-S07" in error_message, (
            f"Error message must contain 'V-S07'; got: {error_message!r}"
        )
        assert "unknown-provider" in error_message, (
            f"Error message must name the provider; got: {error_message!r}"
        )
        assert "unknown-backend" in error_message, (
            f"Error message must name the backend; got: {error_message!r}"
        )


def test_v_s07_names_stage_id_in_error() -> None:
    """V-S07 error message includes the stage id of the offending stage."""
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = _make_fresh_registry()
    stage = _make_normalized_stage("offending-stage", provider="p", backend="b")

    try:
        validate_backend_renderer_availability((stage,), registry)
        assert False, "Expected StaticValidationError"  # noqa: B011
    except StaticValidationError as error:
        assert "offending-stage" in str(error), (
            f"Error message must name the stage id; got: {str(error)!r}"
        )


def test_v_s07_passes_for_empty_stages() -> None:
    """V-S07 raises no error when the stage list is empty."""
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = _make_fresh_registry()
    validate_backend_renderer_availability((), registry)


# ---------------------------------------------------------------------------
# V-S08 tests
# ---------------------------------------------------------------------------

def test_v_s08_passes_when_invocation_kind_supported() -> None:
    """V-S08 raises no error when the backend's invocation kind is in the supported set."""
    from stagr.core.enums import InvocationKind
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = _make_fresh_registry()
    renderer = _StubBackendRendererPrComment()
    registry.register(renderer)
    stage = _make_normalized_stage("review-stage")

    supported_kinds = frozenset({InvocationKind.PR_COMMENT})
    validate_platform_invocation_compatibility((stage,), registry, supported_kinds)


def test_v_s08_raises_for_unsupported_invocation_kind() -> None:
    """V-S08 raises StaticValidationError when CI_COMPONENT is used on a platform that lacks support."""
    from stagr.core.enums import InvocationKind
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = _make_fresh_registry()
    renderer = _StubBackendRendererCiComponent()
    registry.register(renderer)
    stage = _make_normalized_stage(
        "implement-stage",
        provider="stub-provider",
        backend="ci-component-backend",
    )

    # Platform supports only PR_COMMENT — CI_COMPONENT is not in the set.
    supported_kinds = frozenset({InvocationKind.PR_COMMENT, InvocationKind.API_CALL})

    try:
        validate_platform_invocation_compatibility((stage,), registry, supported_kinds)
        assert False, "Expected StaticValidationError but no exception was raised"  # noqa: B011
    except StaticValidationError as error:
        error_message = str(error)
        assert "V-S08" in error_message, (
            f"Error message must contain 'V-S08'; got: {error_message!r}"
        )
        assert "ci_component" in error_message, (
            f"Error message must name the unsupported kind; got: {error_message!r}"
        )


def test_v_s08_names_stage_in_error() -> None:
    """V-S08 error message includes the stage id."""
    from stagr.core.enums import InvocationKind
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = _make_fresh_registry()
    renderer = _StubBackendRendererCiComponent()
    registry.register(renderer)
    stage = _make_normalized_stage(
        "named-stage",
        provider="stub-provider",
        backend="ci-component-backend",
    )

    try:
        validate_platform_invocation_compatibility(
            (stage,), registry, frozenset({InvocationKind.PR_COMMENT})
        )
        assert False, "Expected StaticValidationError"  # noqa: B011
    except StaticValidationError as error:
        assert "named-stage" in str(error), (
            f"Error must name the stage id; got: {str(error)!r}"
        )


def test_v_s08_github_renderer_supports_ci_component() -> None:
    """GitHubPlatformRenderer.SUPPORTED_INVOCATION_KINDS includes CI_COMPONENT."""
    from stagr.core.enums import InvocationKind
    from stagr.platforms.github.renderer import GitHubPlatformRenderer

    assert InvocationKind.CI_COMPONENT in GitHubPlatformRenderer.SUPPORTED_INVOCATION_KINDS, (
        "GitHubPlatformRenderer must support CI_COMPONENT"
    )


# ---------------------------------------------------------------------------
# V-S09 tests
# ---------------------------------------------------------------------------

def test_v_s09_skips_when_fast_path_disabled() -> None:
    """V-S09 raises no error when fast_path is disabled (routing_policy.fast_path is None)."""
    from stagr.core.static_validator import validate_route_dependency_closure

    routing_policy = _make_routing_policy_disabled()
    # Stage with unsatisfied dependency — would fail if check ran.
    stage_with_unmet_dep = _make_normalized_stage("integration-test", dependencies=("build",))

    validate_route_dependency_closure(routing_policy, (stage_with_unmet_dep,))
    # No exception means V-S09 was correctly skipped.


def test_v_s09_passes_when_route_is_dependency_closed() -> None:
    """V-S09 raises no error when all stage dependencies are present in the route set."""
    from stagr.core.static_validator import validate_route_dependency_closure

    build_stage = _make_normalized_stage("build", dependencies=())
    integration_test_stage = _make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    routing_policy = _make_routing_policy_with_fast_path(
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

    build_stage = _make_normalized_stage("build", dependencies=())
    integration_test_stage = _make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    # Fast route omits 'build' even though 'integration-test' depends on it.
    routing_policy = _make_routing_policy_with_fast_path(
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

    build_stage = _make_normalized_stage("build", dependencies=())
    integration_test_stage = _make_normalized_stage(
        "integration-test", dependencies=("build",)
    )
    # Normal route omits 'build'.
    routing_policy = _make_routing_policy_with_fast_path(
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

    review_stage = _make_normalized_stage("review", dependencies=())
    security_stage = _make_normalized_stage("security", dependencies=())
    routing_policy = _make_routing_policy_with_fast_path(
        fast_stage_ids=("review",),
        normal_stage_ids=("review", "security"),
    )

    validate_route_dependency_closure(routing_policy, (review_stage, security_stage))


def test_v_s09_ignores_unknown_stage_id_in_route() -> None:
    """V-S09 skips route stage ids not present in normalized_stages (V-S05 covers those)."""
    from stagr.core.static_validator import validate_route_dependency_closure

    routing_policy = _make_routing_policy_with_fast_path(
        fast_stage_ids=("ghost-stage",),
        normal_stage_ids=("ghost-stage",),
    )

    validate_route_dependency_closure(routing_policy, ())
    # No exception: unknown stage ids are out of V-S09's scope.
