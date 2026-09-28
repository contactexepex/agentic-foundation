"""Phase 1 render loop test sub-package.

Re-exports all test functions for the top-level runner and exposes
PHASE1_RENDER_LOOP_TESTS as the ordered list the runner appends to _TESTS.
"""
from __future__ import annotations

from neutral_core_tests.phase1_render_loop_tests.test_stage_processing import (
    test_phase1_two_stages_returns_two_specs,
    test_phase1_result_count_equals_stage_count,
    test_phase1_empty_stages_returns_empty_list,
    test_phase1_multiple_secrets_all_resolved,
)
from neutral_core_tests.phase1_render_loop_tests.test_error_conditions import (
    test_phase1_missing_backend_raises_backend_renderer_not_found_error,
    test_phase1_unresolvable_alias_raises_before_platform_renderer,
    test_phase1_mismatched_stage_result_id_raises_value_error,
)
from neutral_core_tests.phase1_render_loop_tests.test_invariants import (
    test_phase1_resolved_plan_has_env_name_set,
    test_phase1_phase2_methods_not_called,
)

PHASE1_RENDER_LOOP_TESTS = [
    test_phase1_two_stages_returns_two_specs,
    test_phase1_result_count_equals_stage_count,
    test_phase1_empty_stages_returns_empty_list,
    test_phase1_multiple_secrets_all_resolved,
    test_phase1_missing_backend_raises_backend_renderer_not_found_error,
    test_phase1_unresolvable_alias_raises_before_platform_renderer,
    test_phase1_mismatched_stage_result_id_raises_value_error,
    test_phase1_resolved_plan_has_env_name_set,
    test_phase1_phase2_methods_not_called,
]

__all__ = [
    "PHASE1_RENDER_LOOP_TESTS",
    "test_phase1_two_stages_returns_two_specs",
    "test_phase1_result_count_equals_stage_count",
    "test_phase1_empty_stages_returns_empty_list",
    "test_phase1_multiple_secrets_all_resolved",
    "test_phase1_missing_backend_raises_backend_renderer_not_found_error",
    "test_phase1_unresolvable_alias_raises_before_platform_renderer",
    "test_phase1_mismatched_stage_result_id_raises_value_error",
    "test_phase1_resolved_plan_has_env_name_set",
    "test_phase1_phase2_methods_not_called",
]
