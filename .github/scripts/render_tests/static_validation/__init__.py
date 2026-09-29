"""Static validation test package for V-S10 / V-S11 / V-S12.

Exported entry point: ``test_static_validation``, called by the thin runner at
``.github/scripts/test_render.py``.  Test logic lives in focused sub-modules:

- ``test_v_s10``: modules.auto_merge blocking-stage requirement
- ``test_v_s11``: dormant routing-config warning (key-presence check)
- ``test_v_s12``: SecretRef alias resolution (static path)
"""
from __future__ import annotations

from render_tests.harness import check, expect_raises
from render_tests.static_validation.test_v_s10 import (
    _v_s10_auto_merge_no_blocking,
    _v_s10_auto_merge_with_blocking,
    _v_s10_no_auto_merge_no_blocking,
)
from render_tests.static_validation.test_v_s11 import (
    _dormant_routing_stages_warning_emitted,
    _dormant_routing_warning_emitted,
    _dormant_routing_warning_on_empty_globs_list,
    _dormant_routing_warning_on_empty_stages_dict,
    _no_dormant_routing_warning_when_fast_path_enabled,
    _no_dormant_routing_warning_when_no_routing_keys,
)
from render_tests.static_validation.test_v_s12 import (
    _test_resolve_alias_explicit,
    _test_resolve_alias_provider_api_key_default,
    _test_resolve_alias_provider_api_key_explicit,
    _test_resolve_alias_trusted_commenter_default,
    _test_resolve_alias_trusted_commenter_explicit,
    _test_resolve_alias_unknown_falls_back_to_alias,
    _test_v_s12_convention_fallback_accepts_unknown_alias,
)

# Re-export the RenderError reference so callers that imported it from this
# module before the split continue to work.
from render_tests.harness import render  # noqa: F401


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
    check(
        _dormant_routing_warning_on_empty_globs_list(),
        "V-S11: disabled fast_path with globs: [] (empty list) emits dormant-routing warning",
    )
    check(
        _dormant_routing_warning_on_empty_stages_dict(),
        "V-S11: disabled fast_path with stages: {} (empty dict) emits dormant-routing warning",
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
        _test_resolve_alias_unknown_falls_back_to_alias(),
        "V-S12: unknown alias with no mapping falls back to alias-as-secret-name",
    )
    check(
        _test_v_s12_convention_fallback_accepts_unknown_alias(),
        "V-S12: _validate_secret_alias_resolution accepts unregistered alias via convention fallback",
    )
