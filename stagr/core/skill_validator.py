"""Static validation V-S06: skill file existence.

For each stage where ``skill`` is not None, the referenced skill id must resolve
to an existing ``.agentic/skills/<id>/SKILL.md`` file.  A missing file raises
:class:`~stagr.core.models.StaticValidationError` naming the expected path.

Stages with ``skill=None`` (e.g. IMPLEMENT stages) are skipped — they do not
require a skill file.  Stages with ``enabled: false`` are skipped because
disabled stages are removed before normalization and never participate in the
active pipeline.

Design source: design-docs/07-validation.md (V-S06).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import StaticValidationError


def validate_skill_file_existence(
    stages: list[dict[str, Any]],
    project_root: Path,
) -> None:
    """Raise StaticValidationError (V-S06) for any stage whose skill file is absent.

    Iterates over ``stages`` and, for each enabled stage where ``skill`` is not
    ``None``, checks that the file
    ``<project_root>/.agentic/skills/<skill_id>/SKILL.md`` exists on disk.

    Args:
        stages: Stage dicts to validate.  Each must be a dict.  The ``skill``
            key is optional; its absence is treated as ``None``.  Stages with
            ``enabled: false`` are skipped.
        project_root: The root directory of the operator's project — the
            directory that contains ``.agentic/config.yml``.

    Raises:
        StaticValidationError: V-S06 when a required skill file is missing,
            naming the stage id and the expected file path.
    """
    for stage in stages:
        if not stage.get("enabled", True):
            continue
        skill_id = stage.get("skill")
        if skill_id is None:
            continue
        skill_path_obj = Path(skill_id)
        if skill_path_obj.is_absolute() or ".." in skill_path_obj.parts:
            raise StaticValidationError(
                f"V-S06: skill id '{skill_id}' contains path-escaping components; "
                f"skill ids must be simple identifiers"
            )
        expected_skill_file = project_root / ".agentic" / "skills" / skill_id / "SKILL.md"
        if not expected_skill_file.is_file():
            stage_id = stage.get("id", "<unknown>")
            raise StaticValidationError(
                f"V-S06: stage '{stage_id}' references skill '{skill_id}' "
                f"but the expected file does not exist: {expected_skill_file}"
            )
        try:
            real_file = expected_skill_file.resolve()
            # Use project_root.resolve() as the trusted anchor and append the skills path
            # lexically.  If the skills directory itself were resolved instead, a symlink at
            # .agentic/skills would make both real_file and real_skills_base resolve into
            # the same external directory, defeating the confinement check entirely.
            real_skills_base = project_root.resolve() / ".agentic" / "skills"
            if not str(real_file).startswith(str(real_skills_base) + os.sep):
                stage_id = stage.get("id", "<unknown>")
                raise StaticValidationError(
                    f"V-S06: stage '{stage_id}' skill file resolves outside the project "
                    f"skills directory (possible symlink escape): {expected_skill_file}"
                )
        except OSError:
            pass  # resolve() failed for an unusual reason; is_file() check already handled missing files
