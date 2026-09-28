"""Render-pipeline error types.

Errors raised during the Phase 1 rendering loop. These are distinct from
normalization-time errors (ConfigError, StaticValidationError in models.py)
because they occur after the normalized stage graph has been validated.
"""
from __future__ import annotations


class SecretAliasResolutionError(Exception):
    """Raised when a SecretRef alias has no mapping in provider_config.

    The Phase 1 alias resolution step looks up each SecretRef.alias in
    ``provider_config["providers"][<provider>]["secrets"][<alias>]``. When
    an alias is absent from that mapping, this error is raised before the
    PlatformRenderer is called for the affected stage.

    The error message names the stage, the provider, and the unresolvable alias
    so the operator can correct their provider configuration.
    """
