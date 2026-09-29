"""plan and apply share one pipeline: same hashes, same StageResultSpecs, all-or-nothing writes."""
from __future__ import annotations

import dataclasses
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

import yaml

from stagr.cli import plan_apply
from stagr.core import platform_targets
from stagr.core.enums import StageKind
from stagr.core.pipeline import normalize_config
from stagr.platforms.github.renderer import GitHubPlatformRenderer

from ..harness import check
from .helpers import (
    DEFAULT_WORKFLOW_DIRECTORY,
    DOGFOOD_WORKFLOW_NAMES,
    dogfood_project,
    hashes_by_name,
    hashes_listed_in_plan_output,
    read_config,
    rewrite_config,
    run_cli,
    snapshot_tree,
)


def test_plan_hashes_equal_the_files_apply_writes() -> None:
    with dogfood_project() as project_root:
        _, plan_output, _ = run_cli("plan")
        listed_hashes = hashes_listed_in_plan_output(plan_output)
        run_cli("apply")
        written_hashes = hashes_by_name(project_root / DEFAULT_WORKFLOW_DIRECTORY)
        check(sorted(listed_hashes) == sorted(DOGFOOD_WORKFLOW_NAMES), "plan: lists a hash for every artifact")
        check(listed_hashes == written_hashes, "plan: printed sha256 values equal the hashes of the files apply writes")
        for workflow_name, size_text in (
            (line.split()[2], line.split()[3]) for line in plan_output.splitlines() if "sha256:" in line
        ):
            written_size = (project_root / DEFAULT_WORKFLOW_DIRECTORY / workflow_name).stat().st_size
            check(size_text == str(written_size), f"plan: printed size for {workflow_name} equals the written size")


def test_plan_and_apply_produce_identical_stage_result_specs() -> None:
    recorded_results = {}
    original_pipeline = plan_apply.run_render_pipeline

    def recording_pipeline(config_path, project_root, platform_override=None):
        pipeline_result = original_pipeline(config_path, project_root, platform_override)
        recorded_results[len(recorded_results)] = pipeline_result
        return pipeline_result

    plan_apply.run_render_pipeline = recording_pipeline
    try:
        with dogfood_project():
            run_cli("plan")
            run_cli("apply")
    finally:
        plan_apply.run_render_pipeline = original_pipeline
    plan_result, apply_result = recorded_results[0], recorded_results[1]
    check(len(plan_result.stage_result_specs) == 3, "pipeline: one StageResultSpec per enabled stage")
    check(plan_result.stage_result_specs == apply_result.stage_result_specs,
          "plan and apply: identical StageResultSpecs")
    check(plan_result.artifacts == apply_result.artifacts, "plan and apply: identical artifacts (paths and bytes)")
    check(all(spec.provenance.publisher_identity == "5125793" for spec in plan_result.stage_result_specs),
          "pipeline: StageResultSpec provenance carries the configured publisher app_id")


class _RendererThatFailsOnSecurityStage(GitHubPlatformRenderer):
    """Renders the first stages normally, then rejects the `security` stage."""

    def render_stage(self, plan, stage, render_context):
        if stage.id == "security":
            raise ValueError("injected renderer failure for stage 'security'")
        return super().render_stage(plan, stage, render_context)


class _RendererThatWritesOutsideItsArtifactDirectory(GitHubPlatformRenderer):
    def render_routing(self, render_context):
        super().render_routing(render_context)
        (self._output_dir / "stray.txt").write_text("outside the workflows directory", encoding="utf-8")


@contextmanager
def _github_renderer_replaced_by(renderer_class):
    original_target = platform_targets.PLATFORM_TARGETS["github"]
    platform_targets.PLATFORM_TARGETS["github"] = dataclasses.replace(
        original_target,
        create_renderer=lambda output_root, publisher_config: renderer_class(
            output_root, publisher_config.app_id, publisher_config.private_key_secret
        ),
    )
    try:
        yield
    finally:
        platform_targets.PLATFORM_TARGETS["github"] = original_target


def test_a_renderer_writing_outside_its_artifact_directory_is_rejected() -> None:
    with _github_renderer_replaced_by(_RendererThatWritesOutsideItsArtifactDirectory), dogfood_project() as project_root:
        before_run = snapshot_tree(project_root)
        exit_code, _, error_output = run_cli("apply")
        check(exit_code == 1 and "outside its artifact directory" in error_output,
              "apply: a renderer writing outside .github/workflows is rejected")
        check(snapshot_tree(project_root) == before_run, "stray renderer output: nothing reaches the project")


def test_a_failing_stage_aborts_before_anything_is_written() -> None:
    with _github_renderer_replaced_by(_RendererThatFailsOnSecurityStage), dogfood_project() as project_root:
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        workflow_directory.mkdir(parents=True)
        (workflow_directory / "stage-review.yml").write_text("name: previous review\n", encoding="utf-8")
        before_run = snapshot_tree(project_root)
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command)
            check(exit_code == 1 and "injected renderer failure" in error_output,
                  f"{command}: a renderer failure on one stage exits 1 with its message")
            check(snapshot_tree(project_root) == before_run,
                  f"{command}: a failure on the last stage leaves the target exactly as it was")


def test_rendering_uses_a_private_scratch_directory_that_is_removed() -> None:
    with dogfood_project() as project_root, tempfile.TemporaryDirectory() as scratch_parent:
        previous_temp_directory = tempfile.tempdir
        tempfile.tempdir = scratch_parent
        try:
            run_cli("plan")
            check(list(Path(scratch_parent).iterdir()) == [], "plan: the scratch render directory is removed afterwards")
            run_cli("apply")
            check(list(Path(scratch_parent).iterdir()) == [], "apply: the scratch render directory is removed afterwards")
        finally:
            tempfile.tempdir = previous_temp_directory
        check(not any(path.name.startswith(".") and path.suffix == ".stagr-tmp"
                      for path in (project_root / DEFAULT_WORKFLOW_DIRECTORY).iterdir()),
              "apply: no temporary write files are left beside the workflows")


def test_unsafe_target_paths_are_refused_before_any_write() -> None:
    with dogfood_project() as project_root:
        workflow_directory = project_root / DEFAULT_WORKFLOW_DIRECTORY
        workflow_directory.mkdir(parents=True)
        outside_file = project_root / "elsewhere.yml"
        outside_file.write_text("name: keep me\n", encoding="utf-8")
        os.symlink(outside_file, workflow_directory / "stage-review.yml")
        before_run = snapshot_tree(project_root)
        for command in ("plan", "apply"):
            exit_code, _, error_output = run_cli(command)
            check(exit_code == 1 and "not a regular file" in error_output,
                  f"{command}: a symlink in place of a workflow is refused")
        check(snapshot_tree(project_root) == before_run and outside_file.read_text() == "name: keep me\n",
              "symlink target: nothing written and the symlink destination is untouched")

        (project_root / "not-a-dir").write_text("a file", encoding="utf-8")
        exit_code, _, error_output = run_cli("apply", "--out", "not-a-dir")
        check(exit_code == 1 and "not a directory" in error_output, "apply: --out pointing at a file is refused")


def test_extends_base_config_is_resolved() -> None:
    with dogfood_project() as project_root:
        full_config = read_config(project_root)
        base_config = {"platform": {"publisher": full_config["platform"].pop("publisher")}}
        (project_root / ".agentic" / "base.yml").write_text(yaml.safe_dump(base_config), encoding="utf-8")
        rewrite_config(project_root, lambda config: (
            config["platform"].pop("publisher", None), config.__setitem__("extends", "base.yml")))
        exit_code, _, error_output = run_cli("plan")
        check(exit_code == 0, f"plan: an extends base that supplies the publisher is merged ({error_output.strip()})")


def test_explicit_backend_object_is_normalized_to_its_name() -> None:
    normalized_stages = normalize_config({
        "version": 2, "profile": "custom", "defaults": {"provider": "openai"},
        "stages": [{"id": "review", "type": "review", "backend": {"name": "codex"}}],
    })
    check(normalized_stages[0].backend == "codex" and normalized_stages[0].kind is StageKind.REVIEW,
          "normalize: schema-form backend {name: codex} resolves to the string 'codex'")
