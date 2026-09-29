"""`stagr plan` and `stagr apply` — run the render pipeline, then report it or write it.

Both commands call the same :func:`run_render_pipeline` (validation, normalization, Phase 1,
Phase 2 through the PlatformRenderer) and the same :func:`classify_artifacts`. They differ only
in the last step: `plan` prints what would change, `apply` writes it.
"""
from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

from ..core.artifact_target import (
    ArtifactChange,
    ArtifactStatus,
    classify_artifacts,
    find_stale_files,
    remove_stale_files,
    write_changed_artifacts,
)
from ..core.errors import RenderPipelineError
from ..core.render_pipeline import RenderPipelineResult, run_render_pipeline

_STATUS_MARKERS = {
    ArtifactStatus.NEW: "+ new      ",
    ArtifactStatus.CHANGED: "~ changed  ",
    ArtifactStatus.UNCHANGED: "= unchanged",
}


def _render_and_classify(
    args: argparse.Namespace,
    command_name: str,
) -> tuple[RenderPipelineResult, tuple[ArtifactChange, ...]] | None:
    """Run the shared pipeline and compare with the target; print the error and return None on failure."""
    try:
        pipeline_result = run_render_pipeline(args.config, Path.cwd(), args.platform)
        artifact_changes = classify_artifacts(args.out, pipeline_result.artifacts)
    except RenderPipelineError as pipeline_error:
        print(f"{command_name}: {pipeline_error}", file=sys.stderr)
        return None
    for warning in pipeline_result.warnings:
        print(f"{command_name}: warning: {warning}", file=sys.stderr)
    return pipeline_result, artifact_changes


def _print_unified_diff(artifact_change: ArtifactChange) -> None:
    artifact_name = artifact_change.artifact.relative_path
    current_lines = artifact_change.target_path.read_text(encoding="utf-8", errors="replace").splitlines()
    rendered_lines = artifact_change.artifact.content.decode("utf-8", errors="replace").splitlines()
    for diff_line in difflib.unified_diff(
        current_lines, rendered_lines, fromfile=f"a/{artifact_name}", tofile=f"b/{artifact_name}", lineterm=""
    ):
        print(f"      {diff_line}")


def _print_stale_files(stale_files: tuple[Path, ...], instruction: str) -> None:
    if stale_files:
        print(f"  stage workflows in the target that this config no longer renders ({instruction}):")
        for stale_file in stale_files:
            print(f"      ? {stale_file.name}")


def cmd_plan(args: argparse.Namespace) -> int:
    rendered = _render_and_classify(args, "plan")
    if rendered is None:
        return 1
    pipeline_result, artifact_changes = rendered

    print(f"stagr plan - would render {len(artifact_changes)} {pipeline_result.platform_name} "
          f"artifact(s) into {args.out}/")
    name_width = max((len(change.artifact.relative_path) for change in artifact_changes), default=0)
    for artifact_change in artifact_changes:
        artifact = artifact_change.artifact
        print(f"  {_STATUS_MARKERS[artifact_change.status]} {artifact.relative_path:<{name_width}}  "
              f"{artifact.size_bytes:>6} bytes  sha256:{artifact.sha256_hex}")
        if artifact_change.status is ArtifactStatus.CHANGED and args.diff:
            _print_unified_diff(artifact_change)
    _print_stale_files(
        find_stale_files(args.out, pipeline_result.artifacts, pipeline_result.stage_artifact_glob),
        "left untouched; `stagr apply --prune` removes them",
    )
    print("\nplan: dry run only - nothing was written.")
    return 0


def cmd_apply(args: argparse.Namespace) -> int:
    rendered = _render_and_classify(args, "apply")
    if rendered is None:
        return 1
    pipeline_result, artifact_changes = rendered

    stale_files = find_stale_files(args.out, pipeline_result.artifacts, pipeline_result.stage_artifact_glob)
    try:
        written_changes = write_changed_artifacts(artifact_changes)
        if args.prune:
            remove_stale_files(stale_files)
    except OSError as write_failure:
        print(f"apply: cannot write to {args.out}: {write_failure}", file=sys.stderr)
        return 1

    for artifact_change in artifact_changes:
        verb = {
            ArtifactStatus.NEW: "+ wrote    ",
            ArtifactStatus.CHANGED: "~ updated  ",
            ArtifactStatus.UNCHANGED: "= unchanged",
        }[artifact_change.status]
        print(f"  {verb} {artifact_change.artifact.relative_path}")

    if args.prune:
        for stale_file in stale_files:
            print(f"  - pruned    {stale_file.name}")
    else:
        _print_stale_files(stale_files, "kept; pass --prune to remove them")

    print(f"\napply: {len(written_changes)} file(s) written, "
          f"{len(artifact_changes) - len(written_changes)} unchanged"
          + (f", {len(stale_files)} stale pruned" if args.prune else ""))
    return 0
