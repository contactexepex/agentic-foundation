"""Compare rendered artifacts with the files on disk, and write them.

``stagr plan`` uses ``classify_artifacts`` to say what would happen; ``stagr apply`` uses the same
function, then ``write_artifacts`` for the files that are new or changed. Every path is confined
to the project root: a symlink or a directory at a target path is refused rather than followed.
"""
from __future__ import annotations

import enum
import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from stagr.core.models import RenderedArtifact


class ArtifactWriteError(Exception):
    """A target path cannot safely be written (symlink, directory, or outside the root)."""


class ArtifactStatus(enum.Enum):
    NEW = "new"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ArtifactEntry:
    """One artifact, its size and hash, and what writing it would do to the target."""

    artifact: RenderedArtifact
    status: ArtifactStatus

    @property
    def content_bytes(self) -> bytes:
        return self.artifact.content.encode("utf-8")

    @property
    def size_in_bytes(self) -> int:
        return len(self.content_bytes)

    @property
    def sha256_hex(self) -> str:
        return hashlib.sha256(self.content_bytes).hexdigest()


def classify_artifacts(
    project_root: Path, artifacts: tuple[RenderedArtifact, ...]
) -> tuple[ArtifactEntry, ...]:
    """Return one entry per artifact; raise ``ArtifactWriteError`` if any target is unsafe."""
    return tuple(_classify_artifact(project_root, artifact) for artifact in artifacts)


def write_artifacts(project_root: Path, entries: tuple[ArtifactEntry, ...]) -> None:
    """Write every new or changed entry; unchanged files are left untouched (idempotent)."""
    for entry in entries:
        if entry.status is ArtifactStatus.UNCHANGED:
            continue
        _write_atomically(project_root / entry.artifact.path, entry.content_bytes)


def _classify_artifact(project_root: Path, artifact: RenderedArtifact) -> ArtifactEntry:
    target_path = project_root / artifact.path
    _assert_target_is_safe(project_root, artifact.path)
    if not target_path.exists():
        return ArtifactEntry(artifact, ArtifactStatus.NEW)
    existing_bytes = target_path.read_bytes()
    is_identical = existing_bytes == artifact.content.encode("utf-8")
    return ArtifactEntry(artifact, ArtifactStatus.UNCHANGED if is_identical else ArtifactStatus.CHANGED)


def _assert_target_is_safe(project_root: Path, relative_path: str) -> None:
    """Refuse a symlink anywhere on the path below the root, and a directory as the target."""
    current_path = project_root
    for segment in relative_path.split("/"):
        current_path = current_path / segment
        if current_path.is_symlink():
            raise ArtifactWriteError(
                f"refusing to write {relative_path}: {current_path} is a symlink"
            )
    if current_path.is_dir():
        raise ArtifactWriteError(f"refusing to write {relative_path}: it is a directory")


def _write_atomically(target_path: Path, content_bytes: bytes) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=target_path.parent, prefix=f".{target_path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(file_descriptor, "wb") as temporary_file:
            temporary_file.write(content_bytes)
        os.chmod(temporary_name, 0o644)
        os.replace(temporary_name, target_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
