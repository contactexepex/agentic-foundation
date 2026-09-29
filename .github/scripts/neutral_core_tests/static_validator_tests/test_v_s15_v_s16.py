"""Tests for V-S15 (settings the generated governance cannot enforce) and V-S16 (profile shortcuts)."""
from __future__ import annotations


def test_v_s15_rejects_non_empty_required_status_checks() -> None:
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_merge_settings_are_enforceable

    config = {"merge": {"required_status_checks": [{"name": "Scanner", "app_id": 1}]}}
    try:
        validate_merge_settings_are_enforceable(config)
    except StaticValidationError as validation_error:
        assert "V-S15" in str(validation_error), f"error must name V-S15: {validation_error}"
        return
    raise AssertionError("V-S15 must reject a non-empty merge.required_status_checks")


def test_v_s15_accepts_absent_or_empty_required_status_checks() -> None:
    from stagr.core.static_validator import validate_merge_settings_are_enforceable

    for config in ({}, {"merge": {}}, {"merge": None}, {"merge": {"required_status_checks": []}}):
        validate_merge_settings_are_enforceable(config)


def test_v_s15_warns_only_when_modules_sonar_is_enabled() -> None:
    from stagr.core.static_validator import collect_unenforced_sonar_warnings

    assert len(collect_unenforced_sonar_warnings({"modules": {"sonar": True}})) == 1
    for config in ({}, {"modules": {}}, {"modules": {"sonar": False}}, {"modules": None}):
        assert collect_unenforced_sonar_warnings(config) == (), f"no warning expected for {config!r}"


def test_v_s16_warns_for_minimal_and_standard_only() -> None:
    from stagr.core.static_validator import collect_profile_shortcut_warnings

    standard_warning = collect_profile_shortcut_warnings({"profile": "standard"})
    minimal_warning = collect_profile_shortcut_warnings({"profile": "minimal"})
    assert len(standard_warning) == 1 and "security review" in standard_warning[0]
    assert len(minimal_warning) == 1 and "security review" not in minimal_warning[0]
    for config in ({}, {"profile": "custom"}, {"profile": "full"}):
        assert collect_profile_shortcut_warnings(config) == (), f"no warning expected for {config!r}"
