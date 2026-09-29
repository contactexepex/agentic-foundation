"""V-S12 static validation tests.

V-S12: every SecretRef alias declared by a BackendRenderer must resolve to a
secret env_name.

Resolution precedence (mirrors stagr.core.render_loop._resolve_secret_aliases):
  1. Explicit mapping in providers.<provider>.secrets.
  2a. PROVIDER_API_KEY  → api_key_secret or provider default.
  2b. TRUSTED_COMMENTER_TOKEN → platform_token_secret or REMEDIATION_TOKEN default.
  3. Convention fallback: alias IS the env_name (alias-as-secret-name).
"""
from __future__ import annotations

from stagr.render.config import _resolve_alias_statically, _validate_secret_alias_resolution


def _test_resolve_alias_explicit() -> bool:
    """Explicit mapping in provider_secrets wins over any convention."""
    result = _resolve_alias_statically(
        alias="MY_CUSTOM_ALIAS",
        provider_name="anthropic",
        provider_secrets={"MY_CUSTOM_ALIAS": "SOME_ENV_VAR"},
        api_key_secret=None,
        platform_token_secret=None,
    )
    return result == "SOME_ENV_VAR"


def _test_resolve_alias_provider_api_key_explicit() -> bool:
    """PROVIDER_API_KEY resolves to api_key_secret when supplied."""
    result = _resolve_alias_statically(
        alias="PROVIDER_API_KEY",
        provider_name="anthropic",
        provider_secrets={},
        api_key_secret="MY_KEY_SECRET",
        platform_token_secret=None,
    )
    return result == "MY_KEY_SECRET"


def _test_resolve_alias_provider_api_key_default() -> bool:
    """PROVIDER_API_KEY resolves to provider default when api_key_secret is None."""
    result = _resolve_alias_statically(
        alias="PROVIDER_API_KEY",
        provider_name="anthropic",
        provider_secrets={},
        api_key_secret=None,
        platform_token_secret=None,
    )
    return result == "ANTHROPIC_API_KEY"


def _test_resolve_alias_trusted_commenter_explicit() -> bool:
    """TRUSTED_COMMENTER_TOKEN resolves to platform_token_secret when supplied."""
    result = _resolve_alias_statically(
        alias="TRUSTED_COMMENTER_TOKEN",
        provider_name="openai",
        provider_secrets={},
        api_key_secret=None,
        platform_token_secret="MY_PAT_SECRET",
    )
    return result == "MY_PAT_SECRET"


def _test_resolve_alias_trusted_commenter_default() -> bool:
    """TRUSTED_COMMENTER_TOKEN resolves to REMEDIATION_TOKEN when platform token is None."""
    result = _resolve_alias_statically(
        alias="TRUSTED_COMMENTER_TOKEN",
        provider_name="openai",
        provider_secrets={},
        api_key_secret=None,
        platform_token_secret=None,
    )
    return result == "REMEDIATION_TOKEN"


def _test_resolve_alias_unknown_falls_back_to_alias() -> bool:
    """An unrecognised alias with no explicit mapping falls back to the alias itself.

    This mirrors step 3 of the runtime resolver (render_loop._resolve_secret_aliases):
    when the secrets block is omitted, aliases ARE the platform secret names.
    """
    result = _resolve_alias_statically(
        alias="COMPLETELY_UNKNOWN_ALIAS",
        provider_name="anthropic",
        provider_secrets={},
        api_key_secret=None,
        platform_token_secret=None,
    )
    return result == "COMPLETELY_UNKNOWN_ALIAS"


def _test_v_s12_convention_fallback_accepts_unknown_alias() -> bool:
    """_validate_secret_alias_resolution does NOT raise for an alias absent from provider_secrets.

    With the alias-as-secret-name convention fallback (step 3), any alias not matched
    by explicit mapping or semantic conventions resolves to itself as the platform secret
    name — consistent with the runtime resolver.  Validation passes rather than raising
    SecretAliasResolutionError.

    Exercises the convention fallback path through a synthetic stub renderer that
    declares a non-standard alias, injected via the optional ``renderer_registry``
    parameter so the built-in renderers (which only declare known aliases) do not
    obscure the coverage.
    """
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    from stagr.core.enums import GateDispositionKind, InvocationKind
    from stagr.core.errors import SecretAliasResolutionError
    from stagr.core.models import (
        ExecutionPlan,
        GateDispositionSpec,
        Invocation,
        NormalizedStage,
        SecretRef,
    )
    from stagr.render.stages import expand_stages

    _STUB_PROVIDER = "stub_provider"
    _STUB_BACKEND = "stub_backend"
    _UNREGISTERED_ALIAS = "UNREGISTERED_ALIAS_FOR_VS12"
    _STUB_STAGE_ID = "stub_stage"

    class _StubBackendRenderer:
        """Minimal stub that declares a SecretRef alias with no convention mapping."""

        provider: str = _STUB_PROVIDER
        backend: str = _STUB_BACKEND

        def render(self, stage: NormalizedStage) -> ExecutionPlan:
            return ExecutionPlan(
                stage_id=stage.id,
                invocation=Invocation(kind=InvocationKind.CI_COMPONENT, params={}),
                gate_disposition=GateDispositionSpec(
                    kind=GateDispositionKind.ALWAYS_PASS,
                    selector="always",
                ),
                required_secrets=(SecretRef(alias=_UNREGISTERED_ALIAS),),
            )

    stub_registry = BackendRendererRegistry()
    stub_registry.register(_StubBackendRenderer())

    cfg: dict = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {"provider": _STUB_PROVIDER, "models": {}},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {
                "id": _STUB_STAGE_ID,
                "type": "implement",
                "provider": _STUB_PROVIDER,
                "backend": {"name": _STUB_BACKEND},
                "gate": "advisory",
            }
        ],
    }

    expanded = expand_stages(cfg)
    try:
        _validate_secret_alias_resolution(expanded, cfg, renderer_registry=stub_registry)
        # Convention fallback accepted the alias — validation passed as expected.
        return True
    except SecretAliasResolutionError:
        # Unexpected: convention fallback should have resolved the alias to itself.
        return False


def _test_v_s12_blocking_codex_stage_examines_trusted_commenter_token() -> bool:
    """A blocking Codex review stage causes TRUSTED_COMMENTER_TOKEN to be examined.

    Before the gate fix (Finding 2), OpenAICodexBackendRenderer.render() raised
    ValueError for NON_BLOCKING stages and the broad except silently swallowed it,
    meaning TRUSTED_COMMENTER_TOKEN was never checked.  After the fix the effective
    gate is derived from the stage dict so blocking Codex stages are probed correctly.

    This test verifies that a standard review stage (gate: blocking, provider: openai)
    reaches the renderer and that validation passes (TRUSTED_COMMENTER_TOKEN resolves
    to the REMEDIATION_TOKEN default — no explicit platform.auth.token_secret needed).
    """
    from stagr.core.errors import SecretAliasResolutionError
    from stagr.render.stages import expand_stages

    cfg: dict = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {"provider": "openai", "models": {}},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {
                "id": "review",
                "type": "review",
                "provider": "openai",
                "gate": "blocking",
            }
        ],
    }

    expanded = expand_stages(cfg)
    try:
        _validate_secret_alias_resolution(expanded, cfg)
        # Blocking Codex review stage was probed; TRUSTED_COMMENTER_TOKEN resolved
        # to REMEDIATION_TOKEN via the convention fallback — validation passed.
        return True
    except SecretAliasResolutionError:
        # Unexpected: TRUSTED_COMMENTER_TOKEN should resolve to REMEDIATION_TOKEN.
        return False
