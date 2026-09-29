"""`stagr plan`: succeeds on a valid config and never writes to the target."""
from __future__ import annotations

from ..harness import check
from .helpers import (
    DEFAULT_WORKFLOW_DIRECTORY,
    GENERATED_STAGE_HEADER,
    DOGFOOD_WORKFLOW_NAMES,
    dogfood_project,
    line_mentioning,
    run_cli,
    snapshot_tree,
)


def test_plan_valid_config_exits_zero_and_lists_every_artifact() -> None:
    with dogfood_project():
        exit_code, plan_output, plan_errors = run_cli("plan")
        check(exit_code == 0, f"plan: valid dogfood config exits 0 (stderr: {plan_errors.strip()})")
        for workflow_name in DOGFOOD_WORKFLOW_NAMES:
            check("+ new" in line_mentioning(plan_output, workflow_name), f"plan: lists {workflow_name} as new")
        check("bytes" in plan_output and "sha256:" in plan_output, "plan: shows size and hash per artifact")
        check("stage-implement-codex.yml" not in plan_output,
              "plan: the disabled stage implement-codex has no artifact")
        check("nothing was written" in plan_output, "plan: says it is a dry run")


def test_plan_writes_nothing_when_target_directory_does_not_exist() -> None:
    with dogfood_project() as project_root:
        before_plan = snapshot_tree(project_root)
        exit_code, _, _ = run_cli("plan")
        check(exit_code == 0, "plan: default target that does not exist exits 0")
        check(not (project_root / ".github").exists(), "plan: does not create .github/")
        check(snapshot_tree(project_root) == before_plan, "plan: project tree (paths, mtimes, sizes) unchanged")

        missing_target = project_root / "no" / "such" / "dir"
        exit_code, _, _ = run_cli("plan", "--out", str(missing_target))
        check(exit_code == 0 and not (project_root / "no").exists(),
              "plan: a missing --out directory is not created")


def test_plan_writes_nothing_into_an_existing_target_directory() -> None:
    with dogfood_project() as project_root:
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "ci.yml").write_text("name: hand written\n", encoding="utf-8")
        (workflow_directory / "stage-review.yml").write_text("name: outdated\n", encoding="utf-8")
        before_plan = snapshot_tree(project_root)

        exit_code, plan_output, _ = run_cli("plan", "--diff")
        check(exit_code == 0, "plan: exits 0 against an existing target")
        check(snapshot_tree(project_root) == before_plan,
              "plan: existing target directory (files, mtimes, sizes, listing) unchanged")
        check("~ changed" in plan_output and "stage-review.yml" in plan_output,
              "plan: an out-of-date workflow is reported as changed")
        check("-name:outdated" in plan_output.replace(" ", "") and "+name:" in plan_output.replace(" ", ""),
              "plan --diff: prints the unified diff")


def test_plan_reports_stale_stage_workflows_but_not_hand_written_ones() -> None:
    with dogfood_project() as project_root:
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "ci.yml").write_text("name: hand written\n", encoding="utf-8")
        (workflow_directory / "stage-removed-stage.yml").write_text(GENERATED_STAGE_HEADER, encoding="utf-8")
        (workflow_directory / "stage-deploy.yml").write_text("name: hand written deploy\n", encoding="utf-8")

        _, plan_output, _ = run_cli("plan")
        check("? stage-removed-stage.yml" in plan_output, "plan: a stage workflow no longer rendered is listed as stale")
        check("ci.yml" not in plan_output, "plan: hand-written workflows are never mentioned")
        check("stage-deploy.yml" not in plan_output,
              "plan: a hand-written stage-*.yml is not mistaken for a generated stage workflow")


def test_plan_after_apply_reports_everything_unchanged() -> None:
    with dogfood_project():
        run_cli("apply")
        exit_code, plan_output, _ = run_cli("plan")
        check(exit_code == 0 and plan_output.count("= unchanged") == len(DOGFOOD_WORKFLOW_NAMES)
              and "+ new" not in plan_output and "~ changed" not in plan_output,
              "plan: right after apply every artifact is unchanged")


def test_placeholder_invocation_stages_are_warned_about_by_plan_and_apply() -> None:
    """Review finding: an accepted-but-not-yet-rendered invocation kind must never be silent."""
    with dogfood_project():
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command)
            check(exit_code == 0 and "implement-claude" in error_output and "CI_COMPONENT" in error_output
                  and "placeholder" in error_output,
                  f"{command}: warns that the CI_COMPONENT implement stage is only a placeholder (stderr: "
                  f"{error_output.strip()})")
            check("stage 'review'" not in error_output and "stage 'security'" not in error_output,
                  f"{command}: PR_COMMENT review stages are functional and produce no placeholder warning")
