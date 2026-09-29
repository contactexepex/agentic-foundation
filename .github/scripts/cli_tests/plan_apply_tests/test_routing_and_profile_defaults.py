"""Review findings: fast-path routing defaults/restrictions, AUTO merge visibility, and the default profile."""
from __future__ import annotations

import json
from typing import Any

import yaml

from ..harness import check
from .helpers import DEFAULT_WORKFLOW_DIRECTORY, dogfood_project, rewrite_config, run_cli, snapshot_tree

ENABLED_STAGE_IDS = ["implement-claude", "review", "security"]


def _enable_fast_path(**fast_path_settings: Any):
    def mutate_config(config: dict[str, Any]) -> None:
        config["routing"] = {"fast_path": {"globs": ["**/*.md"], **fast_path_settings}}

    return mutate_config


def _stage_routing_document(project_root, stage_id: str) -> dict[str, Any]:
    """The `routing` object inside the per-stage JSON config that the generated workflow carries."""
    workflow_text = (project_root / DEFAULT_WORKFLOW_DIRECTORY / f"stage-{stage_id}.yml").read_text(encoding="utf-8")
    for line in workflow_text.splitlines():
        stripped_line = line.strip()
        if stripped_line.startswith("{") and '"routing"' in stripped_line:
            return json.loads(stripped_line)["routing"]
    raise AssertionError(f"no stage config JSON found in stage-{stage_id}.yml")


def test_enabled_fast_path_without_stage_map_runs_every_stage_on_the_normal_route() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, _enable_fast_path())
        exit_code, _, error_output = run_cli("apply")
        check(exit_code == 0, f"apply: a fast path without stages.normal is accepted (stderr: {error_output.strip()})")
        routing_document = _stage_routing_document(project_root, "review")
        check(routing_document["fastStageIds"] == [], "fast route stays empty: glob/size gate, no model review")
        check(sorted(routing_document["normalStageIds"]) == sorted(ENABLED_STAGE_IDS),
              f"NORMAL route defaults to every enabled stage, not none ({routing_document['normalStageIds']})")


def test_an_explicit_normal_route_list_is_kept_exactly() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, _enable_fast_path(stages={"fast": [], "normal": ["review", "security"]}))
        exit_code, _, _ = run_cli("apply")
        routing_document = _stage_routing_document(project_root, "review")
        check(exit_code == 0 and routing_document["normalStageIds"] == ["review", "security"],
              f"an operator-listed normal route is not widened ({routing_document['normalStageIds']})")


def test_fast_path_restrictions_that_cannot_be_enforced_are_rejected() -> None:
    restriction_cases = {"max_files": 20, "max_lines": 200, "exclude": ["docs/**"]}
    with dogfood_project() as project_root:
        for setting_name, setting_value in restriction_cases.items():
            rewrite_config(project_root, _enable_fast_path(**{setting_name: setting_value}))
            before_run = snapshot_tree(project_root)
            for command in ("plan", "apply"):
                exit_code, _, error_output = run_cli(command)
                check(exit_code == 1 and "V-S17" in error_output and setting_name in error_output,
                      f"{command}: fast_path.{setting_name} is rejected with V-S17 (stderr: {error_output.strip()})")
            check(snapshot_tree(project_root) == before_run, f"V-S17 ({setting_name}): nothing is written")
        rewrite_config(project_root, _enable_fast_path(enabled=False, max_files=20, exclude=["docs/**"]))
        exit_code, _, error_output = run_cli("plan")
        check(exit_code == 0 and "V-S17" not in error_output,
              f"plan: the same settings on a disabled fast path are dormant, not an error (stderr: {error_output.strip()})")


def test_auto_merge_warns_that_the_generated_governance_does_not_merge() -> None:
    with dogfood_project() as project_root:
        for auto_merge_enabled in (True, False):
            rewrite_config(project_root, lambda config: config["modules"].update({"auto_merge": auto_merge_enabled}))
            exit_code, _, error_output = run_cli("plan")
            has_warning = "V-S15: modules.auto_merge" in error_output and "never merges" in error_output
            check(exit_code == 0 and has_warning is auto_merge_enabled,
                  f"plan: modules.auto_merge={auto_merge_enabled} warns={auto_merge_enabled} (stderr: {error_output.strip()})")


def test_a_config_without_profile_gets_the_schema_default_standard() -> None:
    with dogfood_project() as project_root:
        def drop_profile_and_stages(config: dict[str, Any]) -> None:
            config.pop("profile", None)
            config.pop("stages", None)
            config["modules"].update({"auto_merge": False})

        rewrite_config(project_root, drop_profile_and_stages)
        exit_code, plan_output, error_output = run_cli("plan")
        check(exit_code == 0 and "stage-review.yml" in plan_output and "stage-security.yml" in plan_output,
              f"plan: omitted profile expands to standard (review + security) (stdout: {plan_output.strip()})")
        check("V-S16: profile 'standard'" in error_output, "plan: the implicit standard profile carries the V-S16 note")
        exit_code, _, _ = run_cli("apply")
        written = sorted(path.name for path in (project_root / DEFAULT_WORKFLOW_DIRECTORY).iterdir())
        check(exit_code == 0 and "stage-review.yml" in written and "stage-security.yml" in written,
              f"apply: writes the standard stages for a config with no profile ({written})")
