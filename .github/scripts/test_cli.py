#!/usr/bin/env python3
"""Tests for the M3 operator CLI (doctor / plan / apply).

Runnable with plain `python .github/scripts/test_cli.py` (no pytest). Covers the health
report (secret-by-NAME, no secret values, model resolution, lane selection), fail-loud on an
unresolvable config, and plan/apply determinism + idempotency + prune. Exit 0 = pass.

This is a thin runner: the tests live in scoped modules under `cli_tests/`, all sharing the
single `failures` list defined in `cli_tests.harness`. Run as a script, `sys.path[0]` is
`.github/scripts`, so `cli_tests` resolves as a package.
"""
from __future__ import annotations

import sys

from cli_tests.harness import failures
from cli_tests.report import (
    test_doctor_fail_loud,
    test_doctor_no_secret_values_and_exit,
    test_report,
)
from cli_tests.paths import (
    test_config_path_confined_to_project_root,
    test_config_path_symlink_loop_is_clean_error,
)
from cli_tests.plan_apply import test_plan_apply_idempotent
from cli_tests.help import test_help_command
from cli_tests.init_generate import (
    test_init_build_presets_match_schema_and_wizard_validates,
    test_init_escapes_test_command,
    test_init_full_profile_keeps_security_blocking,
    test_init_next_steps_carry_custom_config_path,
    test_init_print_keeps_stdout_yaml_only,
    test_init_profiles_generate_valid_configs,
    test_init_quotes_yaml_keyword_scalars,
    test_init_review_gate_derived_from_profile,
    test_init_wizard_defaults_and_nontty,
    test_init_wizard_governance_unrecognized_keeps_profile_default,
    test_init_writes_utf8,
)
from cli_tests.init_guards import (
    test_init_refuses_symlink_destination,
    test_init_rejects_pasted_credential_value,
    test_init_rejects_values_the_pipeline_would_reject,
    test_init_reports_write_failure_without_traceback,
    test_init_write_and_overwrite_guard,
)
from cli_tests.detect import (
    test_default_token_secret_is_neutral,
    test_detect_build_preset,
    test_detect_presets_are_schema_valid,
    test_init_uses_detected_preset,
    test_init_wizard_uses_detected_preset_default,
)


def main() -> int:
    test_report()
    test_doctor_no_secret_values_and_exit()
    test_doctor_fail_loud()
    test_config_path_confined_to_project_root()
    test_config_path_symlink_loop_is_clean_error()
    test_plan_apply_idempotent()
    test_init_profiles_generate_valid_configs()
    test_init_write_and_overwrite_guard()
    test_init_wizard_defaults_and_nontty()
    test_help_command()
    test_init_escapes_test_command()
    test_init_refuses_symlink_destination()
    test_init_rejects_values_the_pipeline_would_reject()
    test_init_rejects_pasted_credential_value()
    test_init_next_steps_carry_custom_config_path()
    test_init_writes_utf8()
    test_init_reports_write_failure_without_traceback()
    test_init_print_keeps_stdout_yaml_only()
    test_init_full_profile_keeps_security_blocking()
    test_init_review_gate_derived_from_profile()
    test_init_quotes_yaml_keyword_scalars()
    test_init_wizard_governance_unrecognized_keeps_profile_default()
    test_init_build_presets_match_schema_and_wizard_validates()
    test_default_token_secret_is_neutral()
    test_detect_build_preset()
    test_detect_presets_are_schema_valid()
    test_init_uses_detected_preset()
    test_init_wizard_uses_detected_preset_default()
    if failures:
        print(f"\n{len(failures)} test failure(s).", file=sys.stderr)
        return 1
    print("\nAll M3 CLI tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
