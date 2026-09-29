"""`stagr init` writes blocking Codex stages, so `init -> plan -> apply` works for every profile.

Review finding on the plan/apply PR: `init --profile standard` wrote an advisory security stage, which
the neutral pipeline rejects. These tests pin the fix: generated Codex stages are blocking, the file
explains the two gate categories, and it shows (commented) the publisher block and the build/test
stages that cannot run yet.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from .harness import _project_dir, check
from .plan_apply_tests.helpers import DEFAULT_WORKFLOW_DIRECTORY, run_cli

TEST_ONLY_PUBLISHER_APP_ID = 424242
DEFAULT_CONFIG_FILE = Path(".agentic") / "config.yml"

# Stage workflows `apply` must write for each profile (the implement stage is a placeholder today).
EXPECTED_STAGE_IDS_BY_PROFILE = {
    "minimal": ("implement", "review"),
    "standard": ("implement", "review", "security"),
    "full": ("implement", "review", "security"),
    "custom": (),
}
CODEX_STAGE_TYPES = ("review", "security")


def init_profile_in_current_project(profile: str) -> str:
    """Run `stagr init --profile <profile>` in the current project and return the config text."""
    exit_code, _, error_output = run_cli("init", "--profile", profile)
    check(exit_code == 0, f"init --profile {profile}: exits 0 (stderr: {error_output.strip()})")
    return DEFAULT_CONFIG_FILE.read_text(encoding="utf-8")


def uncomment_publisher_block(config_text: str) -> str:
    """Do what the generated comments tell an operator to do: uncomment the block, set an App ID."""
    config_lines = config_text.splitlines(keepends=True)
    block_start = next(index for index, line in enumerate(config_lines) if line.startswith("  # publisher:"))
    config_lines[block_start] = "  publisher:\n"
    config_lines[block_start + 1] = f"    app_id: {TEST_ONLY_PUBLISHER_APP_ID}\n"
    config_lines[block_start + 2] = "    private_key_secret: STAGR_APP_PRIVATE_KEY\n"
    return "".join(config_lines)


def active_stages(config_text: str) -> list[dict[str, Any]]:
    return (yaml.safe_load(config_text) or {}).get("stages") or []


def is_comment_line(line: str) -> bool:
    return line.lstrip().startswith("#")


def test_every_profile_goes_from_init_to_plan_to_apply() -> None:
    for profile, expected_stage_ids in EXPECTED_STAGE_IDS_BY_PROFILE.items():
        with _project_dir() as project_root:
            generated_text = init_profile_in_current_project(profile)
            DEFAULT_CONFIG_FILE.write_text(uncomment_publisher_block(generated_text), encoding="utf-8")
            publisher = yaml.safe_load(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8"))["platform"]["publisher"]
            check(publisher["app_id"] == TEST_ONLY_PUBLISHER_APP_ID,
                  f"init {profile}: the commented publisher block becomes valid once uncommented")

            plan_exit_code, plan_output, plan_errors = run_cli("plan")
            check(plan_exit_code == 0, f"init {profile} -> plan exits 0 (stderr: {plan_errors.strip()})")
            apply_exit_code, _, apply_errors = run_cli("apply")
            check(apply_exit_code == 0, f"init {profile} -> apply exits 0 (stderr: {apply_errors.strip()})")

            workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
            written_stage_ids = sorted(
                path.name[len("stage-"):-len(".yml")] for path in workflow_directory.glob("stage-*.yml"))
            check(written_stage_ids == sorted(expected_stage_ids),
                  f"init {profile} -> apply writes exactly the stage workflows {sorted(expected_stage_ids)}")

            plan_after_apply_output = run_cli("plan")[1]
            check("+ new" not in plan_after_apply_output and "~ changed" not in plan_after_apply_output,
                  f"init {profile} -> apply -> plan reports everything unchanged")


def test_plan_without_a_publisher_app_id_tells_the_operator_what_to_set() -> None:
    with _project_dir():
        init_profile_in_current_project("standard")
        exit_code, _, error_output = run_cli("plan")
        check(exit_code == 1 and "publisher" in error_output and "app_id" in error_output,
              f"init -> plan before setting the App ID fails naming platform.publisher.app_id "
              f"(stderr: {error_output.strip()})")


def test_generated_codex_stages_are_explicitly_blocking_in_every_profile() -> None:
    for profile, expected_stage_ids in EXPECTED_STAGE_IDS_BY_PROFILE.items():
        with _project_dir():
            stages = active_stages(init_profile_in_current_project(profile))
            check([stage["id"] for stage in stages] == list(expected_stage_ids),
                  f"init {profile}: active stages are exactly {list(expected_stage_ids)}")
            codex_stages = [stage for stage in stages if stage["type"] in CODEX_STAGE_TYPES]
            check(all(stage.get("gate") == "blocking" for stage in codex_stages),
                  f"init {profile}: every Codex review/security stage sets gate: blocking explicitly")
            check(not any(stage.get("gate") == "advisory" for stage in stages),
                  f"init {profile}: no generated stage is advisory")


def test_init_gates_match_the_neutral_profile_definitions() -> None:
    from stagr.core.normalize import _PROFILE_STAGE_DEFAULTS
    for profile in ("minimal", "standard"):
        with _project_dir():
            generated_by_id = {stage["id"]: stage for stage in active_stages(init_profile_in_current_project(profile))}
        for neutral_stage in _PROFILE_STAGE_DEFAULTS[profile]:
            generated_stage = generated_by_id[neutral_stage["id"]]
            for field in ("type", "provider", "skill", "gate"):
                check(generated_stage[field] == neutral_stage[field],
                      f"init {profile}: stage '{neutral_stage['id']}' {field} matches the neutral profile "
                      f"({neutral_stage[field]})")


def test_security_review_waits_for_the_code_review_in_every_profile_that_has_both() -> None:
    """Review finding: the two Codex reviews must never start concurrently (AGENTS.md review order)."""
    for profile in ("standard", "full"):
        with _project_dir() as project_root:
            generated_text = init_profile_in_current_project(profile)
            stages_by_id = {stage["id"]: stage for stage in active_stages(generated_text)}
            check(stages_by_id["security"].get("depends_on") == ["review"],
                  f"init {profile}: the security stage depends on the code review")
            check("depends_on" not in stages_by_id["review"], f"init {profile}: the code review depends on nothing")
            DEFAULT_CONFIG_FILE.write_text(uncomment_publisher_block(generated_text), encoding="utf-8")
            exit_code, _, error_output = run_cli("apply", "--out", "out")
            security_workflow = (project_root / "out" / "stage-security.yml").read_text(encoding="utf-8")
            check(exit_code == 0 and '"dependencies":[{' in security_workflow.replace(" ", ""),
                  f"init {profile}: the applied security workflow waits on an upstream stage (stderr: {error_output.strip()})")


def test_generated_file_explains_gates_and_keeps_unavailable_stages_commented() -> None:
    for profile in EXPECTED_STAGE_IDS_BY_PROFILE:
        with _project_dir():
            generated_text = init_profile_in_current_project(profile)
        parsed_config = yaml.safe_load(generated_text)
        check("advisory - posts comments; never stops the pull request from merging" in generated_text
              and "blocking - the stage must complete" in generated_text
              and "resolved, before the pull request can merge" in generated_text,
              f"init {profile}: the file explains advisory vs blocking in plain language")
        check("NOT AVAILABLE YET" in generated_text and "build/test backend" in generated_text
              and "default blocking stages" in generated_text,
              f"init {profile}: build/test are marked not available yet (need a backend, future defaults)")
        check("Optional stages" in generated_text and "SAST/DAST" in generated_text,
              f"init {profile}: the file explains how to add optional stages and pick a gate")
        for unavailable_stage_id in ("build", "test"):
            example_lines = [line for line in generated_text.splitlines() if f"id: {unavailable_stage_id}" in line]
            check(len(example_lines) == 1 and all(is_comment_line(line) for line in example_lines),
                  f"init {profile}: the '{unavailable_stage_id}' stage example is present and commented out")
            check(unavailable_stage_id not in [stage["id"] for stage in parsed_config.get("stages") or []],
                  f"init {profile}: '{unavailable_stage_id}' is not an active stage")
        check("publisher" not in parsed_config["platform"],
              f"init {profile}: platform.publisher is commented out, not active")
        check("# publisher:" in generated_text and "app_id" in generated_text
              and "Create the Stagr GitHub App" in generated_text,
              f"init {profile}: the commented publisher block tells the operator to create the App")
        check(re.search(r"app_id:\s*[0-9]", generated_text) is None
              and "BEGIN" not in generated_text and "PRIVATE KEY" not in generated_text,
              f"init {profile}: no invented App ID and no key material in the file")


def test_uncommenting_the_build_and_test_examples_only_renders_placeholders() -> None:
    """The 'not available yet' comment says these would render only a placeholder; pin that claim."""
    example_blocks = {
        "build": ("  # - id: build\n  #   type: custom\n  #   gate: blocking\n",
                  "  - id: build\n    type: custom\n    gate: blocking\n"),
        "test": ("  # - id: test\n  #   type: test\n  #   gate: blocking\n",
                 "  - id: test\n    type: test\n    gate: blocking\n"),
        "integration-test": ("  # - id: integration-test\n  #   type: custom\n  #   gate: blocking\n",
                             "  - id: integration-test\n    type: custom\n    gate: blocking\n"),
    }
    for stage_id, (commented_block, active_block) in example_blocks.items():
        with _project_dir():
            generated_text = init_profile_in_current_project("full" if stage_id == "integration-test" else "standard")
            check(commented_block in generated_text, f"init: the commented '{stage_id}' example has the expected shape")
            DEFAULT_CONFIG_FILE.write_text(
                uncomment_publisher_block(generated_text).replace(commented_block, active_block), encoding="utf-8")
            exit_code, _, error_output = run_cli("plan")
            check(exit_code == 0 and f"stage '{stage_id}'" in error_output and "placeholder" in error_output,
                  f"plan: an uncommented '{stage_id}' example renders only a warned placeholder "
                  f"(stderr: {error_output.strip()})")


def test_wizard_asks_no_governance_question_and_never_offers_advisory() -> None:
    from stagr import scaffold
    for profile in EXPECTED_STAGE_IDS_BY_PROFILE:
        prompts_shown: list[str] = []
        answers_given = iter([profile, "", "", "", "", ""])  # profile, branch, model, token, preset, test

        def read_answer(prompt: str) -> str:
            prompts_shown.append(prompt)
            return next(answers_given)  # a seventh question would raise StopIteration

        wizard_lines: list[str] = []
        choices = scaffold.run_wizard(read_input=read_answer, write_line=wizard_lines.append)
        wizard_text = "\n".join(wizard_lines + prompts_shown).lower()
        check(len(prompts_shown) == 6, f"wizard {profile}: asks exactly the six non-governance questions")
        check("advisory" not in wizard_text and "blocking" not in wizard_text and "governance" not in wizard_text,
              f"wizard {profile}: no question offers advisory or blocking for the reviews")
        check("security_blocking" not in choices, f"wizard {profile}: no security gate choice is collected")
        if profile in ("minimal", "standard", "full"):
            gates = [stage["gate"] for stage in active_stages(scaffold.generate(choices))
                     if stage["type"] in CODEX_STAGE_TYPES]
            check(gates and set(gates) == {"blocking"}, f"wizard {profile}: generated Codex stages are blocking")


def test_init_prints_the_next_steps_in_order() -> None:
    with _project_dir():
        exit_code, init_output, _ = run_cli("init", "--profile", "standard")
        publisher_step = init_output.find("platform.publisher")
        plan_step = init_output.find("stagr plan")
        apply_step = init_output.find("stagr apply")
        check(exit_code == 0 and "app_id" in init_output and 0 <= publisher_step < plan_step < apply_step,
              f"init: next steps are set platform.publisher.app_id, then stagr plan, then stagr apply "
              f"(stdout: {init_output.strip()})")


def test_rerunning_init_never_overwrites_an_edited_config_without_force() -> None:
    with _project_dir():
        edited_text = uncomment_publisher_block(init_profile_in_current_project("standard"))
        DEFAULT_CONFIG_FILE.write_text(edited_text, encoding="utf-8")

        exit_code, _, error_output = run_cli("init", "--profile", "standard")
        check(exit_code == 1 and "already exists" in error_output,
              "init: a second run refuses to overwrite and says the file exists")
        check(DEFAULT_CONFIG_FILE.read_text(encoding="utf-8") == edited_text,
              "init: the operator's edited config (with the App ID) is untouched by the refused re-run")

        forced_exit_code, _, _ = run_cli("init", "--profile", "standard", "--force")
        check(forced_exit_code == 0 and "publisher" not in yaml.safe_load(DEFAULT_CONFIG_FILE.read_text("utf-8"))["platform"],
              "init --force: regenerates the file on request")


INIT_BLOCKING_DEFAULT_TESTS = [
    test_every_profile_goes_from_init_to_plan_to_apply,
    test_plan_without_a_publisher_app_id_tells_the_operator_what_to_set,
    test_generated_codex_stages_are_explicitly_blocking_in_every_profile,
    test_init_gates_match_the_neutral_profile_definitions,
    test_security_review_waits_for_the_code_review_in_every_profile_that_has_both,
    test_generated_file_explains_gates_and_keeps_unavailable_stages_commented,
    test_uncommenting_the_build_and_test_examples_only_renders_placeholders,
    test_wizard_asks_no_governance_question_and_never_offers_advisory,
    test_init_prints_the_next_steps_in_order,
    test_rerunning_init_never_overwrites_an_edited_config_without_force,
]
