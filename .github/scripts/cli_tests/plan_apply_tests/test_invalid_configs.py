"""Invalid configs: `plan` and `apply` both exit 1 with a clear message and write nothing."""
from __future__ import annotations

import copy
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from ..harness import check
from .helpers import DEFAULT_WORKFLOW_DIRECTORY, dogfood_project, rewrite_config, run_cli, snapshot_tree

PIPELINE_SECRET_LOOKING_VALUE = "sk-abcdef1234567890abcdef"


def _set_version(version: Any) -> Callable[[dict[str, Any]], None]:
    return lambda config: config.__setitem__("version", version)


def _duplicate_stage_id(config: dict[str, Any]) -> None:
    config["stages"].append(copy.deepcopy(config["stages"][2]))


def _unknown_backend(config: dict[str, Any]) -> None:
    config["stages"][0]["backend"] = {"name": "openhands"}


def _dependency_cycle(config: dict[str, Any]) -> None:
    config["stages"][2]["depends_on"] = ["security"]
    config["stages"][3]["depends_on"] = ["review"]


def _unknown_dependency(config: dict[str, Any]) -> None:
    config["stages"][2]["depends_on"] = ["ghost-stage"]


def _remove_publisher(config: dict[str, Any]) -> None:
    del config["platform"]["publisher"]


def _invalid_app_id(config: dict[str, Any]) -> None:
    config["platform"]["publisher"]["app_id"] = "not-a-number"


def _pasted_key_material(config: dict[str, Any]) -> None:
    config["platform"]["publisher"]["private_key_secret"] = PIPELINE_SECRET_LOOKING_VALUE


def _unknown_stage_type(config: dict[str, Any]) -> None:
    config["stages"][2]["type"] = "not-a-real-type"


def _unsupported_platform(config: dict[str, Any]) -> None:
    config["platform"]["type"] = "gitlab"


def _auto_merge_without_blocking_stage(config: dict[str, Any]) -> None:
    # Only the implementer stays enabled, and an implementer never blocks merge.
    for stage in config["stages"][2:]:
        stage["enabled"] = False


def _unreachable_role_name(config: dict[str, Any]) -> None:
    config["platform"]["trusted_roles"] = ["superuser"]


def _advisory_codex_review(config: dict[str, Any]) -> None:
    config["stages"][2]["gate"] = "advisory"


def _route_not_dependency_closed(config: dict[str, Any]) -> None:
    config["stages"][3]["depends_on"] = ["review"]
    config["routing"] = {
        "fast_path": {
            "enabled": True,
            "globs": ["docs/**"],
            "stages": {"fast": ["security"], "normal": ["review", "security"]},
        }
    }


INVALID_CONFIG_CASES: list[tuple[str, Callable[[dict[str, Any]], None], str]] = [
    ("unsupported version 1", _set_version(1), "V-S02"),
    ("version given as a string", _set_version("2"), "V-S02"),
    ("duplicate stage ids", _duplicate_stage_id, "review"),
    ("unknown backend", _unknown_backend, "V-S07"),
    ("dependency cycle", _dependency_cycle, "V-S04"),
    ("dependency on an unknown stage", _unknown_dependency, "V-S05"),
    ("missing publisher block", _remove_publisher, "platform.publisher"),
    ("invalid publisher app_id", _invalid_app_id, "app_id"),
    ("schema violation (unknown stage type)", _unknown_stage_type, "V-S01"),
    ("platform without a renderer", _unsupported_platform, "gitlab"),
    ("auto_merge with no blocking stage", _auto_merge_without_blocking_stage, "V-S10"),
    ("unrecognised trusted role", _unreachable_role_name, "superuser"),
    ("Codex review stage the backend cannot render", _advisory_codex_review, "V-S08"),
    ("route set not dependency-closed", _route_not_dependency_closed, "V-S09"),
]


def _assert_plan_and_apply_reject(case_name: str, expected_fragment: str, project_root: Path) -> None:
    before_run = snapshot_tree(project_root)
    rejection_messages: list[str] = []
    for command in ("plan", "apply"):
        exit_code, command_output, command_errors = run_cli(command)
        check(exit_code == 1, f"{command}: {case_name} exits 1")
        check(expected_fragment in command_errors,
              f"{command}: {case_name} error mentions '{expected_fragment}' (got: {command_errors.strip()[:160]})")
        check(command_errors.startswith(f"{command}: ") and "Traceback" not in command_errors,
              f"{command}: {case_name} is a one-line error, not a traceback")
        check("would render" not in command_output and "file(s) written" not in command_output,
              f"{command}: {case_name} prints no success summary")
        rejection_messages.append(command_errors.split(": ", 1)[1])
    check(rejection_messages[0] == rejection_messages[1], f"plan and apply give the same error for {case_name}")
    check(snapshot_tree(project_root) == before_run and not (project_root / ".github").exists(),
          f"{case_name}: nothing is written by plan or apply")


def test_invalid_configs_are_rejected_identically_by_plan_and_apply() -> None:
    for case_name, mutate_config, expected_fragment in INVALID_CONFIG_CASES:
        with dogfood_project() as project_root:
            rewrite_config(project_root, mutate_config)
            _assert_plan_and_apply_reject(case_name, expected_fragment, project_root)


def test_missing_skill_file_is_rejected() -> None:
    with dogfood_project() as project_root:
        shutil.rmtree(project_root / ".agentic" / "skills" / "code-review")
        _assert_plan_and_apply_reject("missing skill file", "V-S06", project_root)


def test_missing_and_malformed_config_files_are_rejected() -> None:
    with dogfood_project() as project_root:
        exit_code, _, error_output = run_cli("plan", "--config", ".agentic/absent.yml")
        check(exit_code == 1 and "not found" in error_output, "plan: a missing config file exits 1 with 'not found'")
        (project_root / ".agentic" / "broken.yml").write_text("version: [unclosed\n", encoding="utf-8")
        exit_code, _, error_output = run_cli("apply", "--config", ".agentic/broken.yml")
        check(exit_code == 1 and "not valid YAML" in error_output, "apply: malformed YAML exits 1 with a clear message")
        (project_root / ".agentic" / "list.yml").write_text("- just\n- a list\n", encoding="utf-8")
        exit_code, _, error_output = run_cli("plan", "--config", ".agentic/list.yml")
        check(exit_code == 1 and "V-S02" in error_output, "plan: a non-mapping document is a version error")


def test_config_outside_the_project_root_is_rejected() -> None:
    with dogfood_project() as project_root, tempfile.TemporaryDirectory() as outside_directory:
        outside_config = Path(outside_directory) / "config.yml"
        shutil.copyfile(project_root / ".agentic" / "config.yml", outside_config)
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command, "--config", str(outside_config))
            check(exit_code == 1 and "outside the project root" in error_output,
                  f"{command}: a --config outside the project root is refused")
        check(not (project_root / DEFAULT_WORKFLOW_DIRECTORY).exists(), "outside config: nothing written")


def test_pasted_key_material_is_never_echoed() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, _pasted_key_material)
        for command in ("plan", "apply"):
            exit_code, command_output, error_output = run_cli(command)
            check(exit_code == 1, f"{command}: a secret value in private_key_secret exits 1")
            check(PIPELINE_SECRET_LOOKING_VALUE not in command_output + error_output,
                  f"{command}: the pasted value is not echoed to stdout or stderr")


def test_dormant_routing_is_a_warning_not_an_error() -> None:
    with dogfood_project() as project_root:
        rewrite_config(project_root, lambda config: config["routing"]["fast_path"].update({"globs": ["docs/**"]}))
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command)
            check(exit_code == 0 and "V-S11" in error_output and "dormant" in error_output,
                  f"{command}: V-S11 dormant routing warns on stderr and still exits 0")
