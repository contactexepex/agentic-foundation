"""Tests for V-S07: BackendRenderer availability.

V-S07 verifies that every (provider, backend) pair in the config has a
registered BackendRenderer.
"""
from __future__ import annotations

from neutral_core_tests.static_validator_tests.helpers import (
    make_fresh_registry,
    make_normalized_stage,
    StubBackendRendererPrComment,
)


def test_v_s07_passes_when_all_backends_registered() -> None:
    """V-S07 raises no error when every (provider, backend) pair is registered."""
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = make_fresh_registry()
    registry.register(StubBackendRendererPrComment())
    stage = make_normalized_stage("review-stage")

    validate_backend_renderer_availability((stage,), registry)
    # No exception means the check passed.


def test_v_s07_raises_for_unregistered_backend() -> None:
    """V-S07 raises StaticValidationError naming the provider and backend."""
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_backend_renderer_availability

    registry = make_fresh_registry()
    stage = make_normalized_stage(
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

    registry = make_fresh_registry()
    stage = make_normalized_stage("offending-stage", provider="p", backend="b")

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

    registry = make_fresh_registry()
    validate_backend_renderer_availability((), registry)
