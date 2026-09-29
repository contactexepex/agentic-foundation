"""V-S08: a BackendRenderer that rejects a stage is reported as a V-S08 error naming the stage."""
from __future__ import annotations

from neutral_core_tests.static_validator_tests.helpers import make_fresh_registry, make_normalized_stage


class _BackendRendererRejectingEveryStage:
    provider: str = "stub-provider"
    backend: str = "stub-backend"

    def render(self, stage):
        raise ValueError("stub renderer cannot render this stage")


def test_v_s08_reports_a_backend_renderer_rejection_with_stage_and_reason() -> None:
    """A ValueError from BackendRenderer.render surfaces as StaticValidationError naming V-S08 and the stage."""
    from stagr.core.enums import InvocationKind
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_platform_invocation_compatibility

    registry = make_fresh_registry()
    registry.register(_BackendRendererRejectingEveryStage())
    stage = make_normalized_stage("rejected-stage")

    try:
        validate_platform_invocation_compatibility((stage,), registry, frozenset(InvocationKind))
    except StaticValidationError as validation_error:
        message = str(validation_error)
        assert "V-S08" in message and "rejected-stage" in message, f"must name V-S08 and the stage: {message}"
        assert "stub renderer cannot render this stage" in message, f"must keep the renderer's reason: {message}"
        return
    raise AssertionError("V-S08 must raise when the BackendRenderer rejects the stage")
