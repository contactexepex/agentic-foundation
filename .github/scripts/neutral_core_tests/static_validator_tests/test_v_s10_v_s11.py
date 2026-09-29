"""Tests for V-S10 (auto-merge needs blocking stages) and V-S11 (dormant routing warning)."""
from __future__ import annotations


def _merge_policy(mode, blocking_stage_ids):
    from stagr.core.models import MergePolicy

    return MergePolicy(mode=mode, blocking_stage_ids=blocking_stage_ids, require_head_bound=True)


def test_v_s10_raises_for_auto_merge_without_blocking_stages() -> None:
    """V-S10 raises StaticValidationError when AUTO merge has no blocking stage."""
    from stagr.core.enums import MergeMode
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_merge_policy_has_blocking_stages

    try:
        validate_merge_policy_has_blocking_stages(_merge_policy(MergeMode.AUTO, ()))
    except StaticValidationError as validation_error:
        assert "V-S10" in str(validation_error), f"error must name V-S10: {validation_error}"
        return
    raise AssertionError("V-S10 must raise for AUTO merge with no blocking stages")


def test_v_s10_passes_for_auto_merge_with_a_blocking_stage() -> None:
    """V-S10 accepts AUTO merge when at least one stage blocks."""
    from stagr.core.enums import MergeMode
    from stagr.core.static_validator import validate_merge_policy_has_blocking_stages

    validate_merge_policy_has_blocking_stages(_merge_policy(MergeMode.AUTO, ("review",)))


def test_v_s10_passes_for_manual_merge_without_blocking_stages() -> None:
    """V-S10 only guards AUTO merge; a manual merge policy may have no blocking stages."""
    from stagr.core.enums import MergeMode
    from stagr.core.static_validator import validate_merge_policy_has_blocking_stages

    validate_merge_policy_has_blocking_stages(_merge_policy(MergeMode.MANUAL, ()))


def test_v_s11_warns_when_disabled_fast_path_keeps_routing_keys() -> None:
    """V-S11 returns the dormant-routing warning for a disabled fast_path with globs or stages."""
    from stagr.core.static_validator import DORMANT_ROUTING_WARNING, collect_dormant_routing_warnings

    for dormant_key, dormant_value in (("globs", ["docs/**"]), ("stages", {"fast": ["review"]}), ("globs", [])):
        config = {"routing": {"fast_path": {"enabled": False, dormant_key: dormant_value}}}
        assert collect_dormant_routing_warnings(config) == (DORMANT_ROUTING_WARNING,), (
            f"disabled fast_path with {dormant_key}={dormant_value!r} must warn"
        )
    assert "dormant" in DORMANT_ROUTING_WARNING and "V-S11" in DORMANT_ROUTING_WARNING


def test_v_s11_is_silent_when_nothing_is_dormant() -> None:
    """V-S11 produces no warning for enabled fast_path, a bare disabled fast_path, or no routing."""
    from stagr.core.static_validator import collect_dormant_routing_warnings

    assert collect_dormant_routing_warnings({}) == ()
    assert collect_dormant_routing_warnings({"routing": {"fast_path": {"enabled": False}}}) == ()
    assert collect_dormant_routing_warnings(
        {"routing": {"fast_path": {"enabled": True, "globs": ["docs/**"]}}}
    ) == ()
