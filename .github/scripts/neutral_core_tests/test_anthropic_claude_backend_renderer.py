"""Tests for the AnthropicClaudeBackendRenderer (issue #191).

Covers: invocation kind, invocation params (action + secret_inputs), secret alias
contract, gate disposition, absence of EvidenceSpec, Protocol conformance, and
renderer identity (provider + backend).
"""
from __future__ import annotations


def _build_implement_normalized_stage():
    """Return a valid NormalizedStage representing an implement stage."""
    from stagr.core.enums import StageGate, StageKind, StageTrigger
    from stagr.core.models import NormalizedStage

    return NormalizedStage(
        id="implement-claude",
        kind=StageKind.IMPLEMENT,
        provider="anthropic",
        backend="claude-code-action",
        skill=None,
        gate=StageGate.NON_BLOCKING,
        triggers=(StageTrigger.MANUAL,),
        dependencies=(),
    )


def _build_renderer():
    """Return an AnthropicClaudeBackendRenderer instance."""
    from stagr.core.renderers.anthropic_claude_backend_renderer import (
        AnthropicClaudeBackendRenderer,
    )

    return AnthropicClaudeBackendRenderer()


def test_anthropic_renderer_invocation_kind() -> None:
    """render() returns an ExecutionPlan with invocation.kind == CI_COMPONENT."""
    from stagr.core.enums import InvocationKind

    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    assert execution_plan.invocation.kind is InvocationKind.CI_COMPONENT, (
        f"Expected invocation.kind CI_COMPONENT, got {execution_plan.invocation.kind!r}"
    )


_EXPECTED_ACTION_REFERENCE = (
    "anthropics/claude-code-action@cfc3eb22bfed5c26ef66e3223c982af27e4524de"
)


def test_anthropic_renderer_invocation_params_action() -> None:
    """invocation.params contains the exact SHA-pinned Claude Code action reference."""
    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    action_value = execution_plan.invocation.params.get("action")
    assert action_value == _EXPECTED_ACTION_REFERENCE, (
        f"Expected exact pinned action reference {_EXPECTED_ACTION_REFERENCE!r}, "
        f"got {action_value!r}"
    )


def test_anthropic_renderer_invocation_params_secret_inputs() -> None:
    """invocation.params[secret_inputs][PROVIDER_API_KEY] == 'anthropic_api_key'."""
    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    secret_inputs = execution_plan.invocation.params.get("secret_inputs")
    assert secret_inputs is not None, (
        "Expected 'secret_inputs' key in invocation.params"
    )
    provider_api_key_input = secret_inputs.get("PROVIDER_API_KEY")
    assert provider_api_key_input == "anthropic_api_key", (
        f"Expected secret_inputs['PROVIDER_API_KEY'] == 'anthropic_api_key', "
        f"got {provider_api_key_input!r}"
    )


def test_anthropic_renderer_secret_alias_only() -> None:
    """required_secrets has one SecretRef with alias set and env_name not set (None)."""
    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    assert len(execution_plan.required_secrets) == 1, (
        f"Expected exactly 1 required secret, got {len(execution_plan.required_secrets)}"
    )
    secret_ref = execution_plan.required_secrets[0]
    assert secret_ref.alias == "PROVIDER_API_KEY", (
        f"Expected alias 'PROVIDER_API_KEY', got {secret_ref.alias!r}"
    )
    assert secret_ref.env_name is None, (
        f"BackendRenderer must not set SecretRef.env_name; "
        f"got env_name={secret_ref.env_name!r} for alias={secret_ref.alias!r}"
    )


def test_anthropic_renderer_gate_disposition_always_pass() -> None:
    """render() returns ExecutionPlan with gate_disposition.kind == ALWAYS_PASS."""
    from stagr.core.enums import GateDispositionKind

    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    assert execution_plan.gate_disposition.kind is GateDispositionKind.ALWAYS_PASS, (
        f"Expected gate_disposition.kind ALWAYS_PASS, "
        f"got {execution_plan.gate_disposition.kind!r}"
    )


def test_anthropic_renderer_no_evidence_spec() -> None:
    """render() returns ExecutionPlan with no EvidenceSpec (IMPLEMENT stages do not gate merge)."""
    renderer = _build_renderer()
    stage = _build_implement_normalized_stage()

    execution_plan = renderer.render(stage)

    assert execution_plan.evidence == (), (
        f"Expected empty evidence tuple for IMPLEMENT stage, "
        f"got {execution_plan.evidence!r}"
    )


def test_anthropic_renderer_protocol_conformance() -> None:
    """isinstance(renderer, BackendRenderer) passes (runtime Protocol check)."""
    from stagr.core.backend_renderer import BackendRenderer

    renderer = _build_renderer()

    assert isinstance(renderer, BackendRenderer), (
        f"AnthropicClaudeBackendRenderer must satisfy the BackendRenderer Protocol; "
        f"isinstance check failed for type {type(renderer)}"
    )


def test_anthropic_renderer_provider_and_backend() -> None:
    """renderer.provider == 'anthropic' and renderer.backend matches the dogfood config value."""
    from stagr.render.constants import BACKEND_CLAUDE_ACTION

    renderer = _build_renderer()

    assert renderer.provider == "anthropic", (
        f"Expected provider 'anthropic', got {renderer.provider!r}"
    )
    assert renderer.backend == BACKEND_CLAUDE_ACTION, (
        f"Expected backend '{BACKEND_CLAUDE_ACTION}' (from BACKEND_CLAUDE_ACTION), "
        f"got {renderer.backend!r}"
    )
