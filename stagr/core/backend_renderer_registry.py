"""BackendRenderer registry.

Stores BackendRenderer instances keyed by (provider, backend) and tracks
per-provider default backend names. The module exports a single shared
instance (``registry``) for use across a full render pass.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .backend_renderer import BackendRenderer


class BackendRendererNotFoundError(Exception):
    """Raised when no BackendRenderer is registered for a (provider, backend) pair."""


class BackendRendererRegistry:
    """Stores and retrieves BackendRenderer instances by (provider, backend).

    Supports per-provider default backend name registration so callers can
    resolve a renderer without knowing the backend name explicitly.
    """

    def __init__(self) -> None:
        self._renderers: dict[tuple[str, str], "BackendRenderer"] = {}
        self._default_backends: dict[str, str] = {}

    def register(self, renderer: "BackendRenderer") -> None:
        """Add a renderer to the registry under its (provider, backend) key.

        Overwrites any previously registered renderer for the same key.
        """
        self._renderers[(renderer.provider, renderer.backend)] = renderer

    def register_default_backend(self, provider: str, backend_name: str) -> None:
        """Record the default backend name for a provider.

        Overwrites any previously registered default for the same provider.
        """
        self._default_backends[provider] = backend_name

    def get(self, provider: str, backend: str) -> "BackendRenderer":
        """Return the renderer registered under (provider, backend).

        Raises BackendRendererNotFoundError when no renderer is registered
        for the given pair.
        """
        renderer = self._renderers.get((provider, backend))
        if renderer is None:
            raise BackendRendererNotFoundError(
                f"No BackendRenderer registered for provider={provider!r}, backend={backend!r}"
            )
        return renderer

    def default_backend_for(self, provider: str) -> str:
        """Return the default backend name registered for provider.

        Raises BackendRendererNotFoundError when no default is registered
        for the given provider.
        """
        backend_name = self._default_backends.get(provider)
        if backend_name is None:
            raise BackendRendererNotFoundError(
                f"No default backend registered for provider={provider!r}"
            )
        return backend_name

    def has(self, provider: str, backend: str) -> bool:
        """Return True when a renderer is registered for (provider, backend)."""
        return (provider, backend) in self._renderers


registry: BackendRendererRegistry = BackendRendererRegistry()
