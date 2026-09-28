"""Tests for BackendRendererRegistry (issue #189).

Covers: registration, lookup, default backend names, has(), multi-provider
isolation, and error conditions.
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Shared stubs
# ---------------------------------------------------------------------------

class _StubBackendRendererAlpha:
    """Minimal BackendRenderer stub for provider 'openai', backend 'codex'."""

    provider: str = "openai"
    backend: str = "codex"

    def render(self, stage):  # noqa: ANN001, ANN201
        raise NotImplementedError("stub")


class _StubBackendRendererBeta:
    """Minimal BackendRenderer stub for provider 'anthropic', backend 'claude'."""

    provider: str = "anthropic"
    backend: str = "claude"

    def render(self, stage):  # noqa: ANN001, ANN201
        raise NotImplementedError("stub")


def _make_fresh_registry():
    """Return a new BackendRendererRegistry instance isolated from the module singleton."""
    from stagr.core.backend_renderer_registry import BackendRendererRegistry
    return BackendRendererRegistry()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_registry_get_returns_registered_renderer() -> None:
    """get(provider, backend) returns the exact renderer instance that was registered."""
    registry = _make_fresh_registry()
    stub_renderer = _StubBackendRendererAlpha()
    registry.register(stub_renderer)

    retrieved_renderer = registry.get("openai", "codex")

    assert retrieved_renderer is stub_renderer, (
        f"Expected the same renderer instance back; got {retrieved_renderer!r}"
    )


def test_registry_get_unknown_raises_error() -> None:
    """get() raises BackendRendererNotFoundError for an unregistered (provider, backend)."""
    from stagr.core.backend_renderer_registry import BackendRendererNotFoundError

    registry = _make_fresh_registry()

    raised = False
    try:
        registry.get("unknown-provider", "unknown-backend")
    except BackendRendererNotFoundError:
        raised = True

    assert raised, "Expected BackendRendererNotFoundError but no exception was raised"


def test_registry_default_backend_for_provider() -> None:
    """default_backend_for(provider) returns the backend name registered as the default."""
    registry = _make_fresh_registry()
    registry.register_default_backend("openai", "codex")

    default_backend_name = registry.default_backend_for("openai")

    assert default_backend_name == "codex", (
        f"Expected default backend 'codex'; got {default_backend_name!r}"
    )


def test_registry_has_returns_true_for_registered() -> None:
    """has(provider, backend) returns True after a renderer is registered for that pair."""
    registry = _make_fresh_registry()
    registry.register(_StubBackendRendererAlpha())

    result = registry.has("openai", "codex")

    assert result is True, "Expected has() to return True for a registered renderer"


def test_registry_has_returns_false_for_unregistered() -> None:
    """has(provider, backend) returns False when no renderer is registered for that pair."""
    registry = _make_fresh_registry()

    result = registry.has("openai", "codex")

    assert result is False, "Expected has() to return False for an unregistered pair"


def test_registry_multiple_providers_no_collision() -> None:
    """Renderers under different providers are stored and retrieved independently."""
    registry = _make_fresh_registry()
    openai_renderer = _StubBackendRendererAlpha()
    anthropic_renderer = _StubBackendRendererBeta()
    registry.register(openai_renderer)
    registry.register(anthropic_renderer)

    retrieved_openai = registry.get("openai", "codex")
    retrieved_anthropic = registry.get("anthropic", "claude")

    assert retrieved_openai is openai_renderer, (
        f"openai/codex lookup returned wrong renderer: {retrieved_openai!r}"
    )
    assert retrieved_anthropic is anthropic_renderer, (
        f"anthropic/claude lookup returned wrong renderer: {retrieved_anthropic!r}"
    )
    assert retrieved_openai is not retrieved_anthropic, (
        "Two distinct renderers must not be the same object"
    )


def test_registry_default_backend_for_unknown_provider_raises() -> None:
    """default_backend_for() raises BackendRendererNotFoundError when no default is registered."""
    from stagr.core.backend_renderer_registry import BackendRendererNotFoundError

    registry = _make_fresh_registry()

    raised = False
    try:
        registry.default_backend_for("unknown-provider")
    except BackendRendererNotFoundError:
        raised = True

    assert raised, (
        "Expected BackendRendererNotFoundError for unknown provider but no exception was raised"
    )
