"""Static validator test sub-package (V-S07, V-S08, V-S09).

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

STATIC_VALIDATOR_TESTS = [
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
]
