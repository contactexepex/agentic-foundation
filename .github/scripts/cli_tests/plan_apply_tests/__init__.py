"""`stagr plan` / `stagr apply` test package; PLAN_APPLY_TESTS is the ordered list the runner calls."""
from __future__ import annotations

from .test_apply import (
    test_apply_honours_a_custom_out_directory,
    test_apply_leaves_no_temporary_files_and_writes_readable_workflows,
    test_apply_never_follows_a_planted_symlink_at_the_old_temporary_name,
    test_apply_into_temp_dir_then_validate_config_passes,
    test_apply_never_touches_unrelated_files_and_prunes_only_stale_stage_workflows,
    test_apply_repairs_a_changed_workflow_and_only_that_one,
    test_apply_twice_is_idempotent,
    test_apply_wires_the_publisher_app_id_into_the_workflows,
    test_apply_writes_expected_workflows_as_valid_yaml,
)
from .test_consistency import (
    test_a_renderer_writing_outside_its_artifact_directory_is_rejected,
    test_a_failing_stage_aborts_before_anything_is_written,
    test_explicit_backend_object_is_normalized_to_its_name,
    test_extends_base_config_is_resolved,
    test_plan_and_apply_produce_identical_stage_result_specs,
    test_plan_hashes_equal_the_files_apply_writes,
    test_rendering_uses_a_private_scratch_directory_that_is_removed,
    test_unsafe_target_paths_are_refused_before_any_write,
)
from .test_invalid_configs import (
    test_config_outside_the_project_root_is_rejected,
    test_dormant_routing_is_a_warning_not_an_error,
    test_invalid_configs_are_rejected_identically_by_plan_and_apply,
    test_missing_and_malformed_config_files_are_rejected,
    test_missing_skill_file_is_rejected,
    test_pasted_key_material_is_never_echoed,
)
from .test_merge_and_profile_settings import (
    test_empty_required_status_checks_are_accepted,
    test_modules_sonar_warns_that_the_generated_gate_does_not_evaluate_it,
    test_profile_shortcuts_warn_and_full_explains_how_to_proceed,
    test_required_status_checks_are_rejected_rather_than_silently_dropped,
)
from .test_routing_and_profile_defaults import (
    test_a_config_without_profile_gets_the_schema_default_standard,
    test_auto_merge_warns_that_the_generated_governance_does_not_merge,
    test_an_explicit_normal_route_list_is_kept_exactly,
    test_enabled_fast_path_without_stage_map_runs_every_stage_on_the_normal_route,
    test_fast_path_restrictions_that_cannot_be_enforced_are_rejected,
)
from .test_plan import (
    test_placeholder_invocation_stages_are_warned_about_by_plan_and_apply,
    test_plan_after_apply_reports_everything_unchanged,
    test_plan_reports_stale_stage_workflows_but_not_hand_written_ones,
    test_plan_valid_config_exits_zero_and_lists_every_artifact,
    test_plan_writes_nothing_into_an_existing_target_directory,
    test_plan_writes_nothing_when_target_directory_does_not_exist,
)

from .test_symlinked_output_path import (
    test_ordinary_output_directories_still_work,
    test_symlinked_ancestor_of_the_default_output_directory_is_refused,
    test_symlinked_custom_output_directory_is_refused_even_outside_the_project_root,
)

PLAN_APPLY_TESTS = [
    test_plan_valid_config_exits_zero_and_lists_every_artifact,
    test_plan_writes_nothing_when_target_directory_does_not_exist,
    test_plan_writes_nothing_into_an_existing_target_directory,
    test_plan_reports_stale_stage_workflows_but_not_hand_written_ones,
    test_plan_after_apply_reports_everything_unchanged,
    test_apply_writes_expected_workflows_as_valid_yaml,
    test_apply_wires_the_publisher_app_id_into_the_workflows,
    test_apply_twice_is_idempotent,
    test_apply_repairs_a_changed_workflow_and_only_that_one,
    test_apply_never_touches_unrelated_files_and_prunes_only_stale_stage_workflows,
    test_apply_honours_a_custom_out_directory,
    test_apply_into_temp_dir_then_validate_config_passes,
    test_apply_never_follows_a_planted_symlink_at_the_old_temporary_name,
    test_apply_leaves_no_temporary_files_and_writes_readable_workflows,
    test_placeholder_invocation_stages_are_warned_about_by_plan_and_apply,
    test_invalid_configs_are_rejected_identically_by_plan_and_apply,
    test_missing_skill_file_is_rejected,
    test_missing_and_malformed_config_files_are_rejected,
    test_config_outside_the_project_root_is_rejected,
    test_pasted_key_material_is_never_echoed,
    test_dormant_routing_is_a_warning_not_an_error,
    test_plan_hashes_equal_the_files_apply_writes,
    test_plan_and_apply_produce_identical_stage_result_specs,
    test_a_failing_stage_aborts_before_anything_is_written,
    test_a_renderer_writing_outside_its_artifact_directory_is_rejected,
    test_rendering_uses_a_private_scratch_directory_that_is_removed,
    test_unsafe_target_paths_are_refused_before_any_write,
    test_extends_base_config_is_resolved,
    test_explicit_backend_object_is_normalized_to_its_name,
    test_symlinked_ancestor_of_the_default_output_directory_is_refused,
    test_symlinked_custom_output_directory_is_refused_even_outside_the_project_root,
    test_ordinary_output_directories_still_work,
    test_required_status_checks_are_rejected_rather_than_silently_dropped,
    test_empty_required_status_checks_are_accepted,
    test_modules_sonar_warns_that_the_generated_gate_does_not_evaluate_it,
    test_profile_shortcuts_warn_and_full_explains_how_to_proceed,
    test_enabled_fast_path_without_stage_map_runs_every_stage_on_the_normal_route,
    test_an_explicit_normal_route_list_is_kept_exactly,
    test_fast_path_restrictions_that_cannot_be_enforced_are_rejected,
    test_auto_merge_warns_that_the_generated_governance_does_not_merge,
    test_a_config_without_profile_gets_the_schema_default_standard,
]
