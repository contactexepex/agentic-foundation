"""Shared config fragments for V-S10 / V-S11 / V-S12 static validation tests."""
from __future__ import annotations

from render_tests.harness import render  # noqa: F401 — re-exported for test modules

_PLATFORM: dict = {"type": "github", "default_branch": "main"}
_DEFAULTS_ANTHROPIC: dict = {
    "provider": "anthropic",
    "models": {"anthropic": {"default": "claude-opus-4-5"}},
}
_PROVIDERS_ANTHROPIC: dict = {
    "anthropic": {
        "api_key_secret": "ANTHROPIC_API_KEY",
        "secrets": {
            "PROVIDER_API_KEY": "ANTHROPIC_API_KEY",
            "TRUSTED_COMMENTER_TOKEN": "REMEDIATION_TOKEN",
        },
    }
}


def _base_cfg(**overrides) -> dict:
    """Return a minimal valid config; keyword args shallow-merge at the top level."""
    cfg: dict = {
        "version": 2,
        "profile": "custom",
        "platform": _PLATFORM,
        "defaults": _DEFAULTS_ANTHROPIC,
        "build": {"preset": "custom", "commands": {"test": "pytest"}},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {
                "id": "implement",
                "type": "implement",
                "provider": "anthropic",
                "gate": "blocking",
            }
        ],
        "providers": _PROVIDERS_ANTHROPIC,
    }
    cfg.update(overrides)
    return cfg
