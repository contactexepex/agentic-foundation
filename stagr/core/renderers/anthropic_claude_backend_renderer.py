"""BackendRenderer for the Anthropic/Claude Code implement backend.

Produces the ExecutionPlan for stages that use anthropics/claude-code-action as a
native GitHub Actions component (CI_COMPONENT invocation). IMPLEMENT stages do not
gate merge, so gate_disposition is ALWAYS_PASS and no EvidenceSpec is required.

Secret alias contract: only SecretRef.alias is set here; env_name is resolved by the
Phase 1 alias-resolution step (see issue #193) before the PlatformRenderer is invoked.
"""
from __future__ import annotations

from stagr.core.enums import GateDispositionKind, InvocationKind
from stagr.core.models import (
    ExecutionPlan,
    GateDispositionSpec,
    Invocation,
    NormalizedStage,
    SecretRef,
)

_CLAUDE_CODE_ACTION_REFERENCE = "anthropics/claude-code-action"
_PROVIDER_API_KEY_ALIAS = "PROVIDER_API_KEY"
_ANTHROPIC_API_KEY_SECRET_INPUT = "anthropic_api_key"


class AnthropicClaudeBackendRenderer:
    """BackendRenderer that produces an ExecutionPlan for the Claude Code implement backend.

    Uses anthropics/claude-code-action as a CI_COMPONENT invocation. The
    secret_inputs mapping in invocation.params lets the PlatformRenderer wire
    the correct GitHub Actions secret expression without knowing Anthropic-specific
    names.
    """

    provider: str = "anthropic"
    backend: str = "claude-code-action"

    def render(self, stage: NormalizedStage) -> ExecutionPlan:
        """Produce an ExecutionPlan for the given implement stage.

        The plan declares CI_COMPONENT invocation with the Claude Code action
        reference, an alias-only required secret, and ALWAYS_PASS gate disposition.
        No EvidenceSpec is included because IMPLEMENT stages do not gate merge.
        """
        invocation = Invocation(
            kind=InvocationKind.CI_COMPONENT,
            params={
                "action": _CLAUDE_CODE_ACTION_REFERENCE,
                "secret_inputs": {
                    _PROVIDER_API_KEY_ALIAS: _ANTHROPIC_API_KEY_SECRET_INPUT,
                },
            },
        )
        gate_disposition = GateDispositionSpec(
            kind=GateDispositionKind.ALWAYS_PASS,
            selector="always",
        )
        required_secrets = (SecretRef(alias=_PROVIDER_API_KEY_ALIAS),)

        return ExecutionPlan(
            stage_id=stage.id,
            invocation=invocation,
            gate_disposition=gate_disposition,
            required_secrets=required_secrets,
        )
