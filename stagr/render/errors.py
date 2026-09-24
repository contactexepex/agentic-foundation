"""The renderer's fail-loud error type."""
from __future__ import annotations


class RenderError(Exception):
    """A configuration/resolution error that must fail loudly."""
