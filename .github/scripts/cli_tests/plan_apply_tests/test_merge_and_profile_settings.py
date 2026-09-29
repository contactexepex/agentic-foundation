"""V-S15 (settings the generated governance cannot enforce) and V-S16 (profile shortcut semantics)."""
from __future__ import annotations

from typing import Any

from ..harness import check
from .helpers import dogfood_project, rewrite_config, run_cli, snapshot_tree

REQUIRED_CHECK = {"name": "SonarCloud Code Analysis", "app_id": 12526}


def _require_external_check(config: dict[str, Any]) -> None:
    config.setdefault("merge", {})["required_status_checks"] = [REQUIRED_CHECK]


def test_required_status_checks_are_rejected_rather_than_silently_dropped() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, _require_external_check)
        before_run = snapshot_tree(project_root)
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command)
            check(exit_code == 1 and "V-S15" in error_output and "required_status_checks" in error_output,
                  f"{command}: non-empty merge.required_status_checks fails with V-S15 (stderr: {error_output.strip()})")
        check(snapshot_tree(project_root) == before_run, "V-S15: nothing is written when the setting is rejected")


def test_empty_required_status_checks_are_accepted() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, lambda config: config.setdefault("merge", {}).update({"required_status_checks": []}))
        exit_code, _, error_output = run_cli("plan")
        check(exit_code == 0 and "V-S15: merge.required" not in error_output,
              f"plan: an empty required_status_checks list is fine (stderr: {error_output.strip()})")


def test_modules_sonar_warns_that_the_generated_gate_does_not_evaluate_it() -> None:
    with dogfood_project() as project_root:
        for sonar_enabled, expect_warning in ((True, True), (False, False)):
            rewrite_config(project_root, lambda config: config["modules"].update({"sonar": sonar_enabled}))
            exit_code, _, error_output = run_cli("plan")
            has_warning = "V-S15: modules.sonar" in error_output
            check(exit_code == 0 and has_warning is expect_warning,
                  f"plan: modules.sonar={sonar_enabled} warns={expect_warning} (stderr: {error_output.strip()})")


def test_profile_shortcuts_warn_and_full_explains_how_to_proceed() -> None:
    with dogfood_project() as project_root:
        for profile_name in ("minimal", "standard"):
            rewrite_config(project_root, lambda config: config.update({"profile": profile_name, "stages": []}))
            exit_code, _, error_output = run_cli("plan")
            check(exit_code == 0 and f"V-S16: profile '{profile_name}'" in error_output and "implement" in error_output,
                  f"plan: profile {profile_name} warns about the neutral definition (stderr: {error_output.strip()})")
        rewrite_config(project_root, lambda config: config.update({"profile": "custom"}))
        exit_code, _, error_output = run_cli("plan")
        check("V-S16" not in error_output, "plan: profile custom produces no V-S16 warning")
        rewrite_config(project_root, lambda config: config.update({"profile": "full"}))
        exit_code, _, error_output = run_cli("plan")
        check(exit_code == 1 and "'full'" in error_output and "custom" in error_output,
              f"plan: profile full is refused with a pointer to profile custom (stderr: {error_output.strip()})")
