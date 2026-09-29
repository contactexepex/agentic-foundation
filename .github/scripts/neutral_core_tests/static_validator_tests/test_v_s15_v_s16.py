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
    from stagr.core.static_validator import collect_unenforced_merge_warnings

    assert len(collect_unenforced_merge_warnings({"modules": {"sonar": True}})) == 1
    for config in ({}, {"modules": {}}, {"modules": {"sonar": False}}, {"modules": None}):
        assert collect_unenforced_merge_warnings(config) == (), f"no warning expected for {config!r}"


def test_v_s16_warns_for_minimal_and_standard_only() -> None:
    from stagr.core.static_validator import collect_profile_shortcut_warnings

    standard_warning = collect_profile_shortcut_warnings({"profile": "standard"})
    minimal_warning = collect_profile_shortcut_warnings({"profile": "minimal"})
    assert len(standard_warning) == 1 and "security review" in standard_warning[0]
    assert len(minimal_warning) == 1 and "security review" not in minimal_warning[0]
    for config in ({}, {"profile": "custom"}, {"profile": "full"}):
        assert collect_profile_shortcut_warnings(config) == (), f"no warning expected for {config!r}"


def test_v_s15_warns_that_auto_merge_is_not_carried_out_by_the_generated_governance() -> None:
    from stagr.core.static_validator import collect_unenforced_merge_warnings

    warnings = collect_unenforced_merge_warnings({"modules": {"auto_merge": True, "sonar": True}})
    assert len(warnings) == 2 and any("auto_merge" in warning and "never merges" in warning for warning in warnings)
    assert collect_unenforced_merge_warnings({"modules": {"auto_merge": False}}) == ()


def test_v_s17_rejects_enabled_fast_path_restrictions_that_are_not_enforced() -> None:
    from stagr.core.models import StaticValidationError
    from stagr.core.static_validator import validate_fast_path_restrictions_are_enforceable

    for key, value in (("max_files", 5), ("max_lines", 10), ("exclude", ["docs/**"])):
        try:
            validate_fast_path_restrictions_are_enforceable({"routing": {"fast_path": {"globs": ["*.md"], key: value}}})
        except StaticValidationError as validation_error:
            assert "V-S17" in str(validation_error) and key in str(validation_error)
            continue
        raise AssertionError(f"V-S17 must reject fast_path.{key}")
    for accepted in ({}, {"routing": {}}, {"routing": {"fast_path": {"globs": ["*.md"]}}},
                     {"routing": {"fast_path": {"enabled": False, "max_files": 5}}}):
        validate_fast_path_restrictions_are_enforceable(accepted)


def test_normal_route_defaults_to_every_stage_only_when_the_operator_listed_none() -> None:
    from stagr.core.models import FastPathPolicy, PathMatchSpec, RouteStageMap, RoutingPolicy
    from stagr.core.policy import default_normal_route_to_all_stages

    class FakeStage:
        def __init__(self, stage_id: str) -> None:
            self.id = stage_id

    stages = (FakeStage("build"), FakeStage("review"))

    def routing_with(normal: tuple[str, ...]) -> RoutingPolicy:
        return RoutingPolicy(FastPathPolicy(PathMatchSpec(("*.md",)), RouteStageMap(fast=("review",), normal=normal)))

    defaulted = default_normal_route_to_all_stages(routing_with(()), stages)
    assert defaulted.fast_path.stages.normal == ("build", "review") and defaulted.fast_path.stages.fast == ("review",)
    explicit = routing_with(("review",))
    assert default_normal_route_to_all_stages(explicit, stages) is explicit
    disabled = RoutingPolicy(fast_path=None)
    assert default_normal_route_to_all_stages(disabled, stages) is disabled
