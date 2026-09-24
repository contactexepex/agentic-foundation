"""The built-in generic backend."""

from .runner import DEFAULT_KEY_SECRET, Invocation, build_invocation

__all__ = ["DEFAULT_KEY_SECRET", "Invocation", "build_invocation"]
