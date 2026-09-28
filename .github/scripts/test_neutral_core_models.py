#!/usr/bin/env python3
"""Tests for neutral core data models and enumerations (Group A: issues #173–#178).

Run with: python .github/scripts/test_neutral_core_models.py
No pytest required. Exit 0 = all pass.

This is a thin runner. The tests live in scoped modules under ``neutral_core_tests/``,
all sharing the single ``failures`` list defined in ``neutral_core_tests.harness``.
Run as a script, ``sys.path[0]`` is ``.github/scripts``, so ``neutral_core_tests``
resolves as a package.
"""
from __future__ import annotations

import sys

from neutral_core_tests.harness import _fail, _ok, failures
from neutral_core_tests.test_enums import test_enum_string_values
from neutral_core_tests.test_normalized_stage import (
    test_normalized_stage_construction,
    test_normalized_stage_empty_dependencies,
)
from neutral_core_tests.test_execution_plan import (
    test_execution_plan_requires_gate_disposition,
    test_execution_plan_valid,
    test_invocation_params_deep_immutable,
    test_invocation_params_immutable,
)
from neutral_core_tests.test_evidence_and_gate import test_evidence_spec_construction
from neutral_core_tests.test_stage_result import (
    test_stage_result_signal_requires_head_sha,
    test_stage_result_spec_construction,
)
from neutral_core_tests.test_render_context import (
    test_render_context_construction,
    test_render_context_is_immutable,
)
from neutral_core_tests.test_normalize import (
    test_filter_disabled_stages_removes_disabled,
    test_filter_disabled_stages_absent_defaults_to_enabled,
    test_filter_disabled_stages_explicit_true_is_present,
    test_filter_disabled_stages_does_not_mutate_input,
    test_filter_disabled_stages_dogfood_config,
    test_filter_disabled_stages_disables_profile_provided_stage,
    test_expand_profile_defaults_minimal_shape,
    test_expand_profile_defaults_standard_shape,
    test_expand_profile_defaults_standard_fills_missing_fields,
    test_expand_profile_defaults_custom_adds_no_fields,
    test_expand_profile_defaults_explicit_fields_override_profile,
    test_expand_profile_defaults_unrecognized_profile_raises,
    test_expand_profile_defaults_missing_id_raises,
    test_expand_profile_defaults_duplicate_ids_raise,
    test_expand_profile_defaults_is_idempotent,
    test_expand_profile_defaults_does_not_mutate_input,
    test_expand_profile_defaults_standard_includes_all_profile_stages,
    test_expand_profile_defaults_nested_lists_are_not_shared,
    test_expand_profile_defaults_operator_depends_on_survives_expansion,
)
from neutral_core_tests.test_dag import (
    test_dag_linear_chain_passes,
    test_dag_cycle_raises_v_s04,
    test_dag_unknown_dep_raises_v_s05,
    test_dag_disabled_dep_raises_v_s05,
    test_dag_no_deps_passes,
    test_dag_does_not_mutate_input,
    test_dag_parallel_stages_pass,
    test_dag_empty_active_stages_passes,
    test_dag_direct_two_stage_cycle_raises_v_s04,
    test_dag_cycle_error_excludes_downstream_dependents,
)
from neutral_core_tests.test_defaults import (
    test_defaults_provider_propagates,
    test_defaults_explicit_provider_not_overridden,
    test_defaults_model_resolved_from_defaults,
    test_defaults_model_absent_when_no_provider_default,
    test_defaults_missing_provider_raises_config_error,
    test_defaults_does_not_mutate_input,
    test_defaults_empty_defaults_cfg,
    test_defaults_explicit_model_binding_normalized_to_string,
    test_defaults_provider_model_binding_with_tiers_preserved,
    test_defaults_mixed_binding_with_tiers_preserved,
    test_defaults_tier_only_binding_preserved,
)
from neutral_core_tests.test_pipeline_dogfood import (
    test_pipeline_dogfood_config_produces_three_stages,
    test_pipeline_dogfood_config_stage_ids_present,
    test_pipeline_dogfood_config_implement_claude,
    test_pipeline_dogfood_config_review,
    test_pipeline_dogfood_config_security,
    test_pipeline_dogfood_config_no_enabled_field,
    test_pipeline_dogfood_config_backend_derived_from_provider,
)
from neutral_core_tests.test_pipeline_edge_cases import (
    test_pipeline_empty_stages_returns_empty_tuple,
    test_pipeline_single_active_stage,
    test_pipeline_all_disabled_stages_returns_empty_tuple,
    test_pipeline_defaults_provider_propagates_to_stage,
    test_pipeline_returns_tuple_not_list,
    test_pipeline_gate_defaults_to_non_blocking_when_absent,
    test_pipeline_advisory_gate_maps_to_non_blocking,
    test_pipeline_dependencies_tuple_from_depends_on,
    test_pipeline_tiered_model_binding_raises_not_silently_collapsed,
)
from neutral_core_tests.test_policy_routing import (
    test_routing_policy_dogfood_config,
    test_routing_policy_absent_routing_key,
    test_routing_policy_disabled_fast_path,
    test_routing_policy_enabled_fast_path,
    test_routing_policy_no_error_on_dormant_config,
    test_routing_policy_routing_present_no_fast_path_key,
    test_routing_policy_absent_enabled_key_uses_default,
)
from neutral_core_tests.test_policy_trust import (
    test_trust_policy_dogfood_config,
    test_trust_policy_default_fork_policy_is_deny,
    test_trust_policy_explicit_fork_policy,
    test_trust_policy_default_human_merge_label,
    test_trust_policy_custom_human_merge_label,
    test_trust_policy_contributor_not_in_defaults,
    test_trust_policy_absent_trusted_roles_key_uses_default,
    test_trust_policy_unrecognized_role_raises,
    test_trust_policy_unrecognized_role_names_bad_value,
    test_trust_policy_absent_platform_section,
    test_trust_policy_empty_trusted_roles,
    test_trust_policy_returns_trust_policy_instance,
    test_trust_policy_result_is_frozen,
)
from neutral_core_tests.test_policy_merge_blocking import (
    test_merge_policy_dogfood_config,
    test_merge_policy_blocking_stages_included,
    test_merge_policy_non_blocking_excluded,
    test_merge_policy_empty_stages_produces_empty_blocking_ids,
    test_merge_policy_mixed_gates_only_blocking_included,
    test_merge_policy_unknown_module_key_raises_schema_error,
)
from neutral_core_tests.test_policy_merge_derivation import (
    test_merge_policy_mode_auto_when_auto_merge_true,
    test_merge_policy_mode_manual_when_auto_merge_false,
    test_merge_policy_mode_manual_when_modules_absent,
    test_merge_policy_require_head_bound_always_true,
    test_merge_policy_discussion_policy_absent_is_none,
    test_merge_policy_discussion_policy_require_resolved_true,
    test_merge_policy_discussion_policy_require_resolved_false,
    test_merge_policy_sonar_true_adds_external_gate,
    test_merge_policy_sonar_false_no_external_gate,
    test_merge_policy_sonar_absent_no_external_gate,
    test_merge_policy_returns_merge_policy_instance,
    test_merge_policy_result_is_frozen,
)
from neutral_core_tests.test_backend_renderer import (
    test_backend_renderer_protocol_conformance,
    test_backend_renderer_secret_alias_only,
    test_backend_renderer_gate_disposition_set,
    test_backend_renderer_no_platform_fields,
)
from neutral_core_tests.test_anthropic_claude_backend_renderer import (
    test_anthropic_renderer_invocation_kind,
    test_anthropic_renderer_invocation_params_action,
    test_anthropic_renderer_invocation_params_secret_inputs,
    test_anthropic_renderer_secret_alias_only,
    test_anthropic_renderer_gate_disposition_always_pass,
    test_anthropic_renderer_no_evidence_spec,
    test_anthropic_renderer_protocol_conformance,
    test_anthropic_renderer_provider_and_backend,
)
from neutral_core_tests.test_backend_renderer_registry import (
    test_registry_get_returns_registered_renderer,
    test_registry_get_unknown_raises_error,
    test_registry_default_backend_for_provider,
    test_registry_has_returns_true_for_registered,
    test_registry_has_returns_false_for_unregistered,
    test_registry_multiple_providers_no_collision,
    test_registry_default_backend_for_unknown_provider_raises,
)
from neutral_core_tests.test_openai_codex_backend_renderer import (
    test_codex_renderer_invocation_kind_is_pr_comment,
    test_codex_renderer_required_secret_alias_and_no_env_name,
    test_codex_renderer_gate_disposition_kind_is_explicit_pass_marker,
    test_codex_renderer_evidence_has_one_review_result_spec,
    test_codex_renderer_evidence_head_sha_correlation_is_true,
    test_codex_renderer_protocol_conformance,
    test_codex_renderer_provider_and_backend_match_config,
    test_codex_renderer_review_stage_posts_codex_review_command,
    test_codex_renderer_security_stage_posts_security_review_command,
    test_codex_renderer_gate_disposition_has_no_scope,
)

_TESTS = [
    test_enum_string_values,
    test_normalized_stage_construction,
    test_normalized_stage_empty_dependencies,
    test_invocation_params_immutable,
    test_invocation_params_deep_immutable,
    test_execution_plan_requires_gate_disposition,
    test_execution_plan_valid,
    test_evidence_spec_construction,
    test_stage_result_signal_requires_head_sha,
    test_stage_result_spec_construction,
    test_render_context_construction,
    test_render_context_is_immutable,
    test_filter_disabled_stages_removes_disabled,
    test_filter_disabled_stages_absent_defaults_to_enabled,
    test_filter_disabled_stages_explicit_true_is_present,
    test_filter_disabled_stages_does_not_mutate_input,
    test_filter_disabled_stages_dogfood_config,
    test_filter_disabled_stages_disables_profile_provided_stage,
    test_expand_profile_defaults_minimal_shape,
    test_expand_profile_defaults_standard_shape,
    test_expand_profile_defaults_standard_fills_missing_fields,
    test_expand_profile_defaults_custom_adds_no_fields,
    test_expand_profile_defaults_explicit_fields_override_profile,
    test_expand_profile_defaults_unrecognized_profile_raises,
    test_expand_profile_defaults_missing_id_raises,
    test_expand_profile_defaults_duplicate_ids_raise,
    test_expand_profile_defaults_is_idempotent,
    test_expand_profile_defaults_does_not_mutate_input,
    test_expand_profile_defaults_standard_includes_all_profile_stages,
    test_expand_profile_defaults_nested_lists_are_not_shared,
    test_expand_profile_defaults_operator_depends_on_survives_expansion,
    test_dag_linear_chain_passes,
    test_dag_cycle_raises_v_s04,
    test_dag_unknown_dep_raises_v_s05,
    test_dag_disabled_dep_raises_v_s05,
    test_dag_no_deps_passes,
    test_dag_does_not_mutate_input,
    test_dag_parallel_stages_pass,
    test_dag_empty_active_stages_passes,
    test_dag_direct_two_stage_cycle_raises_v_s04,
    test_dag_cycle_error_excludes_downstream_dependents,
    test_defaults_provider_propagates,
    test_defaults_explicit_provider_not_overridden,
    test_defaults_model_resolved_from_defaults,
    test_defaults_model_absent_when_no_provider_default,
    test_defaults_missing_provider_raises_config_error,
    test_defaults_does_not_mutate_input,
    test_defaults_empty_defaults_cfg,
    test_defaults_explicit_model_binding_normalized_to_string,
    test_defaults_provider_model_binding_with_tiers_preserved,
    test_defaults_mixed_binding_with_tiers_preserved,
    test_defaults_tier_only_binding_preserved,
    test_pipeline_dogfood_config_produces_three_stages,
    test_pipeline_dogfood_config_stage_ids_present,
    test_pipeline_dogfood_config_implement_claude,
    test_pipeline_dogfood_config_review,
    test_pipeline_dogfood_config_security,
    test_pipeline_dogfood_config_no_enabled_field,
    test_pipeline_dogfood_config_backend_derived_from_provider,
    test_pipeline_empty_stages_returns_empty_tuple,
    test_pipeline_single_active_stage,
    test_pipeline_all_disabled_stages_returns_empty_tuple,
    test_pipeline_defaults_provider_propagates_to_stage,
    test_pipeline_returns_tuple_not_list,
    test_pipeline_gate_defaults_to_non_blocking_when_absent,
    test_pipeline_advisory_gate_maps_to_non_blocking,
    test_pipeline_dependencies_tuple_from_depends_on,
    test_pipeline_tiered_model_binding_raises_not_silently_collapsed,
    test_routing_policy_dogfood_config,
    test_routing_policy_absent_routing_key,
    test_routing_policy_disabled_fast_path,
    test_routing_policy_enabled_fast_path,
    test_routing_policy_no_error_on_dormant_config,
    test_routing_policy_routing_present_no_fast_path_key,
    test_routing_policy_absent_enabled_key_uses_default,
    test_trust_policy_dogfood_config,
    test_trust_policy_default_fork_policy_is_deny,
    test_trust_policy_explicit_fork_policy,
    test_trust_policy_default_human_merge_label,
    test_trust_policy_custom_human_merge_label,
    test_trust_policy_contributor_not_in_defaults,
    test_trust_policy_absent_trusted_roles_key_uses_default,
    test_trust_policy_unrecognized_role_raises,
    test_trust_policy_unrecognized_role_names_bad_value,
    test_trust_policy_absent_platform_section,
    test_trust_policy_empty_trusted_roles,
    test_trust_policy_returns_trust_policy_instance,
    test_trust_policy_result_is_frozen,
    test_merge_policy_dogfood_config,
    test_merge_policy_blocking_stages_included,
    test_merge_policy_non_blocking_excluded,
    test_merge_policy_empty_stages_produces_empty_blocking_ids,
    test_merge_policy_mixed_gates_only_blocking_included,
    test_merge_policy_unknown_module_key_raises_schema_error,
    test_merge_policy_mode_auto_when_auto_merge_true,
    test_merge_policy_mode_manual_when_auto_merge_false,
    test_merge_policy_mode_manual_when_modules_absent,
    test_merge_policy_require_head_bound_always_true,
    test_merge_policy_discussion_policy_absent_is_none,
    test_merge_policy_discussion_policy_require_resolved_true,
    test_merge_policy_discussion_policy_require_resolved_false,
    test_merge_policy_sonar_true_adds_external_gate,
    test_merge_policy_sonar_false_no_external_gate,
    test_merge_policy_sonar_absent_no_external_gate,
    test_merge_policy_returns_merge_policy_instance,
    test_merge_policy_result_is_frozen,
    test_backend_renderer_protocol_conformance,
    test_backend_renderer_secret_alias_only,
    test_backend_renderer_gate_disposition_set,
    test_backend_renderer_no_platform_fields,
    test_anthropic_renderer_invocation_kind,
    test_anthropic_renderer_invocation_params_action,
    test_anthropic_renderer_invocation_params_secret_inputs,
    test_anthropic_renderer_secret_alias_only,
    test_anthropic_renderer_gate_disposition_always_pass,
    test_anthropic_renderer_no_evidence_spec,
    test_anthropic_renderer_protocol_conformance,
    test_anthropic_renderer_provider_and_backend,
    test_registry_get_returns_registered_renderer,
    test_registry_get_unknown_raises_error,
    test_registry_default_backend_for_provider,
    test_registry_has_returns_true_for_registered,
    test_registry_has_returns_false_for_unregistered,
    test_registry_multiple_providers_no_collision,
    test_registry_default_backend_for_unknown_provider_raises,
    test_codex_renderer_invocation_kind_is_pr_comment,
    test_codex_renderer_required_secret_alias_and_no_env_name,
    test_codex_renderer_gate_disposition_kind_is_explicit_pass_marker,
    test_codex_renderer_evidence_has_one_review_result_spec,
    test_codex_renderer_evidence_head_sha_correlation_is_true,
    test_codex_renderer_protocol_conformance,
    test_codex_renderer_provider_and_backend_match_config,
    test_codex_renderer_review_stage_posts_codex_review_command,
    test_codex_renderer_security_stage_posts_security_review_command,
    test_codex_renderer_gate_disposition_has_no_scope,
]

if __name__ == "__main__":
    for t in _TESTS:
        try:
            t()
            _ok(t.__name__)
        except Exception as exc:
            _fail(t.__name__, exc)

    if failures:
        print(f"\n{len(failures)} test(s) failed: {failures}")
        sys.exit(1)
    print(f"\n{len(_TESTS)} tests passed.")
