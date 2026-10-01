"""Static validation V-S06: skill file existence.

For each stage where ``skill`` is not None, the referenced skill id must resolve to a
``SKILL.md`` file. A repository's own copy, ``.agentic/skills/<id>/SKILL.md``, is used when
present, so a repository overrides a shipped skill by keeping its own copy. Otherwise the skill
must be one the toolkit ships, ``stagr/templates/skills/<id>/SKILL.md``. A skill found in
neither place raises :class:`~stagr.core.models.StaticValidationError` naming both paths.

Stages with ``skill=None`` are skipped — they do not require a skill file. Stages with
``enabled: false`` are skipped because disabled stages are removed before normalization and
never participate in the active pipeline.

Design source: design-docs/07-validation.md (V-S06).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import StaticValidationError

SHIPPED_SKILLS_DIRECTORY = Path(__file__).resolve().parent.parent / "templates" / "skills"


def validate_skill_file_existence(
    stages: list[dict[str, Any]],
    project_root: Path,
) -> None:
    """Raise StaticValidationError (V-S06) for any stage whose skill file is absent.

    Iterates over ``stages`` and, for each enabled stage where ``skill`` is not ``None``,
    checks that ``<project_root>/.agentic/skills/<skill_id>/SKILL.md`` or the shipped
    ``stagr/templates/skills/<skill_id>/SKILL.md`` exists on disk.

    Args:
        stages: Stage dicts to validate.  Each must be a dict.  The ``skill``
            key is optional; its absence is treated as ``None``.  Stages with
            ``enabled: false`` are skipped.
        project_root: The root directory of the operator's project — the
            directory that contains ``.agentic/config.yml``.

    Raises:
        StaticValidationError: V-S06 when a skill id escapes its directory, when the
            repository's copy resolves outside ``.agentic/skills``, or when the skill file
            exists in neither place, naming the stage id and both paths.
    """
    for stage in stages:
        if not stage.get("enabled", True):
            continue
        skill_id = stage.get("skill")
        if skill_id is None:
            continue
        stage_id = stage.get("id", "<unknown>")
        skill_path_obj = Path(skill_id)
        if skill_path_obj.is_absolute() or ".." in skill_path_obj.parts:
            raise StaticValidationError(
                f"V-S06: skill id '{skill_id}' contains path-escaping components; "
                f"skill ids must be simple identifiers"
            )
        repository_skill_file = project_root / ".agentic" / "skills" / skill_id / "SKILL.md"
        if repository_skill_file.is_file():
            _require_inside_repository_skills(stage_id, repository_skill_file, project_root)
            continue
        shipped_skill_file = SHIPPED_SKILLS_DIRECTORY / skill_id / "SKILL.md"
        if not shipped_skill_file.is_file():
            raise StaticValidationError(
                f"V-S06: stage '{stage_id}' references skill '{skill_id}' but no skill file "
                f"exists: neither the repository's {repository_skill_file} nor the shipped "
                f"{shipped_skill_file}"
            )


def _require_inside_repository_skills(
    stage_id: str, repository_skill_file: Path, project_root: Path
) -> None:
    try:
        real_file = repository_skill_file.resolve()
        # Use project_root.resolve() as the trusted anchor and append the skills path
        # lexically.  If the skills directory were resolved instead, a symlink at
        # .agentic/skills would make both paths resolve into the same external directory,
        # defeating the confinement check entirely.
        real_skills_base = project_root.resolve() / ".agentic" / "skills"
    except OSError:
        return  # resolve() failed for an unusual reason; is_file() already confirmed the file
    if not str(real_file).startswith(str(real_skills_base) + os.sep):
        raise StaticValidationError(
            f"V-S06: stage '{stage_id}' skill file resolves outside the project "
            f"skills directory (possible symlink escape): {repository_skill_file}"
        )
