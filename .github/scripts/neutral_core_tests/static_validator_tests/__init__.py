"""Static validator test sub-package (V-S07 through V-S11).

Re-exports all test functions for the top-level runner and exposes
STATIC_VALIDATOR_TESTS as the ordered list the runner may append to _TESTS.
"""
from __future__ import annotations

from neutral_core_tests.static_validator_tests.test_v_s07 import (
    test_v_s07_passes_when_all_backends_registered,
    test_v_s07_raises_for_unregistered_backend,
    test_v_s07_names_stage_id_in_error,
    test_v_s07_passes_for_empty_stages,
)
from neutral_core_tests.static_validator_tests.test_v_s08 import (
    test_v_s08_passes_when_invocation_kind_supported,
    test_v_s08_raises_for_unsupported_invocation_kind,
    test_v_s08_names_stage_in_error,
    test_v_s08_github_renderer_supports_ci_component,
)
from neutral_core_tests.static_validator_tests.test_v_s09 import (
    test_v_s09_skips_when_fast_path_disabled,
    test_v_s09_passes_when_route_is_dependency_closed,
    test_v_s09_raises_when_fast_route_missing_dependency,
    test_v_s09_raises_when_normal_route_missing_dependency,
    test_v_s09_passes_for_stage_with_no_dependencies,
    test_v_s09_ignores_unknown_stage_id_in_route,
)

from neutral_core_tests.static_validator_tests.test_v_s10_v_s11 import (
    test_v_s10_raises_for_auto_merge_without_blocking_stages,
    test_v_s10_passes_for_auto_merge_with_a_blocking_stage,
    test_v_s10_passes_for_manual_merge_without_blocking_stages,
    test_v_s11_warns_when_disabled_fast_path_keeps_routing_keys,
    test_v_s11_is_silent_when_nothing_is_dormant,
)
from neutral_core_tests.static_validator_tests.test_v_s15_v_s16 import (
    test_v_s15_accepts_absent_or_empty_required_status_checks,
    test_v_s15_rejects_non_empty_required_status_checks,
    test_v_s15_warns_only_when_modules_sonar_is_enabled,
    test_v_s16_warns_for_minimal_and_standard_only,
    test_v_s15_warns_that_auto_merge_is_not_carried_out_by_the_generated_governance,
    test_v_s17_rejects_enabled_fast_path_restrictions_that_are_not_enforced,
    test_normal_route_defaults_to_every_stage_only_when_the_operator_listed_none,
)
from neutral_core_tests.static_validator_tests.test_v_s08_renderer_rejection import (
    test_v_s08_reports_a_backend_renderer_rejection_with_stage_and_reason,
)

STATIC_VALIDATOR_TESTS = [
    test_v_s15_warns_that_auto_merge_is_not_carried_out_by_the_generated_governance,
    test_v_s17_rejects_enabled_fast_path_restrictions_that_are_not_enforced,
    test_normal_route_defaults_to_every_stage_only_when_the_operator_listed_none,
    test_v_s15_rejects_non_empty_required_status_checks,
    test_v_s15_accepts_absent_or_empty_required_status_checks,
    test_v_s15_warns_only_when_modules_sonar_is_enabled,
    test_v_s16_warns_for_minimal_and_standard_only,
    test_v_s07_passes_when_all_backends_registered,
    test_v_s07_raises_for_unregistered_backend,
    test_v_s07_names_stage_id_in_error,
    test_v_s07_passes_for_empty_stages,
    test_v_s08_passes_when_invocation_kind_supported,
    test_v_s08_raises_for_unsupported_invocation_kind,
    test_v_s08_names_stage_in_error,
    test_v_s08_github_renderer_supports_ci_component,
    test_v_s09_skips_when_fast_path_disabled,
    test_v_s09_passes_when_route_is_dependency_closed,
    test_v_s09_raises_when_fast_route_missing_dependency,
    test_v_s09_raises_when_normal_route_missing_dependency,
    test_v_s09_passes_for_stage_with_no_dependencies,
    test_v_s09_ignores_unknown_stage_id_in_route,
    test_v_s10_raises_for_auto_merge_without_blocking_stages,
    test_v_s10_passes_for_auto_merge_with_a_blocking_stage,
    test_v_s10_passes_for_manual_merge_without_blocking_stages,
    test_v_s11_warns_when_disabled_fast_path_keeps_routing_keys,
    test_v_s11_is_silent_when_nothing_is_dormant,
    test_v_s08_reports_a_backend_renderer_rejection_with_stage_and_reason,
]

__all__ = [
    "STATIC_VALIDATOR_TESTS",
    "test_v_s07_passes_when_all_backends_registered",
    "test_v_s07_raises_for_unregistered_backend",
    "test_v_s07_names_stage_id_in_error",
    "test_v_s07_passes_for_empty_stages",
    "test_v_s08_passes_when_invocation_kind_supported",
    "test_v_s08_raises_for_unsupported_invocation_kind",
    "test_v_s08_names_stage_in_error",
    "test_v_s08_github_renderer_supports_ci_component",
    "test_v_s09_skips_when_fast_path_disabled",
    "test_v_s09_passes_when_route_is_dependency_closed",
    "test_v_s09_raises_when_fast_route_missing_dependency",
    "test_v_s09_raises_when_normal_route_missing_dependency",
    "test_v_s09_passes_for_stage_with_no_dependencies",
    "test_v_s09_ignores_unknown_stage_id_in_route",
    "test_v_s10_raises_for_auto_merge_without_blocking_stages",
    "test_v_s10_passes_for_auto_merge_with_a_blocking_stage",
    "test_v_s10_passes_for_manual_merge_without_blocking_stages",
    "test_v_s11_warns_when_disabled_fast_path_keeps_routing_keys",
    "test_v_s11_is_silent_when_nothing_is_dormant",
    "test_v_s08_reports_a_backend_renderer_rejection_with_stage_and_reason",
]
