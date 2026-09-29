"""Compare rendered artifacts with a target directory, and write them into it.

Used by ``stagr plan`` (classify only) and ``stagr apply`` (classify, then write). Both call
:func:`classify_artifacts`, so the status ``plan`` predicts is exactly what ``apply`` acts on.

Safety rules, all checked while classifying so that a problem is reported before anything
is written:

* the target directory, if it exists, must be a directory, and no directory on the way to it from the
  project root (the current directory) may be a symlink, because ``mkdir``/``mkstemp``/``os.replace``
  would follow it and write outside the checkout. A target outside the project root is the operator's
  explicit choice, so only its own final component is checked;
* an existing target path must be a regular file, never a directory or a symlink;
* only files named by the artifacts are ever written; nothing else in the directory is
  touched, and stale per-stage files are removed only by the explicit :func:`remove_stale_files`.
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from .errors import RenderPipelineError
from .render_pipeline import RenderedArtifact


# mkstemp creates files 0600; generated workflows are ordinary readable repository files.
_ARTIFACT_FILE_MODE = 0o644


class ArtifactStatus(str, Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ArtifactChange:
    """One artifact and how it differs from the file already at its target path."""

    artifact: RenderedArtifact
    target_path: Path
    status: ArtifactStatus


def classify_artifacts(
    target_directory: Path,
    artifacts: tuple[RenderedArtifact, ...],
) -> tuple[ArtifactChange, ...]:
    """Return a status for each artifact against ``target_directory`` without writing.

    Raises:
        RenderPipelineError: When the directory or a target path is not usable (see module docstring).
    """
    if target_directory.exists() and not target_directory.is_dir():
        raise RenderPipelineError(f"output path '{target_directory}' exists and is not a directory")
    _reject_symlinked_directory_chain(target_directory)
    return tuple(_classify_one(target_directory, artifact) for artifact in artifacts)


def _reject_symlinked_directory_chain(target_directory: Path) -> None:
    """Refuse an output path that reaches its directory through a symlink inside the project root."""
    project_root = Path(os.getcwd())
    absolute_target = Path(os.path.abspath(target_directory))
    if absolute_target.is_relative_to(project_root):
        path_parts = absolute_target.relative_to(project_root).parts
        directories_to_check = [
            project_root.joinpath(*path_parts[:prefix_length]) for prefix_length in range(1, len(path_parts) + 1)
        ]
    else:
        directories_to_check = [absolute_target]
    for directory in directories_to_check:
        if directory.is_symlink():
            raise RenderPipelineError(
                f"refusing to write through '{directory}': it is a symlink on the output path "
                f"'{target_directory}'"
            )


def _classify_one(target_directory: Path, artifact: RenderedArtifact) -> ArtifactChange:
    target_path = target_directory / artifact.relative_path
    if target_path.is_symlink() or (target_path.exists() and not target_path.is_file()):
        raise RenderPipelineError(f"refusing to replace '{target_path}': it is not a regular file")
    if not target_path.exists():
        status = ArtifactStatus.NEW
    elif target_path.read_bytes() == artifact.content:
        status = ArtifactStatus.UNCHANGED
    else:
        status = ArtifactStatus.CHANGED
    return ArtifactChange(artifact=artifact, target_path=target_path, status=status)


def write_changed_artifacts(changes: tuple[ArtifactChange, ...]) -> tuple[ArtifactChange, ...]:
    """Write every NEW or CHANGED artifact; leave UNCHANGED files untouched. Returns what was written.

    Each file is written to a temporary name beside its target and renamed into place, so a
    failure never leaves a half-written workflow.
    """
    written_changes = tuple(change for change in changes if change.status is not ArtifactStatus.UNCHANGED)
    for change in written_changes:
        _write_file_atomically(change.target_path, change.artifact.content)
    return written_changes


def _write_file_atomically(target_path: Path, content: bytes) -> None:
    """Write ``content`` beside ``target_path`` under a unique, exclusively created temporary name.

    ``tempfile.mkstemp`` creates the file with ``O_CREAT | O_EXCL`` under a random name, so a
    pre-existing file or symlink (for example one committed to the repository) can never be
    followed or reused; ``os.replace`` then swaps it in atomically.
    """
    target_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target_path.parent, prefix=f".{target_path.name}.", suffix=".stagr-tmp"
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content)
        os.chmod(temporary_path, _ARTIFACT_FILE_MODE)
        os.replace(temporary_path, target_path)
    finally:
        temporary_path.unlink(missing_ok=True)


def find_stale_files(
    target_directory: Path,
    artifacts: tuple[RenderedArtifact, ...],
    stage_artifact_glob: str,
) -> tuple[Path, ...]:
    """Return per-stage files in ``target_directory`` that no artifact would write.

    Only names matching ``stage_artifact_glob`` (for GitHub, ``stage-*.yml``) are considered,
    so workflows the operator wrote by hand are never reported as stale.
    """
    if not target_directory.is_dir():
        return ()
    rendered_names = {artifact.relative_path for artifact in artifacts}
    return tuple(
        stage_file
        for stage_file in sorted(target_directory.glob(stage_artifact_glob))
        if stage_file.is_file() and stage_file.name not in rendered_names
    )


def remove_stale_files(stale_files: tuple[Path, ...]) -> None:
    """Delete the given stale per-stage files."""
    for stale_file in stale_files:
        stale_file.unlink()
