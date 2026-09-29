"""`stagr apply`: writes the expected workflows, idempotently, without touching unrelated files."""
from __future__ import annotations

import subprocess
import sys

import yaml

from ..harness import REPO_ROOT, check
from .helpers import (
    DEFAULT_WORKFLOW_DIRECTORY,
    DOGFOOD_ENABLED_STAGE_IDS,
    DOGFOOD_WORKFLOW_NAMES,
    dogfood_project,
    hashes_by_name,
    run_cli,
    snapshot_tree,
)


def test_apply_writes_expected_workflows_as_valid_yaml() -> None:
    with dogfood_project() as project_root:
        exit_code, apply_output, apply_errors = run_cli("apply")
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        check(exit_code == 0, f"apply: dogfood config exits 0 (stderr: {apply_errors.strip()})")
        written_names = sorted(path.name for path in workflow_directory.iterdir())
        check(written_names == sorted(DOGFOOD_WORKFLOW_NAMES),
              f"apply: writes exactly stage-<id>.yml per enabled stage, routing.yml, governance.yml ({written_names})")
        for workflow_name in DOGFOOD_WORKFLOW_NAMES:
            parsed_workflow = yaml.safe_load((workflow_directory / workflow_name).read_text(encoding="utf-8"))
            check(isinstance(parsed_workflow, dict) and isinstance(parsed_workflow.get("jobs"), dict)
                  and parsed_workflow["jobs"],
                  f"apply: {workflow_name} is valid YAML with a non-empty jobs mapping")
        check(f"{len(DOGFOOD_WORKFLOW_NAMES)} file(s) written" in apply_output, "apply: prints a summary")
        for stage_id in DOGFOOD_ENABLED_STAGE_IDS:
            stage_workflow = yaml.safe_load(
                (workflow_directory / f"stage-{stage_id}.yml").read_text(encoding="utf-8"))
            check(f"stagr/stage/{stage_id}" in (workflow_directory / f"stage-{stage_id}.yml").read_text(encoding="utf-8")
                  and "name" in stage_workflow,
                  f"apply: stage-{stage_id}.yml carries its own Check Run name")


def test_apply_wires_the_publisher_app_id_into_the_workflows() -> None:
    with dogfood_project() as project_root:
        run_cli("apply")
        governance_text = (project_root / DEFAULT_WORKFLOW_DIRECTORY / "governance.yml").read_text(encoding="utf-8")
        check("5125793" in governance_text, "apply: platform.publisher.app_id reaches the governance artifact")
        check("STAGR_APP_PRIVATE_KEY" in governance_text,
              "apply: the default private_key_secret NAME reaches the artifact")


def test_apply_twice_is_idempotent() -> None:
    with dogfood_project() as project_root:
        run_cli("apply")
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        hashes_after_first_apply = hashes_by_name(workflow_directory)
        snapshot_after_first_apply = snapshot_tree(project_root)

        exit_code, second_output, _ = run_cli("apply")
        check(exit_code == 0, "apply: second run exits 0")
        check(hashes_by_name(workflow_directory) == hashes_after_first_apply, "apply: second run leaves identical content")
        check(snapshot_tree(project_root) == snapshot_after_first_apply,
              "apply: second run rewrites nothing (mtimes unchanged, no temp files left)")
        check("0 file(s) written" in second_output, "apply: second run reports 0 files written")


def test_apply_repairs_a_changed_workflow_and_only_that_one() -> None:
    with dogfood_project() as project_root:
        run_cli("apply")
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        expected_hashes = hashes_by_name(workflow_directory)
        (workflow_directory / "routing.yml").write_text("name: tampered\n", encoding="utf-8")
        untouched_before = {
            name: (workflow_directory / name).stat().st_mtime_ns for name in DOGFOOD_WORKFLOW_NAMES if name != "routing.yml"
        }

        _, apply_output, _ = run_cli("apply")
        check(hashes_by_name(workflow_directory) == expected_hashes, "apply: restores the changed workflow")
        check("1 file(s) written" in apply_output, "apply: reports exactly one file written")
        check(untouched_before == {
            name: (workflow_directory / name).stat().st_mtime_ns for name in untouched_before
        }, "apply: unchanged workflows keep their mtime")


def test_apply_never_touches_unrelated_files_and_prunes_only_stale_stage_workflows() -> None:
    with dogfood_project() as project_root:
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "ci.yml").write_text("name: hand written ci\n", encoding="utf-8")
        (workflow_directory / "stage-removed-stage.yml").write_text("name: stale stage\n", encoding="utf-8")
        (project_root / "README.md").write_text("unrelated\n", encoding="utf-8")

        _, apply_output, _ = run_cli("apply")
        check((workflow_directory / "ci.yml").read_text(encoding="utf-8") == "name: hand written ci\n",
              "apply: a hand-written workflow is not modified")
        check((workflow_directory / "stage-removed-stage.yml").exists() and "kept" in apply_output,
              "apply: a stale stage workflow is kept and reported without --prune")

        _, prune_output, _ = run_cli("apply", "--prune")
        check(not (workflow_directory / "stage-removed-stage.yml").exists() and "pruned" in prune_output,
              "apply --prune: removes the stale stage workflow")
        check((workflow_directory / "ci.yml").exists() and (project_root / "README.md").exists(),
              "apply --prune: hand-written and unrelated files survive")
        check(sorted(path.name for path in workflow_directory.iterdir()) == sorted(DOGFOOD_WORKFLOW_NAMES + ("ci.yml",)),
              "apply --prune: directory holds exactly the rendered workflows plus the hand-written one")


def test_apply_honours_a_custom_out_directory() -> None:
    with dogfood_project() as project_root:
        exit_code, _, _ = run_cli("apply", "--out", "build/workflows")
        check(exit_code == 0 and sorted(path.name for path in (project_root / "build" / "workflows").iterdir())
              == sorted(DOGFOOD_WORKFLOW_NAMES), "apply --out: writes the workflows into the given directory")
        check(not (project_root / ".github").exists(), "apply --out: leaves the default directory alone")


def test_apply_into_temp_dir_then_validate_config_passes() -> None:
    with dogfood_project() as project_root:
        exit_code, _, apply_errors = run_cli("apply", "--out", str(project_root / "out"))
        check(exit_code == 0, f"apply: dogfood config into a temp dir exits 0 ({apply_errors.strip()})")
    validation = subprocess.run(
        [sys.executable, str(REPO_ROOT / ".github" / "scripts" / "validate_config.py")],
        capture_output=True, text=True, cwd=REPO_ROOT, check=False,
    )
    check(validation.returncode == 0, f"validate_config.py passes after apply ({validation.stderr.strip()[:200]})")
