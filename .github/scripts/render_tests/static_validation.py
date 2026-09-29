"""Tests for V-S10 / V-S11 / V-S12 static validation checks.

V-S10: modules.auto_merge: true requires at least one BLOCKING stage.
V-S11: fast_path.enabled: false with routing keys present emits a dormant-routing warning.
V-S12: every SecretRef alias declared by a BackendRenderer must resolve to a secret env_name.
"""
from __future__ import annotations

import warnings

from .harness import check, expect_raises, render
from stagr.render.config import (
    _resolve_alias_statically,
    _warn_dormant_routing_config,
)

# ---------------------------------------------------------------------------
# Minimal shared config fragments
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# V-S10 tests
# ---------------------------------------------------------------------------


def _v_s10_auto_merge_no_blocking() -> None:
    """auto_merge: true with only advisory stages must raise V-S10 RenderError."""
    cfg = _base_cfg(
        modules={"auto_merge": True},
        stages=[
            {
                "id": "implement",
                "type": "implement",
                "provider": "anthropic",
                "gate": "advisory",
            }
        ],
    )
    render.validate_config(cfg)


def _v_s10_auto_merge_with_blocking() -> None:
    """auto_merge: true with a BLOCKING Codex review stage must NOT raise."""
    # Only Codex review/security stages contribute to the auto-merge gate (check (a)),
    # so use a blocking Codex review stage (with pr_updated trigger) to satisfy V-S10.
    cfg = {
        "version": 2,
        "profile": "custom",
        "platform": {"type": "github", "default_branch": "main"},
        "defaults": {"provider": "openai", "models": {}},
        "modules": {"auto_merge": True},
        "routing": {"fast_path": {"enabled": False}},
        "stages": [
            {
                "id": "review",
                "type": "review",
                "backend": {"name": "codex"},
                "gate": "blocking",
                "triggers": ["pr_opened", "pr_updated"],
            }
        ],
    }
    render.validate_config(cfg)


def _v_s10_no_auto_merge_no_blocking() -> None:
    """No auto_merge flag with only advisory stages is fine — V-S10 is silent."""
    cfg = _base_cfg(
        stages=[
            {
                "id": "implement",
                "type": "implement",
                "provider": "anthropic",
                "gate": "advisory",
            }
        ],
    )
    render.validate_config(cfg)


# ---------------------------------------------------------------------------
# V-S11 tests
# ---------------------------------------------------------------------------


def _dormant_routing_warning_emitted() -> bool:
    """Returns True when _warn_dormant_routing_config emits a UserWarning."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "globs": ["*.md", "docs/**"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )


def _dormant_routing_stages_warning_emitted() -> bool:
    """routing.fast_path.stages present also triggers the dormant warning."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": False,
                "stages": ["implement"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return any(
        issubclass(w.category, UserWarning) and "dormant" in str(w.message).lower()
        for w in caught
    )


def _no_dormant_routing_warning_when_fast_path_enabled() -> bool:
    """No warning emitted when fast_path.enabled: true, even with globs."""
    cfg = {
        "routing": {
            "fast_path": {
                "enabled": True,
                "globs": ["*.md"],
            }
        }
    }
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return not any(issubclass(w.category, UserWarning) for w in caught)


def _no_dormant_routing_warning_when_no_routing_keys() -> bool:
    """No warning when fast_path is disabled but no routing keys are set."""
    cfg = {"routing": {"fast_path": {"enabled": False}}}
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        _warn_dormant_routing_config(cfg)
    return not any(issubclass(w.category, UserWarning) for w in caught)


# ---------------------------------------------------------------------------
# V-S12 tests (unit-level alias resolution)
# ---------------------------------------------------------------------------


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


def _test_resolve_alias_unknown_returns_none() -> bool:
    """An unrecognised alias with no explicit mapping returns None (V-S12 will reject it)."""
    result = _resolve_alias_statically(
        alias="COMPLETELY_UNKNOWN_ALIAS",
        provider_name="anthropic",
        provider_secrets={},
        api_key_secret=None,
        platform_token_secret=None,
    )
    return result is None


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------


def test_static_validation() -> None:
    """Run all V-S10 / V-S11 / V-S12 static validation tests."""

    # V-S10 ----------------------------------------------------------------
    expect_raises(
        _v_s10_auto_merge_no_blocking,
        "V-S10: auto_merge=true with zero BLOCKING stages raises RenderError",
    )
    try:
        _v_s10_auto_merge_with_blocking()
        check(True, "V-S10: auto_merge=true with a BLOCKING stage is accepted")
    except render.RenderError as exc:
        check(False, f"V-S10: auto_merge=true with a BLOCKING stage raised unexpectedly: {exc}")
    try:
        _v_s10_no_auto_merge_no_blocking()
        check(True, "V-S10: no auto_merge, advisory-only stages are accepted")
    except render.RenderError as exc:
        check(False, f"V-S10: no auto_merge, advisory-only stages raised unexpectedly: {exc}")

    # V-S11 ----------------------------------------------------------------
    check(
        _dormant_routing_warning_emitted(),
        "V-S11: disabled fast_path with globs emits dormant-routing UserWarning",
    )
    check(
        _dormant_routing_stages_warning_emitted(),
        "V-S11: disabled fast_path with stages emits dormant-routing UserWarning",
    )
    check(
        _no_dormant_routing_warning_when_fast_path_enabled(),
        "V-S11: enabled fast_path with globs emits no warning",
    )
    check(
        _no_dormant_routing_warning_when_no_routing_keys(),
        "V-S11: disabled fast_path without routing keys emits no warning",
    )

    # V-S12 ----------------------------------------------------------------
    check(
        _test_resolve_alias_explicit(),
        "V-S12: explicit provider_secrets mapping resolves alias",
    )
    check(
        _test_resolve_alias_provider_api_key_explicit(),
        "V-S12: PROVIDER_API_KEY resolves to supplied api_key_secret",
    )
    check(
        _test_resolve_alias_provider_api_key_default(),
        "V-S12: PROVIDER_API_KEY resolves to provider default (anthropic -> ANTHROPIC_API_KEY)",
    )
    check(
        _test_resolve_alias_trusted_commenter_explicit(),
        "V-S12: TRUSTED_COMMENTER_TOKEN resolves to supplied platform_token_secret",
    )
    check(
        _test_resolve_alias_trusted_commenter_default(),
        "V-S12: TRUSTED_COMMENTER_TOKEN resolves to REMEDIATION_TOKEN default",
    )
    check(
        _test_resolve_alias_unknown_returns_none(),
        "V-S12: unknown alias with no mapping returns None",
    )
